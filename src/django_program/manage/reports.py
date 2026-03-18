"""Report service layer for conference admin reporting.

Provides data-access functions that return querysets and aggregated data for
nine report types: attendee manifest, product inventory, voucher usage,
discount effectiveness, sales by date, credit notes, speaker registration,
financial reconciliation, and registration flow. All queries are scoped to
a specific conference.
"""

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db.models import Avg, Count, Exists, F, OuterRef, Q, QuerySet, Sum, Value
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

if TYPE_CHECKING:
    import datetime

    from django_program.conference.models import Conference

from django_program.pretalx.models import Room, ScheduleSlot, Speaker, Talk
from django_program.programs.models import Activity, ActivitySignup, TravelGrant
from django_program.registration.models import (
    AddOn,
    Attendee,
    Cart,
    Credit,
    Order,
    OrderLineItem,
    Payment,
    TicketType,
    Voucher,
)
from django_program.sponsors.models import Sponsor, SponsorBenefit, SponsorLevel

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
        try:
            tt_id = int(ticket_type_id)
        except ValueError, TypeError:
            tt_id = None
        if tt_id:
            qs = qs.filter(
                order__line_items__ticket_type_id=tt_id,
                order__status__in=_PAID_STATUSES,
            ).distinct()

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
    the condition type label (e.g. "Speaker", "Product Discount") with a
    list of condition dicts.

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


def get_aov_by_date(
    conference: Conference,
    *,
    date_from: datetime.date | None = None,
    date_until: datetime.date | None = None,
) -> list[dict[str, Any]]:
    """Return daily average order value for paid orders.

    Groups paid orders by date, computes avg(total) per day.

    Args:
        conference: The conference to scope the query to.
        date_from: Optional lower bound (inclusive) for order date.
        date_until: Optional upper bound (inclusive) for order date.

    Returns:
        A list of dicts with ``date``, ``aov``, and ``count`` keys,
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
            aov=Coalesce(Avg("total"), Value(_ZERO)),
            count=Count("id"),
        )
        .order_by("date")
    )

    return [{"date": row["date"], "aov": row["aov"], "count": row["count"]} for row in rows]


def get_revenue_by_ticket_type(
    conference: Conference,
    *,
    date_from: datetime.date | None = None,
    date_until: datetime.date | None = None,
) -> list[dict[str, Any]]:
    """Return daily revenue broken down by ticket type.

    Joins OrderLineItem -> Order (paid), groups by date and ticket type name.

    Args:
        conference: The conference to scope the query to.
        date_from: Optional lower bound (inclusive) for order date.
        date_until: Optional upper bound (inclusive) for order date.

    Returns:
        A list of dicts with ``date``, ``ticket_type``, ``revenue``, and
        ``count`` keys, ordered chronologically then by ticket type.
    """
    qs = OrderLineItem.objects.filter(
        order__conference=conference,
        order__status__in=_PAID_STATUSES,
        ticket_type__isnull=False,
    )

    if date_from is not None:
        qs = qs.filter(order__created_at__date__gte=date_from)
    if date_until is not None:
        qs = qs.filter(order__created_at__date__lte=date_until)

    rows = (
        qs.annotate(date=TruncDate("order__created_at"))
        .values("date", "ticket_type__name")
        .annotate(
            revenue=Coalesce(Sum("line_total"), Value(_ZERO)),
            count=Coalesce(Sum("quantity"), Value(0)),
        )
        .order_by("date", "ticket_type__name")
    )

    return [
        {
            "date": row["date"],
            "ticket_type": row["ticket_type__name"],
            "revenue": row["revenue"],
            "count": row["count"],
        }
        for row in rows
    ]


def get_discount_impact(conference: Conference) -> dict[str, Any]:
    """Return discount impact metrics for paid orders.

    Computes total gross sales, net revenue, discount amounts, the discount
    rate as a percentage, and a per-voucher breakdown.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A dict with ``total_discount``, ``total_gross``, ``total_net``,
        ``discount_rate``, ``by_voucher``, ``orders_with_discount``, and
        ``orders_without_discount``.
    """
    paid_orders = Order.objects.filter(
        conference=conference,
        status__in=_PAID_STATUSES,
    )

    agg = paid_orders.aggregate(
        total_discount=Coalesce(Sum("discount_amount"), Value(_ZERO)),
        total_gross=Coalesce(Sum("subtotal"), Value(_ZERO)),
        total_net=Coalesce(Sum("total"), Value(_ZERO)),
        orders_with_discount=Count("id", filter=Q(discount_amount__gt=0)),
        orders_without_discount=Count("id", filter=Q(discount_amount=0)),
    )

    total_gross = agg["total_gross"]
    total_discount = agg["total_discount"]
    discount_rate = (total_discount / total_gross * 100) if total_gross else _ZERO

    by_voucher = list(
        paid_orders.filter(voucher_code__gt="")
        .values("voucher_code")
        .annotate(
            discount_total=Coalesce(Sum("discount_amount"), Value(_ZERO)),
            order_count=Count("id"),
        )
        .order_by("-discount_total")
        .values("voucher_code", "discount_total", "order_count")
    )

    by_voucher_serializable = [
        {
            "code": row["voucher_code"],
            "discount_total": float(row["discount_total"]),
            "order_count": row["order_count"],
        }
        for row in by_voucher
    ]

    return {
        "total_discount": total_discount,
        "total_gross": total_gross,
        "total_net": agg["total_net"],
        "discount_rate": discount_rate,
        "by_voucher": by_voucher_serializable,
        "orders_with_discount": agg["orders_with_discount"],
        "orders_without_discount": agg["orders_without_discount"],
    }


def get_refund_metrics(conference: Conference) -> dict[str, Any]:
    """Return refund and credit metrics for the conference.

    Computes total refunded amount (credits issued from source orders),
    total revenue, refund rate, and credit counts grouped by status.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A dict with ``total_refunded``, ``total_revenue``, ``refund_rate``,
        ``refund_count``, and ``by_status``.
    """
    refund_agg = Credit.objects.filter(
        conference=conference,
        source_order__isnull=False,
    ).aggregate(
        total_refunded=Coalesce(Sum("amount"), Value(_ZERO)),
        refund_count=Count("id"),
    )

    revenue_agg = Order.objects.filter(
        conference=conference,
        status__in=_PAID_STATUSES,
    ).aggregate(
        total_revenue=Coalesce(Sum("total"), Value(_ZERO)),
    )

    total_refunded = refund_agg["total_refunded"]
    total_revenue = revenue_agg["total_revenue"]
    refund_rate = (total_refunded / total_revenue * 100) if total_revenue else _ZERO

    status_rows = Credit.objects.filter(conference=conference).values("status").annotate(count=Count("id"))
    by_status: dict[str, int] = {
        Credit.Status.AVAILABLE: 0,
        Credit.Status.APPLIED: 0,
        Credit.Status.EXPIRED: 0,
    }
    for row in status_rows:
        by_status[row["status"]] = row["count"]

    return {
        "total_refunded": total_refunded,
        "total_revenue": total_revenue,
        "refund_rate": refund_rate,
        "refund_count": refund_agg["refund_count"],
        "by_status": by_status,
    }


def get_cashflow_waterfall(conference: Conference) -> list[dict[str, Any]]:
    """Return waterfall chart data for cash flow visualization.

    Computes gross sales, discount deductions, refund deductions, credits
    applied as an inflow, and the resulting net revenue.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A list of dicts with ``label``, ``value``, and ``type`` keys
        representing waterfall steps.
    """
    paid_orders = Order.objects.filter(
        conference=conference,
        status__in=_PAID_STATUSES,
    )

    order_agg = paid_orders.aggregate(
        gross=Coalesce(Sum("subtotal"), Value(_ZERO)),
        discounts=Coalesce(Sum("discount_amount"), Value(_ZERO)),
        net=Coalesce(Sum("total"), Value(_ZERO)),
    )

    refund_agg = Credit.objects.filter(
        conference=conference,
        source_order__isnull=False,
    ).aggregate(
        total_refunded=Coalesce(Sum("amount"), Value(_ZERO)),
    )

    credits_applied_agg = Credit.objects.filter(
        conference=conference,
        status=Credit.Status.APPLIED,
    ).aggregate(
        total_applied=Coalesce(Sum("amount"), Value(_ZERO)),
    )

    gross = order_agg["gross"]
    discounts = order_agg["discounts"]
    refunds = refund_agg["total_refunded"]
    credits_applied = credits_applied_agg["total_applied"]
    net_revenue = gross - discounts - refunds + credits_applied

    return [
        {"label": "Gross Sales", "value": gross, "type": "total"},
        {"label": "Discounts", "value": -discounts, "type": "decrease"},
        {"label": "Refunds", "value": -refunds, "type": "decrease"},
        {"label": "Credits Applied", "value": credits_applied, "type": "increase"},
        {"label": "Net Revenue", "value": net_revenue, "type": "total"},
    ]


def get_cumulative_revenue(
    conference: Conference,
    *,
    date_from: datetime.date | None = None,
    date_until: datetime.date | None = None,
) -> list[dict[str, Any]]:
    """Return cumulative revenue over time.

    Computes daily revenue from paid orders and a running total.

    Args:
        conference: The conference to scope the query to.
        date_from: Optional lower bound (inclusive) for order date.
        date_until: Optional upper bound (inclusive) for order date.

    Returns:
        A list of dicts with ``date``, ``daily``, and ``cumulative`` keys,
        ordered chronologically.
    """
    daily = get_sales_by_date(conference, date_from=date_from, date_until=date_until)

    cumulative = _ZERO
    result: list[dict[str, Any]] = []
    for row in daily:
        cumulative += row["revenue"]
        result.append(
            {
                "date": row["date"],
                "daily": row["revenue"],
                "cumulative": cumulative,
            }
        )

    return result


def get_revenue_per_attendee(conference: Conference) -> dict[str, Any]:
    """Return net revenue divided by total attendee count.

    Net revenue is the sum of paid order totals minus credits issued from
    refunds (source_order is not null).

    Args:
        conference: The conference to scope the query to.

    Returns:
        A dict with net_revenue, attendee_count, and revenue_per_attendee.
    """
    revenue_agg = Order.objects.filter(
        conference=conference,
        status__in=_PAID_STATUSES,
    ).aggregate(
        gross=Coalesce(Sum("total"), Value(_ZERO)),
    )

    refund_agg = Credit.objects.filter(
        conference=conference,
        source_order__isnull=False,
    ).aggregate(
        total_refunded=Coalesce(Sum("amount"), Value(_ZERO)),
    )

    net_revenue = revenue_agg["gross"] - refund_agg["total_refunded"]
    attendee_count = Attendee.objects.filter(conference=conference).count()
    revenue_per_attendee = (net_revenue / attendee_count) if attendee_count else _ZERO

    return {
        "net_revenue": net_revenue,
        "attendee_count": attendee_count,
        "revenue_per_attendee": revenue_per_attendee,
    }


def get_revenue_breakdown(conference: Conference) -> dict[str, Any]:
    """Return revenue breakdown by ticket, add-on, and sponsor sources.

    Ticket and add-on revenue come from paid order line items. Sponsor
    revenue is estimated from SponsorLevel cost multiplied by the number
    of active sponsors at each level.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A dict with ticket_revenue, addon_revenue, sponsor_revenue,
        total_revenue, and percentage breakdowns for each source.
    """
    ticket_agg = OrderLineItem.objects.filter(
        order__conference=conference,
        order__status__in=_PAID_STATUSES,
        ticket_type__isnull=False,
    ).aggregate(
        total=Coalesce(Sum("line_total"), Value(_ZERO)),
    )
    ticket_revenue: Decimal = ticket_agg["total"]

    addon_agg = OrderLineItem.objects.filter(
        order__conference=conference,
        order__status__in=_PAID_STATUSES,
        addon__isnull=False,
    ).aggregate(
        total=Coalesce(Sum("line_total"), Value(_ZERO)),
    )
    addon_revenue: Decimal = addon_agg["total"]

    sponsor_levels = SponsorLevel.objects.filter(conference=conference).annotate(
        active_count=Count("sponsors", filter=Q(sponsors__is_active=True)),
    )
    sponsor_revenue = _ZERO
    for level in sponsor_levels:
        sponsor_revenue += level.cost * level.active_count

    total_revenue = ticket_revenue + addon_revenue + sponsor_revenue

    def _pct(part: Decimal, whole: Decimal) -> Decimal:
        return (part / whole * 100) if whole else _ZERO

    return {
        "ticket_revenue": ticket_revenue,
        "addon_revenue": addon_revenue,
        "sponsor_revenue": sponsor_revenue,
        "total_revenue": total_revenue,
        "ticket_pct": _pct(ticket_revenue, total_revenue),
        "addon_pct": _pct(addon_revenue, total_revenue),
        "sponsor_pct": _pct(sponsor_revenue, total_revenue),
    }


def get_cart_funnel(conference: Conference) -> dict[str, Any]:
    """Return cart conversion funnel metrics.

    Counts carts by status and computes abandonment and conversion rates.
    Completed carts are those with CHECKED_OUT status.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A dict with total_carts, completed, abandoned, expired, open,
        abandonment_rate, and conversion_rate.
    """
    qs = Cart.objects.filter(conference=conference)
    agg = qs.aggregate(
        total_carts=Count("id"),
        completed=Count("id", filter=Q(status=Cart.Status.CHECKED_OUT)),
        abandoned=Count("id", filter=Q(status=Cart.Status.ABANDONED)),
        expired=Count("id", filter=Q(status=Cart.Status.EXPIRED)),
        open=Count("id", filter=Q(status=Cart.Status.OPEN)),
    )

    total = agg["total_carts"] or 0
    completed = agg["completed"] or 0
    abandoned = agg["abandoned"] or 0
    expired = agg["expired"] or 0
    open_count = agg["open"] or 0

    abandonment_rate = Decimal(abandoned + expired) / Decimal(total) * 100 if total else _ZERO
    conversion_rate = Decimal(completed) / Decimal(total) * 100 if total else _ZERO

    return {
        "total_carts": total,
        "completed": completed,
        "abandoned": abandoned,
        "expired": expired,
        "open": open_count,
        "abandonment_rate": abandonment_rate,
        "conversion_rate": conversion_rate,
    }


def get_ticket_sales_ratio(conference: Conference) -> list[dict[str, Any]]:
    """Return per-ticket-type sales data with availability windows.

    For each ticket type, reports the number sold, revenue generated,
    whether it is an early-bird ticket (time-limited availability), and
    the availability window as a human-readable string.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A list of dicts per ticket type with name, sold, revenue,
        is_early_bird, and availability_window.
    """
    ticket_types = (
        TicketType.objects.filter(conference=conference)
        .annotate(
            sold=Coalesce(
                Sum(
                    "order_line_items__quantity",
                    filter=Q(order_line_items__order__status__in=_PAID_STATUSES),
                ),
                Value(0),
            ),
            revenue=Coalesce(
                Sum(
                    "order_line_items__line_total",
                    filter=Q(order_line_items__order__status__in=_PAID_STATUSES),
                ),
                Value(_ZERO),
            ),
        )
        .order_by("order", "name")
    )

    total_revenue = sum((tt.revenue for tt in ticket_types), _ZERO)

    result: list[dict[str, Any]] = []
    for tt in ticket_types:
        is_early_bird = tt.available_from is not None and tt.available_until is not None
        window = f"{tt.available_from} - {tt.available_until}" if is_early_bird else "Always available"
        capacity = tt.total_quantity if tt.total_quantity > 0 else None
        fill_rate = (Decimal(tt.sold) / Decimal(capacity) * 100) if capacity else None
        revenue_pct = (tt.revenue / total_revenue * 100) if total_revenue else _ZERO

        result.append(
            {
                "name": str(tt.name),
                "sold": tt.sold,
                "revenue": tt.revenue,
                "is_early_bird": is_early_bird,
                "availability_window": window,
                "capacity": capacity,
                "fill_rate": fill_rate,
                "revenue_pct": revenue_pct,
            }
        )

    return result


def get_checkin_throughput(
    conference: Conference,
    *,
    bucket_minutes: int = 15,
) -> list[dict[str, Any]]:
    """Return time-bucketed check-in counts.

    Groups attendee check-in timestamps into fixed-width time buckets
    and returns the count per bucket, ordered chronologically.

    Args:
        conference: The conference to scope the query to.
        bucket_minutes: Width of each time bucket in minutes.

    Returns:
        A list of dicts with bucket_start, bucket_end, and count keys.
    """
    from datetime import timedelta  # noqa: PLC0415

    checkins = (
        Attendee.objects.filter(
            conference=conference,
            checked_in_at__isnull=False,
        )
        .values_list("checked_in_at", flat=True)
        .order_by("checked_in_at")
    )

    bucket_delta = timedelta(minutes=bucket_minutes)
    buckets: dict[Any, int] = {}

    for ts in checkins:
        # Truncate to the nearest bucket boundary
        epoch_seconds = int(ts.timestamp())
        bucket_seconds = bucket_minutes * 60
        truncated_epoch = (epoch_seconds // bucket_seconds) * bucket_seconds
        bucket_start = ts.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        ) + timedelta(seconds=truncated_epoch - int(ts.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()))
        buckets[bucket_start] = buckets.get(bucket_start, 0) + 1

    return [
        {
            "bucket_start": start,
            "bucket_end": start + bucket_delta,
            "count": count,
        }
        for start, count in sorted(buckets.items())
    ]


def get_room_utilization(conference: Conference) -> list[dict[str, Any]]:
    """Return per-room schedule utilization metrics.

    For each room, counts the total number of schedule slots and the
    number of slots that have an assigned talk.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A list of dicts with room_name, room_capacity, total_slots,
        talk_slots, and utilization_pct.
    """
    rooms = (
        Room.objects.filter(conference=conference)
        .annotate(
            total_slots=Count("schedule_slots"),
            talk_slots=Count("schedule_slots", filter=Q(schedule_slots__talk__isnull=False)),
        )
        .order_by("position", "name")
    )

    return [
        {
            "room_id": room.pk,
            "room_name": str(room.name),
            "room_capacity": room.capacity,
            "total_slots": room.total_slots,
            "talk_slots": room.talk_slots,
            "utilization_pct": (
                Decimal(room.talk_slots) / Decimal(room.total_slots) * 100 if room.total_slots else _ZERO
            ),
        }
        for room in rooms
    ]


def get_sponsor_benefit_fulfillment(conference: Conference) -> dict[str, Any]:
    """Return sponsor benefit fulfillment metrics.

    Aggregates benefit completion status across all sponsors and provides
    a per-sponsor breakdown with level information.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A dict with total_benefits, completed, pending, fulfillment_rate,
        and a by_sponsor list of per-sponsor details.
    """
    benefits = SponsorBenefit.objects.filter(sponsor__conference=conference)
    agg = benefits.aggregate(
        total_benefits=Count("id"),
        completed=Count("id", filter=Q(is_complete=True)),
        pending=Count("id", filter=Q(is_complete=False)),
    )

    total = agg["total_benefits"] or 0
    completed = agg["completed"] or 0
    pending = agg["pending"] or 0
    fulfillment_rate = Decimal(completed) / Decimal(total) * 100 if total else _ZERO

    by_sponsor_qs = (
        Sponsor.objects.filter(conference=conference)
        .select_related("level")
        .annotate(
            benefit_total=Count("benefits"),
            benefit_completed=Count("benefits", filter=Q(benefits__is_complete=True)),
            benefit_pending=Count("benefits", filter=Q(benefits__is_complete=False)),
        )
        .filter(benefit_total__gt=0)
        .order_by("level__order", "name")
    )

    by_sponsor = [
        {
            "sponsor_name": str(s.name),
            "level": str(s.level.name),
            "total": s.benefit_total,
            "completed": s.benefit_completed,
            "pending": s.benefit_pending,
        }
        for s in by_sponsor_qs
    ]

    return {
        "total_benefits": total,
        "completed": completed,
        "pending": pending,
        "fulfillment_rate": fulfillment_rate,
        "by_sponsor": by_sponsor,
    }


def get_travel_grant_analytics(conference: Conference) -> dict[str, Any]:
    """Return comprehensive travel grant application analytics.

    Aggregates grant applications by status, type, and amounts across
    the requested, approved, and disbursed lifecycle stages.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A dict with total_applications, by_status, approval_rate,
        disbursement_rate, average and total amounts for each stage,
        by_type breakdown, international_count, and first_time_count.
    """
    grants = TravelGrant.objects.filter(conference=conference)

    total_applications = grants.count()

    # By status
    by_status: dict[str, int] = {}
    status_rows = grants.values("status").annotate(count=Count("id"))
    for row in status_rows:
        by_status[row["status"]] = row["count"]

    # Approval and disbursement counts
    approved_statuses = {
        TravelGrant.GrantStatus.OFFERED,
        TravelGrant.GrantStatus.ACCEPTED,
        TravelGrant.GrantStatus.DISBURSED,
    }
    approved_count = sum(by_status.get(s, 0) for s in approved_statuses)
    disbursed_count = by_status.get(TravelGrant.GrantStatus.DISBURSED, 0)

    approval_rate = Decimal(approved_count) / Decimal(total_applications) * 100 if total_applications else _ZERO
    disbursement_rate = Decimal(disbursed_count) / Decimal(total_applications) * 100 if total_applications else _ZERO

    # Amount aggregations
    amount_agg = grants.aggregate(
        avg_requested=Coalesce(Avg("requested_amount"), Value(_ZERO)),
        avg_approved=Coalesce(Avg("approved_amount"), Value(_ZERO)),
        avg_disbursed=Coalesce(Avg("disbursed_amount"), Value(_ZERO)),
        total_requested=Coalesce(Sum("requested_amount"), Value(_ZERO)),
        total_approved=Coalesce(Sum("approved_amount"), Value(_ZERO)),
        total_disbursed=Coalesce(Sum("disbursed_amount"), Value(_ZERO)),
    )

    # By application type
    by_type: dict[str, int] = {}
    type_rows = grants.values("application_type").annotate(count=Count("id"))
    for row in type_rows:
        by_type[row["application_type"]] = row["count"]

    international_count = grants.filter(international=True).count()
    first_time_count = grants.filter(first_time=True).count()

    return {
        "total_applications": total_applications,
        "by_status": by_status,
        "approval_rate": approval_rate,
        "disbursement_rate": disbursement_rate,
        "avg_requested": amount_agg["avg_requested"],
        "avg_approved": amount_agg["avg_approved"],
        "avg_disbursed": amount_agg["avg_disbursed"],
        "total_requested": amount_agg["total_requested"],
        "total_approved": amount_agg["total_approved"],
        "total_disbursed": amount_agg["total_disbursed"],
        "by_type": by_type,
        "international_count": international_count,
        "first_time_count": first_time_count,
    }


def get_activity_utilization(conference: Conference) -> list[dict[str, Any]]:
    """Return per-activity signup utilization metrics.

    For each activity, counts confirmed, waitlisted, and cancelled
    signups and computes utilization as a percentage of max_participants.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A list of dicts per activity with name, activity_type,
        max_participants, confirmed, waitlisted, cancelled, and
        utilization_pct (None if max_participants is not set).
    """
    activities = (
        Activity.objects.filter(conference=conference)
        .annotate(
            confirmed=Count(
                "signups",
                filter=Q(signups__status=ActivitySignup.SignupStatus.CONFIRMED),
            ),
            waitlisted=Count(
                "signups",
                filter=Q(signups__status=ActivitySignup.SignupStatus.WAITLISTED),
            ),
            cancelled=Count(
                "signups",
                filter=Q(signups__status=ActivitySignup.SignupStatus.CANCELLED),
            ),
        )
        .order_by("start_time", "name")
    )

    return [
        {
            "activity_id": a.pk,
            "name": str(a.name),
            "activity_type": str(a.activity_type),
            "max_participants": a.max_participants,
            "confirmed": a.confirmed,
            "waitlisted": a.waitlisted,
            "cancelled": a.cancelled,
            "utilization_pct": (
                Decimal(a.confirmed) / Decimal(a.max_participants) * 100 if a.max_participants else None
            ),
        }
        for a in activities
    ]


def get_content_analytics(conference: Conference) -> dict[str, Any]:
    """Return content and schedule analytics for talks, rooms, and slots.

    Aggregates talk counts by state and submission type, room totals,
    and schedule slot counts by slot type.

    Args:
        conference: The conference to scope the query to.

    Returns:
        A dict with total_talks, by_state, by_type, by_track,
        total_rooms, total_schedule_slots, and slot_types.
    """
    talks = Talk.objects.filter(conference=conference)
    total_talks = talks.count()

    by_state: dict[str, int] = {}
    for row in talks.values("state").annotate(count=Count("id")):
        by_state[row["state"]] = row["count"]

    by_type: dict[str, int] = {}
    for row in talks.values("submission_type").annotate(count=Count("id")):
        by_type[row["submission_type"]] = row["count"]

    by_track: dict[str, int] = {}
    for row in talks.values("track").annotate(count=Count("id")):
        by_track[row["track"]] = row["count"]

    total_rooms = Room.objects.filter(conference=conference).count()

    slots = ScheduleSlot.objects.filter(conference=conference)
    total_schedule_slots = slots.count()

    slot_types: dict[str, int] = {}
    for row in slots.values("slot_type").annotate(count=Count("id")):
        slot_types[row["slot_type"]] = row["count"]

    return {
        "total_talks": total_talks,
        "by_state": by_state,
        "by_type": by_type,
        "by_track": by_track,
        "total_rooms": total_rooms,
        "total_schedule_slots": total_schedule_slots,
        "slot_types": slot_types,
    }
