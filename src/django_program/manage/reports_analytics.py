"""Extended analytics and KPI report functions for conference management.

Provides Tier 2 (expense tracking, attribution, ratings, NPS) and
Tier 3 (cross-conference retention, LTV, renewal rates) analytics.
"""

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db.models import Avg, Count, Q, Sum, Value
from django.db.models.functions import Coalesce

if TYPE_CHECKING:
    from django_program.conference.models import Conference

from django_program.conference.models import Expense, ExpenseCategory
from django_program.pretalx.models import SessionRating, Speaker, Talk
from django_program.programs.models import Survey, SurveyResponse
from django_program.registration.models import Attendee, Order
from django_program.sponsors.models import Sponsor, SponsorLevel

_ZERO = Decimal("0.00")

_PAID_STATUSES = [Order.Status.PAID, Order.Status.PARTIALLY_REFUNDED]


# ---------------------------------------------------------------------------
# Tier 2: Single-conference analytics
# ---------------------------------------------------------------------------


def get_expense_summary(conference: Conference) -> dict[str, Any]:
    """Return expense totals and per-category breakdown for the conference.

    Budget variance is calculated as budget minus actual spending, so a
    positive value means under budget.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A dict with total_expenses, total_budget, budget_variance,
        budget_variance_pct, by_category, and expense_count.
    """
    categories = ExpenseCategory.objects.filter(conference=conference).annotate(
        actual=Coalesce(Sum("expenses__amount"), Value(_ZERO)),
        expense_count=Count("expenses"),
    )

    by_category: list[dict[str, Any]] = []
    total_expenses = _ZERO
    total_budget = _ZERO

    for cat in categories:
        actual = cat.actual  # type: ignore[attr-defined]
        budget = cat.budget_amount
        variance = (budget - actual) if budget is not None else None
        total_expenses += actual
        if budget is not None:
            total_budget += budget

        by_category.append(
            {
                "name": str(cat.name),
                "budget": budget,
                "actual": actual,
                "variance": variance,
                "expense_count": cat.expense_count,  # type: ignore[attr-defined]
            }
        )

    # Include expenses with no category match (orphaned categories are
    # already handled above; this covers the totals from Expense directly).
    direct_agg = Expense.objects.filter(conference=conference).aggregate(
        total=Coalesce(Sum("amount"), Value(_ZERO)),
        count=Count("id"),
    )
    total_expenses = direct_agg["total"]
    expense_count: int = direct_agg["count"]

    budget_variance = total_budget - total_expenses
    budget_variance_pct = (budget_variance / total_budget * 100) if total_budget else _ZERO

    return {
        "total_expenses": total_expenses,
        "total_budget": total_budget,
        "budget_variance": budget_variance,
        "budget_variance_pct": budget_variance_pct,
        "by_category": by_category,
        "expense_count": expense_count,
    }


def get_event_roi(conference: Conference) -> dict[str, Any]:
    """Return return-on-investment metrics for the conference.

    Revenue is drawn from paid orders; expenses from the Expense model.
    Division-by-zero cases return ``Decimal("0.00")``.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A dict with total_revenue, total_expenses, gross_profit,
        gross_margin_pct, net_profit, net_margin_pct, roi_pct,
        cost_per_attendee, and revenue_per_attendee.
    """
    revenue_agg = Order.objects.filter(
        conference=conference,
        status__in=_PAID_STATUSES,
    ).aggregate(
        total_revenue=Coalesce(Sum("total"), Value(_ZERO)),
    )
    total_revenue: Decimal = revenue_agg["total_revenue"]

    expense_agg = Expense.objects.filter(conference=conference).aggregate(
        total_expenses=Coalesce(Sum("amount"), Value(_ZERO)),
    )
    total_expenses: Decimal = expense_agg["total_expenses"]

    gross_profit = total_revenue - total_expenses
    gross_margin_pct = (gross_profit / total_revenue * 100) if total_revenue else _ZERO

    # Net profit is the same as gross here (no tax/overhead model yet).
    net_profit = gross_profit
    net_margin_pct = gross_margin_pct

    roi_pct = (total_revenue - total_expenses) / total_expenses * 100 if total_expenses else _ZERO

    attendee_count = Attendee.objects.filter(conference=conference).count()
    cost_per_attendee = total_expenses / attendee_count if attendee_count else _ZERO
    revenue_per_attendee = total_revenue / attendee_count if attendee_count else _ZERO

    return {
        "total_revenue": total_revenue,
        "total_expenses": total_expenses,
        "gross_profit": gross_profit,
        "gross_margin_pct": gross_margin_pct,
        "net_profit": net_profit,
        "net_margin_pct": net_margin_pct,
        "roi_pct": roi_pct,
        "cost_per_attendee": cost_per_attendee,
        "revenue_per_attendee": revenue_per_attendee,
    }


def get_registration_attribution(conference: Conference) -> dict[str, Any]:
    """Return registration attribution grouped by UTM parameters.

    Groups paid orders by utm_source, utm_medium, and utm_campaign,
    computing the count and revenue contribution of each.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A dict with by_source, by_medium, by_campaign lists, plus
        total_attributed and total_unattributed counts.
    """
    paid_orders = Order.objects.filter(
        conference=conference,
        status__in=_PAID_STATUSES,
    )

    def _group_by_field(field: str) -> list[dict[str, Any]]:
        rows = (
            paid_orders.filter(**{f"{field}__gt": ""})
            .values(field)
            .annotate(
                count=Count("id"),
                revenue=Coalesce(Sum("total"), Value(_ZERO)),
            )
            .order_by("-count")
        )
        return [{"name": row[field], "count": row["count"], "revenue": row["revenue"]} for row in rows]

    by_source = _group_by_field("utm_source")
    by_medium = _group_by_field("utm_medium")
    by_campaign = _group_by_field("utm_campaign")

    total_orders = paid_orders.count()
    unattributed = paid_orders.filter(
        utm_source="",
        utm_medium="",
        utm_campaign="",
    ).count()
    attributed = total_orders - unattributed

    return {
        "by_source": by_source,
        "by_medium": by_medium,
        "by_campaign": by_campaign,
        "total_attributed": attributed,
        "total_unattributed": unattributed,
    }


def get_session_rating_analytics(conference: Conference) -> dict[str, Any]:
    """Return session rating statistics, distribution, and rankings.

    Top and bottom sessions require a minimum of 3 ratings to qualify.
    Score distribution maps each score value (1-5) to its count.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A dict with total_ratings, average_score, score_distribution,
        top_sessions, bottom_sessions, and by_track.
    """
    ratings_qs = SessionRating.objects.filter(conference=conference)

    agg = ratings_qs.aggregate(
        total_ratings=Count("id"),
        average_score=Coalesce(Avg("score"), Value(_ZERO)),
    )
    total_ratings: int = agg["total_ratings"]
    average_score: Decimal = Decimal(str(agg["average_score"]))

    # Score distribution (1 through 5)
    dist_rows = ratings_qs.values("score").annotate(count=Count("id")).order_by("score")
    score_distribution: dict[int, int] = dict.fromkeys(range(1, 6), 0)
    for row in dist_rows:
        score_distribution[row["score"]] = row["count"]

    # Per-talk aggregation
    talk_stats = (
        ratings_qs.values("talk__id", "talk__title", "talk__track")
        .annotate(
            avg_score=Avg("score"),
            rating_count=Count("id"),
        )
        .filter(rating_count__gte=3)
    )

    def _talk_dict(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "talk_title": row["talk__title"],
            "avg_score": Decimal(str(round(row["avg_score"], 2))),
            "rating_count": row["rating_count"],
            "track": row["talk__track"] or "",
        }

    sorted_asc = sorted(talk_stats, key=lambda r: r["avg_score"])
    sorted_desc = sorted(talk_stats, key=lambda r: r["avg_score"], reverse=True)

    top_sessions = [_talk_dict(r) for r in sorted_desc[:10]]
    bottom_sessions = [_talk_dict(r) for r in sorted_asc[:10]]

    # By track
    track_rows = (
        ratings_qs.filter(talk__track__gt="")
        .values("talk__track")
        .annotate(
            avg_score=Avg("score"),
            rating_count=Count("id"),
        )
        .order_by("-avg_score")
    )
    by_track = [
        {
            "track": row["talk__track"],
            "avg_score": Decimal(str(round(row["avg_score"], 2))),
            "rating_count": row["rating_count"],
        }
        for row in track_rows
    ]

    return {
        "total_ratings": total_ratings,
        "average_score": average_score,
        "score_distribution": score_distribution,
        "top_sessions": top_sessions,
        "bottom_sessions": bottom_sessions,
        "by_track": by_track,
    }


def get_nps_score(
    conference: Conference,
    *,
    survey_slug: str | None = None,
) -> dict[str, Any]:
    """Return Net Promoter Score metrics for the conference.

    NPS is computed as the percentage of promoters (score 9-10) minus the
    percentage of detractors (score 0-6). Passives score 7-8.

    Args:
        conference: The conference to scope the query to.
        survey_slug: Optional slug to select a specific survey. When omitted,
            the first NPS-type survey for the conference is used.

    Returns:
        A dict with nps_score, promoters, passives, detractors,
        total_responses, promoter_pct, passive_pct, detractor_pct,
        and response_rate.
    """
    if survey_slug:
        survey = Survey.objects.filter(conference=conference, slug=survey_slug).first()
    else:
        survey = Survey.objects.filter(
            conference=conference,
            survey_type=Survey.SurveyType.NPS,
        ).first()

    empty: dict[str, Any] = {
        "nps_score": 0,
        "promoters": 0,
        "passives": 0,
        "detractors": 0,
        "total_responses": 0,
        "promoter_pct": _ZERO,
        "passive_pct": _ZERO,
        "detractor_pct": _ZERO,
        "response_rate": _ZERO,
    }

    if survey is None:
        return empty

    responses = SurveyResponse.objects.filter(survey=survey)
    agg = responses.aggregate(
        total=Count("id"),
        promoters=Count("id", filter=Q(score__gte=9)),
        detractors=Count("id", filter=Q(score__lte=6)),
        passives=Count("id", filter=Q(score__gte=7, score__lte=8)),
    )

    total: int = agg["total"] or 0
    promoters: int = agg["promoters"] or 0
    passives: int = agg["passives"] or 0
    detractors: int = agg["detractors"] or 0

    if total == 0:
        return empty

    promoter_pct = Decimal(promoters) / Decimal(total) * 100
    passive_pct = Decimal(passives) / Decimal(total) * 100
    detractor_pct = Decimal(detractors) / Decimal(total) * 100
    nps_score = round(promoter_pct - detractor_pct)

    attendee_count = Attendee.objects.filter(conference=conference).count()
    response_rate = Decimal(total) / Decimal(attendee_count) * 100 if attendee_count else _ZERO

    return {
        "nps_score": nps_score,
        "promoters": promoters,
        "passives": passives,
        "detractors": detractors,
        "total_responses": total,
        "promoter_pct": promoter_pct,
        "passive_pct": passive_pct,
        "detractor_pct": detractor_pct,
        "response_rate": response_rate,
    }


def get_sponsor_analytics(conference: Conference) -> dict[str, Any]:
    """Return sponsor-level analytics with revenue and benefit tracking.

    Aggregates sponsor counts, expected revenue (level cost * sponsor count),
    benefit fulfillment per level, and a pipeline view comparing actual
    sponsors to target capacity at each tier.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A dict with total_sponsors, total_sponsor_revenue, by_level list,
        overall_fulfillment_rate, and pipeline data.
    """
    levels = (
        SponsorLevel.objects.filter(conference=conference)
        .annotate(
            sponsor_count=Count("sponsors", filter=Q(sponsors__is_active=True)),
            total_benefits=Count("sponsors__benefits"),
            completed_benefits=Count(
                "sponsors__benefits",
                filter=Q(sponsors__benefits__is_complete=True),
            ),
        )
        .order_by("order", "name")
    )

    by_level: list[dict[str, Any]] = []
    total_sponsors = 0
    total_revenue = _ZERO
    total_benefits = 0
    total_completed = 0

    for level in levels:
        sponsor_count: int = level.sponsor_count  # type: ignore[attr-defined]
        level_revenue = level.cost * sponsor_count
        benefits: int = level.total_benefits  # type: ignore[attr-defined]
        completed: int = level.completed_benefits  # type: ignore[attr-defined]
        fulfillment = Decimal(completed) / Decimal(benefits) * 100 if benefits else _ZERO

        total_sponsors += sponsor_count
        total_revenue += level_revenue
        total_benefits += benefits
        total_completed += completed

        by_level.append(
            {
                "level_name": str(level.name),
                "level_slug": str(level.slug),
                "cost": level.cost,
                "sponsor_count": sponsor_count,
                "revenue": level_revenue,
                "total_benefits": benefits,
                "completed_benefits": completed,
                "fulfillment_rate": fulfillment,
            }
        )

    overall_fulfillment = Decimal(total_completed) / Decimal(total_benefits) * 100 if total_benefits else _ZERO

    return {
        "total_sponsors": total_sponsors,
        "total_sponsor_revenue": total_revenue,
        "by_level": by_level,
        "overall_fulfillment_rate": overall_fulfillment,
        "total_benefits": total_benefits,
        "total_completed_benefits": total_completed,
    }


# ---------------------------------------------------------------------------
# Tier 3: Cross-conference analytics
# ---------------------------------------------------------------------------


def get_yoy_retention(conference: Conference) -> dict[str, Any]:
    """Return year-over-year attendee retention metrics.

    A "returning" attendee is a user who has an Attendee record for both
    this conference and any conference with an earlier start_date.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A dict with current_attendee_count, returning_count, new_count,
        retention_rate, and previous_conferences.
    """
    from django_program.conference.models import Conference as ConferenceModel  # noqa: PLC0415

    current_user_ids = set(Attendee.objects.filter(conference=conference).values_list("user_id", flat=True))
    current_count = len(current_user_ids)

    previous_confs = ConferenceModel.objects.filter(
        start_date__lt=conference.start_date,
    ).order_by("-start_date")

    all_previous_user_ids: set[int] = set()
    previous_conferences: list[dict[str, Any]] = []

    for prev in previous_confs:
        prev_user_ids = set(Attendee.objects.filter(conference=prev).values_list("user_id", flat=True))
        shared = current_user_ids & prev_user_ids
        all_previous_user_ids |= prev_user_ids
        previous_conferences.append(
            {
                "name": str(prev.name),
                "slug": str(prev.slug),
                "shared_attendee_count": len(shared),
            }
        )

    returning_count = len(current_user_ids & all_previous_user_ids)
    new_count = current_count - returning_count
    retention_rate = Decimal(returning_count) / Decimal(current_count) * 100 if current_count else _ZERO

    return {
        "current_attendee_count": current_count,
        "returning_count": returning_count,
        "new_count": new_count,
        "retention_rate": retention_rate,
        "previous_conferences": previous_conferences,
    }


def get_attendee_lifetime_value(conference: Conference) -> dict[str, Any]:
    """Return attendee lifetime value metrics across all conferences.

    LTV is computed as the sum of all paid Order totals for each user
    who has placed at least one order for the given conference.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A dict with avg_ltv, max_ltv, min_ltv, total_users_with_orders,
        and top_users (top 20 by total spend).
    """
    # Users who have paid orders for this conference
    conf_user_ids = (
        Order.objects.filter(
            conference=conference,
            status__in=_PAID_STATUSES,
        )
        .values_list("user_id", flat=True)
        .distinct()
    )

    # Aggregate all paid orders across all conferences for those users
    user_ltv = (
        Order.objects.filter(
            user_id__in=conf_user_ids,
            status__in=_PAID_STATUSES,
        )
        .values("user_id", "user__username", "user__email")
        .annotate(
            total_spent=Coalesce(Sum("total"), Value(_ZERO)),
            order_count=Count("id"),
            conferences_attended=Count("conference_id", distinct=True),
        )
    )

    if not user_ltv.exists():
        return {
            "avg_ltv": _ZERO,
            "max_ltv": _ZERO,
            "min_ltv": _ZERO,
            "total_users_with_orders": 0,
            "top_users": [],
        }

    all_totals = list(user_ltv.values_list("total_spent", flat=True))
    avg_ltv = sum(all_totals, _ZERO) / len(all_totals) if all_totals else _ZERO
    max_ltv = max(all_totals) if all_totals else _ZERO
    min_ltv = min(all_totals) if all_totals else _ZERO

    top_users = [
        {
            "username": row["user__username"],
            "email": row["user__email"],
            "total_spent": row["total_spent"],
            "order_count": row["order_count"],
            "conferences_attended": row["conferences_attended"],
        }
        for row in user_ltv.order_by("-total_spent")[:20]
    ]

    return {
        "avg_ltv": avg_ltv,
        "max_ltv": max_ltv,
        "min_ltv": min_ltv,
        "total_users_with_orders": len(all_totals),
        "top_users": top_users,
    }


def get_sponsor_renewal_rate(conference: Conference) -> dict[str, Any]:
    """Return sponsor renewal metrics comparing to previous conferences.

    A "returning" sponsor is matched by name across conferences with an
    earlier start_date.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A dict with current_sponsor_count, returning_count, new_count,
        renewal_rate, and by_level breakdown.
    """
    current_sponsors = Sponsor.objects.filter(
        conference=conference,
    ).select_related("level")

    current_names = {str(s.name) for s in current_sponsors}
    current_count = len(current_names)

    previous_names = set(
        Sponsor.objects.filter(
            conference__start_date__lt=conference.start_date,
        ).values_list("name", flat=True)
    )

    returning_names = current_names & {str(n) for n in previous_names}
    returning_count = len(returning_names)
    new_count = current_count - returning_count
    renewal_rate = Decimal(returning_count) / Decimal(current_count) * 100 if current_count else _ZERO

    # Breakdown by level
    levels = SponsorLevel.objects.filter(conference=conference)
    by_level: list[dict[str, Any]] = []
    for level in levels:
        level_sponsors = [s for s in current_sponsors if s.level_id == level.pk]
        level_names = {str(s.name) for s in level_sponsors}
        level_returning = len(level_names & returning_names)
        by_level.append(
            {
                "level_name": str(level.name),
                "total": len(level_sponsors),
                "returning": level_returning,
                "new": len(level_sponsors) - level_returning,
            }
        )

    return {
        "current_sponsor_count": current_count,
        "returning_count": returning_count,
        "new_count": new_count,
        "renewal_rate": renewal_rate,
        "by_level": by_level,
    }


def get_speaker_return_rate(conference: Conference) -> dict[str, Any]:
    """Return speaker return-rate metrics for the conference.

    Speakers are matched to previous conferences by their linked user FK
    when available, falling back to a name + email combination.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A dict with current_speaker_count, returning_count, new_count,
        and return_rate.
    """
    current_speakers = Speaker.objects.filter(conference=conference)
    current_count = current_speakers.count()

    if current_count == 0:
        return {
            "current_speaker_count": 0,
            "returning_count": 0,
            "new_count": 0,
            "return_rate": _ZERO,
        }

    previous_speakers = Speaker.objects.filter(
        conference__start_date__lt=conference.start_date,
    )

    # Build lookup sets for previous speakers
    prev_user_ids = set(previous_speakers.filter(user__isnull=False).values_list("user_id", flat=True))
    prev_name_emails = set(previous_speakers.filter(user__isnull=True).values_list("name", "email"))

    returning = 0
    for speaker in current_speakers:
        matched_by_user = speaker.user_id is not None and speaker.user_id in prev_user_ids
        matched_by_name = speaker.user_id is None and (str(speaker.name), str(speaker.email)) in prev_name_emails
        if matched_by_user or matched_by_name:
            returning += 1

    new_count = current_count - returning
    return_rate = Decimal(returning) / Decimal(current_count) * 100

    return {
        "current_speaker_count": current_count,
        "returning_count": returning,
        "new_count": new_count,
        "return_rate": return_rate,
    }


def get_yoy_growth(conference: Conference) -> dict[str, Any]:
    """Return year-over-year growth metrics across conferences.

    Computes attendance, revenue, sponsor count, and talk count for the
    current conference and all previous ones, with growth percentages
    comparing the current conference to the most recent predecessor.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A dict with ``current`` stats, ``history`` list, and computed
        ``growth_pct`` fields comparing current to most recent previous.
    """
    from django_program.conference.models import Conference as ConferenceModel  # noqa: PLC0415

    def _conf_stats(conf: ConferenceModel) -> dict[str, Any]:
        attendance = Attendee.objects.filter(conference=conf).count()
        rev_agg = Order.objects.filter(
            conference=conf,
            status__in=_PAID_STATUSES,
        ).aggregate(revenue=Coalesce(Sum("total"), Value(_ZERO)))
        sponsors = Sponsor.objects.filter(conference=conf).count()
        talks = Talk.objects.filter(conference=conf).count()
        return {
            "name": str(conf.name),
            "attendance": attendance,
            "revenue": rev_agg["revenue"],
            "sponsors": sponsors,
            "talks": talks,
        }

    current = _conf_stats(conference)

    previous_confs = ConferenceModel.objects.filter(
        start_date__lt=conference.start_date,
    ).order_by("-start_date")

    history: list[dict[str, Any]] = [_conf_stats(c) for c in previous_confs]

    # Compute per-entry growth percentages between consecutive conferences.
    # history is newest-first; build a chronological list to compare pairs.
    chronological = [*reversed(history), current]
    for i in range(1, len(chronological)):
        prev_entry = chronological[i - 1]
        cur_entry = chronological[i]
        for metric in ("attendance", "revenue"):
            prev_val = prev_entry[metric]
            cur_val = cur_entry[metric]
            if isinstance(prev_val, Decimal):
                pct = (cur_val - prev_val) / prev_val * 100 if prev_val else _ZERO
            elif prev_val:
                pct = Decimal(cur_val - prev_val) / Decimal(prev_val) * 100
            else:
                pct = _ZERO
            cur_entry[f"{metric}_growth_pct"] = pct

    # Top-level growth vs most recent previous conference
    result: dict[str, Any] = {"current": current, "history": history}

    if history:
        prev = history[0]
        for metric in ("attendance", "revenue", "sponsors", "talks"):
            prev_val = prev[metric]
            cur_val = current[metric]
            if isinstance(prev_val, Decimal):
                pct = (cur_val - prev_val) / prev_val * 100 if prev_val else _ZERO
            elif prev_val:
                pct = Decimal(cur_val - prev_val) / Decimal(prev_val) * 100
            else:
                pct = _ZERO
            result[f"{metric}_growth_pct"] = pct

    return result
