"""Report service layer for conference admin reporting.

Provides data-access functions that return querysets and aggregated data for
the attendee manifest, product inventory, voucher usage, and discount
effectiveness reports. All queries are scoped to a specific conference.
"""

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db.models import Count, Exists, F, OuterRef, Q, QuerySet, Sum, Value
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

if TYPE_CHECKING:
    import datetime

    from django_program.conference.models import Conference

from django_program.pretalx.models import Speaker
from django_program.registration.models import (
    AddOn,
    Attendee,
    Credit,
    Order,
    Payment,
    TicketType,
    Voucher,
)

_ZERO = Decimal("0.00")

_PAID_STATUSES = [Order.Status.PAID, Order.Status.PARTIALLY_REFUNDED]


def get_attendee_manifest(
    conference: Conference,
    *,
    ticket_type_id: int | str | None = None,
    checked_in: str = "",
    completed: str = "",
) -> QuerySet[Attendee]:
    """Return a filterable queryset of attendees for the manifest report.

    Joins through Attendee -> Order -> OrderLineItem -> TicketType to provide
    ticket information alongside attendee details.

    Args:
        conference: The conference to scope the query to.
        ticket_type_id: Optional filter by ticket type ID.
        checked_in: Filter by check-in status ("yes", "no", or empty for all).
        completed: Filter by completed registration ("yes", "no", or empty).

    Returns:
        A queryset of Attendee objects with select_related user and order.
    """
    qs = (
        Attendee.objects.filter(conference=conference)
        .select_related("user", "order")
        .prefetch_related("order__line_items__ticket_type")
        .order_by("user__last_name", "user__first_name", "user__username")
    )

    if checked_in == "yes":
        qs = qs.filter(checked_in_at__isnull=False)
    elif checked_in == "no":
        qs = qs.filter(checked_in_at__isnull=True)

    if completed == "yes":
        qs = qs.filter(completed_registration=True)
    elif completed == "no":
        qs = qs.filter(completed_registration=False)

    if ticket_type_id:
        qs = qs.filter(
            order__line_items__ticket_type_id=ticket_type_id,
            order__status__in=_PAID_STATUSES,
        )

    return qs


def get_attendee_summary(conference: Conference) -> dict[str, int]:
    """Return summary statistics for the attendee manifest.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A dict with total, checked_in, and completed counts.
    """
    qs = Attendee.objects.filter(conference=conference)
    agg = qs.aggregate(
        total=Count("id"),
        checked_in=Count("id", filter=Q(checked_in_at__isnull=False)),
        completed=Count("id", filter=Q(completed_registration=True)),
    )
    return {
        "total": agg["total"] or 0,
        "checked_in": agg["checked_in"] or 0,
        "completed": agg["completed"] or 0,
    }


def get_ticket_inventory(conference: Conference) -> QuerySet[TicketType]:
    """Return ticket type inventory with sold, reserved, and remaining counts.

    Sold count includes orders with paid or partially_refunded status.
    Reserved count includes pending orders with an active inventory hold.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A queryset of TicketType objects annotated with sold_count and reserved_count.
    """
    now = timezone.now()

    return (
        TicketType.objects.filter(conference=conference)
        .annotate(
            sold_count=Coalesce(
                Sum(
                    "order_line_items__quantity",
                    filter=Q(order_line_items__order__status__in=_PAID_STATUSES),
                ),
                Value(0),
            ),
            reserved_count=Coalesce(
                Sum(
                    "order_line_items__quantity",
                    filter=Q(
                        order_line_items__order__status=Order.Status.PENDING,
                        order_line_items__order__hold_expires_at__gt=now,
                    ),
                ),
                Value(0),
            ),
        )
        .order_by("order", "name")
    )


def get_addon_inventory(conference: Conference) -> QuerySet[AddOn]:
    """Return add-on inventory with sold, reserved, and remaining counts.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A queryset of AddOn objects annotated with sold_count and reserved_count.
    """
    now = timezone.now()

    return (
        AddOn.objects.filter(conference=conference)
        .annotate(
            sold_count=Coalesce(
                Sum(
                    "order_line_items__quantity",
                    filter=Q(order_line_items__order__status__in=_PAID_STATUSES),
                ),
                Value(0),
            ),
            reserved_count=Coalesce(
                Sum(
                    "order_line_items__quantity",
                    filter=Q(
                        order_line_items__order__status=Order.Status.PENDING,
                        order_line_items__order__hold_expires_at__gt=now,
                    ),
                ),
                Value(0),
            ),
        )
        .order_by("order", "name")
    )


def get_voucher_usage(conference: Conference) -> QuerySet[Voucher]:
    """Return voucher usage data with revenue impact annotations.

    Revenue impact is the sum of discount_amount from orders that used the
    voucher code (matched via Order.voucher_code).

    Args:
        conference: The conference to scope the query to.

    Returns:
        A queryset of Voucher objects annotated with revenue_impact.
    """
    return (
        Voucher.objects.filter(conference=conference)
        .annotate(
            revenue_impact=Coalesce(
                Sum(
                    "conference__orders__discount_amount",
                    filter=Q(
                        conference__orders__voucher_code=F("code"),
                        conference__orders__status__in=_PAID_STATUSES,
                    ),
                ),
                Value(Decimal("0.00")),
            ),
        )
        .order_by("-times_used", "code")
    )


def get_voucher_summary(conference: Conference) -> dict[str, Any]:
    """Return summary statistics for the voucher usage report.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A dict with total, active, used, and total_revenue_impact.
    """
    qs = Voucher.objects.filter(conference=conference)
    agg = qs.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(is_active=True)),
        used=Count("id", filter=Q(times_used__gt=0)),
    )

    # Revenue impact: sum discount_amount from paid orders that used any voucher code
    voucher_codes = list(qs.values_list("code", flat=True))
    revenue_impact_agg = Order.objects.filter(
        conference=conference,
        voucher_code__in=voucher_codes,
        status__in=_PAID_STATUSES,
    ).aggregate(
        total_impact=Sum("discount_amount"),
    )

    return {
        "total": agg["total"] or 0,
        "active": agg["active"] or 0,
        "used": agg["used"] or 0,
        "total_revenue_impact": revenue_impact_agg["total_impact"] or _ZERO,
    }


def _condition_to_dict(cond: object, type_label: str) -> dict[str, Any]:
    """Convert a condition model instance to a serializable dict.

    Args:
        cond: A concrete condition model instance.
        type_label: Human-readable label for the condition type.

    Returns:
        A dict with the condition's key attributes.
    """
    entry: dict[str, Any] = {
        "name": cond.name,  # type: ignore[attr-defined]
        "type": type_label,
        "is_active": cond.is_active,  # type: ignore[attr-defined]
        "priority": cond.priority,  # type: ignore[attr-defined]
    }
    if hasattr(cond, "times_used"):
        entry["times_used"] = cond.times_used  # type: ignore[attr-defined]
    if hasattr(cond, "limit"):
        entry["limit"] = cond.limit  # type: ignore[attr-defined]
    if hasattr(cond, "discount_type"):
        entry["discount_type"] = cond.get_discount_type_display()  # type: ignore[attr-defined]
        entry["discount_value"] = cond.discount_value  # type: ignore[attr-defined]
    if hasattr(cond, "percentage"):
        entry["discount_type"] = "Percentage"
        entry["discount_value"] = cond.percentage  # type: ignore[attr-defined]

    products: list[str] = []
    if hasattr(cond, "applicable_ticket_types"):
        products.extend(str(tt) for tt in cond.applicable_ticket_types.all())  # type: ignore[attr-defined]
    if hasattr(cond, "applicable_addons"):
        products.extend(str(ao) for ao in cond.applicable_addons.all())  # type: ignore[attr-defined]
    if hasattr(cond, "apply_to_tickets") and cond.apply_to_tickets:  # type: ignore[attr-defined]
        products.append("All ticket types")
    if hasattr(cond, "apply_to_addons") and cond.apply_to_addons:  # type: ignore[attr-defined]
        products.append("All add-ons")
    entry["applicable_products"] = products

    return entry


def get_discount_conditions(conference: Conference) -> dict[str, list[dict[str, Any]]]:
    """Return all discount/condition data grouped by condition type.

    Queries each concrete condition model and returns a flat dict keyed by
    the condition type slug with a list of condition dicts.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A dict mapping condition type names to lists of condition data dicts.
    """
    from django_program.registration.conditions import (  # noqa: PLC0415
        DiscountForCategory,
        DiscountForProduct,
        GroupMemberCondition,
        IncludedProductCondition,
        SpeakerCondition,
        TimeOrStockLimitCondition,
    )

    result: dict[str, list[dict[str, Any]]] = {}

    for model_class, type_label in [
        (TimeOrStockLimitCondition, "Time/Stock Limit"),
        (SpeakerCondition, "Speaker"),
        (GroupMemberCondition, "Group Member"),
        (IncludedProductCondition, "Included Product"),
        (DiscountForProduct, "Product Discount"),
        (DiscountForCategory, "Category Discount"),
    ]:
        qs = model_class.objects.filter(conference=conference).order_by("priority", "name")
        if hasattr(model_class, "applicable_ticket_types"):
            qs = qs.prefetch_related("applicable_ticket_types", "applicable_addons")
        conditions = qs
        entries = [_condition_to_dict(cond, type_label) for cond in conditions]
        if entries:
            result[type_label] = entries

    return result


def get_discount_summary(conference: Conference) -> dict[str, int]:
    """Return summary statistics for the discount effectiveness report.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A dict with total and active condition counts.
    """
    from django_program.registration.conditions import (  # noqa: PLC0415
        DiscountForCategory,
        DiscountForProduct,
        GroupMemberCondition,
        IncludedProductCondition,
        SpeakerCondition,
        TimeOrStockLimitCondition,
    )

    total = 0
    active = 0

    for model_class in [
        TimeOrStockLimitCondition,
        SpeakerCondition,
        GroupMemberCondition,
        IncludedProductCondition,
        DiscountForProduct,
        DiscountForCategory,
    ]:
        qs = model_class.objects.filter(conference=conference)
        agg = qs.aggregate(
            total=Count("id"),
            active=Count("id", filter=Q(is_active=True)),
        )
        total += agg["total"] or 0
        active += agg["active"] or 0

    return {"total": total, "active": active}


def get_sales_by_date(
    conference: Conference,
    *,
    date_from: datetime.date | None = None,
    date_until: datetime.date | None = None,
) -> list[dict[str, Any]]:
    """Return daily sales aggregation with order count and total revenue.

    Queries paid orders for the conference, grouped by the date portion of
    ``created_at``. Optionally filtered by a date range.

    Args:
        conference: The conference to scope the query to.
        date_from: Optional lower bound (inclusive) for order date.
        date_until: Optional upper bound (inclusive) for order date.

    Returns:
        A list of dicts with ``date``, ``count``, and ``revenue`` keys,
        ordered chronologically.
    """
    qs = Order.objects.filter(
        conference=conference,
        status__in=_PAID_STATUSES,
    )

    if date_from is not None:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_until is not None:
        qs = qs.filter(created_at__date__lte=date_until)

    rows = (
        qs.annotate(date=TruncDate("created_at"))
        .values("date")
        .annotate(
            count=Count("id"),
            revenue=Coalesce(Sum("total"), Value(_ZERO)),
        )
        .order_by("date")
    )

    return [
        {
            "date": row["date"],
            "count": row["count"],
            "revenue": row["revenue"],
        }
        for row in rows
    ]


def get_credit_notes(conference: Conference) -> QuerySet[Credit]:
    """Return all credit records for the conference with related objects.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A queryset of Credit objects with user, source_order, and
        applied_to_order pre-loaded.
    """
    return (
        Credit.objects.filter(conference=conference)
        .select_related("user", "source_order", "applied_to_order")
        .order_by("-created_at")
    )


def get_credit_summary(conference: Conference) -> dict[str, Any]:
    """Return summary statistics for credit notes.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A dict with total_issued, total_outstanding, total_applied, and count.
    """
    qs = Credit.objects.filter(conference=conference)
    agg = qs.aggregate(
        count=Count("id"),
        total_issued=Coalesce(Sum("amount"), Value(_ZERO)),
        total_outstanding=Coalesce(
            Sum("remaining_amount", filter=Q(status=Credit.Status.AVAILABLE)),
            Value(_ZERO),
        ),
        total_applied=Coalesce(
            Sum("amount", filter=Q(status=Credit.Status.APPLIED)),
            Value(_ZERO),
        ),
    )
    return {
        "count": agg["count"] or 0,
        "total_issued": agg["total_issued"],
        "total_outstanding": agg["total_outstanding"],
        "total_applied": agg["total_applied"],
    }


def get_speaker_registrations(conference: Conference) -> QuerySet[Speaker]:
    """Return speakers annotated with registration status.

    Joins through Speaker -> user -> Order to determine whether each speaker
    has a paid registration for the conference.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A queryset of Speaker objects annotated with ``has_paid_order`` and
        ``talk_count``.
    """
    return (
        Speaker.objects.filter(conference=conference)
        .select_related("user")
        .annotate(
            has_paid_order=Exists(
                Order.objects.filter(
                    conference=conference,
                    user_id=OuterRef("user_id"),
                    status__in=_PAID_STATUSES,
                )
            ),
            talk_count=Count("talks"),
        )
        .order_by("name")
    )


def get_reconciliation(conference: Conference) -> dict[str, Any]:
    """Return comprehensive financial reconciliation data.

    Computes sales totals, payment totals, refund/credit balances, and
    breakdowns by payment method and order status.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A dict with sales_total, payments_total, refunds_total,
        credits_outstanding, discrepancy, by_payment_method,
        and by_order_status.
    """
    sales_agg = Order.objects.filter(
        conference=conference,
        status__in=_PAID_STATUSES,
    ).aggregate(
        sales_total=Coalesce(Sum("total"), Value(_ZERO)),
    )
    sales_total = sales_agg["sales_total"]

    payments_agg = Payment.objects.filter(
        order__conference=conference,
        status=Payment.Status.SUCCEEDED,
    ).aggregate(
        payments_total=Coalesce(Sum("amount"), Value(_ZERO)),
    )
    payments_total = payments_agg["payments_total"]

    credit_agg = Credit.objects.filter(conference=conference).aggregate(
        refunds_total=Coalesce(
            Sum("amount", filter=Q(source_order__isnull=False)),
            Value(_ZERO),
        ),
        credits_outstanding=Coalesce(
            Sum("remaining_amount", filter=Q(status=Credit.Status.AVAILABLE)),
            Value(_ZERO),
        ),
    )
    refunds_total = credit_agg["refunds_total"]
    credits_outstanding = credit_agg["credits_outstanding"]

    by_payment_method = list(
        Payment.objects.filter(
            order__conference=conference,
            status=Payment.Status.SUCCEEDED,
        )
        .values("method")
        .annotate(
            count=Count("id"),
            total=Coalesce(Sum("amount"), Value(_ZERO)),
        )
        .order_by("method")
    )

    by_order_status = list(
        Order.objects.filter(conference=conference)
        .values("status")
        .annotate(
            count=Count("id"),
            total=Coalesce(Sum("total"), Value(_ZERO)),
        )
        .order_by("status")
    )

    return {
        "sales_total": sales_total,
        "payments_total": payments_total,
        "refunds_total": refunds_total,
        "credits_outstanding": credits_outstanding,
        "discrepancy": sales_total - payments_total,
        "by_payment_method": by_payment_method,
        "by_order_status": by_order_status,
    }


def get_registration_flow(
    conference: Conference,
    *,
    date_from: datetime.date | None = None,
    date_until: datetime.date | None = None,
) -> list[dict[str, Any]]:
    """Return daily registration and cancellation counts.

    Registrations are counted from Attendee creation dates. Cancellations
    are counted from Order records with status CANCELLED, grouped by the
    date portion of ``updated_at``.

    Args:
        conference: The conference to scope the query to.
        date_from: Optional lower bound (inclusive) for the date range.
        date_until: Optional upper bound (inclusive) for the date range.

    Returns:
        A list of dicts with ``date``, ``registrations``, and
        ``cancellations`` keys, ordered chronologically.
    """
    reg_qs = Attendee.objects.filter(conference=conference)
    cancel_qs = Order.objects.filter(
        conference=conference,
        status=Order.Status.CANCELLED,
    )

    if date_from is not None:
        reg_qs = reg_qs.filter(created_at__date__gte=date_from)
        cancel_qs = cancel_qs.filter(updated_at__date__gte=date_from)
    if date_until is not None:
        reg_qs = reg_qs.filter(created_at__date__lte=date_until)
        cancel_qs = cancel_qs.filter(updated_at__date__lte=date_until)

    reg_rows = (
        reg_qs.annotate(date=TruncDate("created_at"))
        .values("date")
        .annotate(registrations=Count("id"))
        .order_by("date")
    )

    cancel_rows = (
        cancel_qs.annotate(date=TruncDate("updated_at"))
        .values("date")
        .annotate(cancellations=Count("id"))
        .order_by("date")
    )

    merged: dict[datetime.date, dict[str, int]] = {}
    for row in reg_rows:
        merged.setdefault(row["date"], {"registrations": 0, "cancellations": 0})
        merged[row["date"]]["registrations"] = row["registrations"]

    for row in cancel_rows:
        merged.setdefault(row["date"], {"registrations": 0, "cancellations": 0})
        merged[row["date"]]["cancellations"] = row["cancellations"]

    return [
        {
            "date": date,
            "registrations": vals["registrations"],
            "cancellations": vals["cancellations"],
        }
        for date, vals in sorted(merged.items())
    ]
