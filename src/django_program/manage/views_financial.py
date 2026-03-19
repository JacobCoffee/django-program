"""Financial overview dashboard views for conference management.

Provides revenue summaries, order/cart/payment breakdowns, ticket sales
analytics, and recent transaction listings -- all scoped to the current
conference.
"""

import datetime
import json
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db.models import Count, Q, QuerySet, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.views.generic import TemplateView

from django_program.manage.reports import (
    get_aov_by_date,
    get_cashflow_waterfall,
    get_cumulative_revenue,
    get_discount_impact,
    get_refund_metrics,
    get_revenue_by_ticket_type,
    get_sales_by_date,
    get_ticket_inventory,
)
from django_program.manage.views import ConferencePermissionMixin
from django_program.programs.models import TravelGrant

if TYPE_CHECKING:
    from django_program.conference.models import Conference
from django_program.registration.models import (
    Attendee,
    Cart,
    Credit,
    Order,
    Payment,
    TicketType,
)

_ZERO = Decimal("0.00")


def _build_chart_context(
    conference: Conference,
    orders_by_status: dict[str, dict[str, object]],
    payments_by_method: dict[str, dict[str, object]],
) -> dict[str, str]:
    """Build JSON chart data for the financial dashboard template partials.

    Args:
        conference: The conference to scope queries to.
        orders_by_status: Order counts and totals keyed by status string.
        payments_by_method: Payment aggregation keyed by method string.

    Returns:
        Dict of JSON-encoded chart data strings, ready to inject into
        the template context.
    """
    sixty_days_ago = timezone.now().date() - datetime.timedelta(days=60)
    sales_data = get_sales_by_date(conference, date_from=sixty_days_ago)

    # -- AOV over time --
    aov_data = get_aov_by_date(conference, date_from=sixty_days_ago)

    # -- Revenue by ticket type --
    rev_by_type = get_revenue_by_ticket_type(conference, date_from=sixty_days_ago)

    # -- Discount impact --
    discount_data = get_discount_impact(conference)

    # -- Refund metrics --
    refund_data = get_refund_metrics(conference)

    # -- Cash flow waterfall --
    waterfall = get_cashflow_waterfall(conference)

    # -- Cumulative revenue --
    cumulative = get_cumulative_revenue(conference, date_from=sixty_days_ago)

    return {
        "chart_sales_json": json.dumps(
            [
                {"date": row["date"].isoformat(), "count": row["count"], "revenue": float(row["revenue"])}
                for row in sales_data
            ]
        ),
        "chart_orders_json": json.dumps(
            [
                {"status": status, "count": data["count"], "total": float(data["total"])}
                for status, data in orders_by_status.items()
                if data["count"] > 0
            ]
        ),
        "chart_payments_json": json.dumps(
            [
                {"method": method, "count": data["count"], "total": float(data["total_amount"])}
                for method, data in payments_by_method.items()
                if data["count"] > 0
            ]
        ),
        "chart_tickets_json": json.dumps(
            [
                {
                    "name": str(tt.name),
                    "sold": tt.sold_count,
                    "reserved": tt.reserved_count,
                    "remaining": (
                        max(0, tt.total_quantity - tt.sold_count - tt.reserved_count) if tt.total_quantity > 0 else 0
                    ),
                    "total": tt.total_quantity,
                }
                for tt in get_ticket_inventory(conference)
            ]
        ),
        "chart_aov_json": json.dumps(
            [{"date": row["date"].isoformat(), "aov": float(row["aov"]), "count": row["count"]} for row in aov_data]
        ),
        "chart_rev_by_type_json": json.dumps(
            [
                {
                    "date": row["date"].isoformat(),
                    "ticket_type": row["ticket_type"],
                    "revenue": float(row["revenue"]),
                    "count": row["count"],
                }
                for row in rev_by_type
            ]
        ),
        "chart_discount_json": json.dumps(
            {
                "total_discount": float(discount_data["total_discount"]),
                "total_gross": float(discount_data["total_gross"]),
                "total_net": float(discount_data["total_net"]),
                "discount_rate": float(discount_data["discount_rate"]),
                "by_voucher": discount_data["by_voucher"],
                "orders_with_discount": discount_data["orders_with_discount"],
                "orders_without_discount": discount_data["orders_without_discount"],
            }
        ),
        "chart_refund_json": json.dumps(
            {
                "total_refunded": float(refund_data["total_refunded"]),
                "total_revenue": float(refund_data["total_revenue"]),
                "refund_rate": float(refund_data["refund_rate"]),
                "refund_count": refund_data["refund_count"],
                "by_status": refund_data["by_status"],
            }
        ),
        "chart_waterfall_json": json.dumps(
            [{"label": step["label"], "value": float(step["value"]), "type": step["type"]} for step in waterfall]
        ),
        "chart_cumulative_json": json.dumps(
            [
                {"date": row["date"].isoformat(), "daily": float(row["daily"]), "cumulative": float(row["cumulative"])}
                for row in cumulative
            ]
        ),
    }


def _build_financial_budget_context(conference: Conference, total_revenue: Decimal) -> dict[str, object]:
    """Build budget-vs-actuals data for the financial dashboard.

    Uses the already-computed ``total_revenue`` for the revenue budget
    comparison instead of re-querying.

    Args:
        conference: The conference to compute budget data for.
        total_revenue: Pre-computed total paid revenue.

    Returns:
        A dict with budget metrics, empty if no budget fields are configured.
    """
    budget: dict[str, object] = {}

    if conference.revenue_budget:
        budget["revenue_target"] = conference.revenue_budget
        budget["revenue_actual"] = total_revenue
        budget["revenue_pct"] = (
            float(total_revenue / conference.revenue_budget * 100) if conference.revenue_budget else 0
        )

    if conference.target_attendance:
        actual_attendance = Attendee.objects.filter(conference=conference).count()
        budget["attendance_target"] = conference.target_attendance
        budget["attendance_actual"] = actual_attendance
        budget["attendance_pct"] = round(actual_attendance / conference.target_attendance * 100, 1)

    if conference.grant_budget:
        granted = (
            TravelGrant.objects.filter(
                conference=conference,
                status__in=[
                    TravelGrant.GrantStatus.ACCEPTED,
                    TravelGrant.GrantStatus.OFFERED,
                ],
            ).aggregate(total=Sum("approved_amount"))["total"]
            or _ZERO
        )
        disbursed = (
            TravelGrant.objects.filter(
                conference=conference,
                status=TravelGrant.GrantStatus.DISBURSED,
            ).aggregate(total=Sum("disbursed_amount"))["total"]
            or _ZERO
        )
        budget["grant_target"] = conference.grant_budget
        budget["grant_committed"] = granted
        budget["grant_disbursed"] = disbursed
        budget["grant_pct"] = float(granted / conference.grant_budget * 100) if conference.grant_budget else 0

    return budget


# Backward compatibility alias
FinancePermissionMixin = ConferencePermissionMixin


class FinancialDashboardView(ConferencePermissionMixin, TemplateView):
    """Comprehensive financial overview for a conference.

    Computes revenue totals, order/cart/payment breakdowns, ticket sales
    analytics, and surfaces recent orders and active carts.  All data is
    scoped to ``self.conference``.
    """

    template_name = "django_program/manage/financial_dashboard.html"
    required_permission = "view_finance"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:  # noqa: PLR0915
        """Build context with all financial metrics for the dashboard.

        Args:
            **kwargs: Additional context data.

        Returns:
            Template context containing revenue, order, cart, payment,
            ticket, and credit analytics.
        """
        context: dict[str, object] = super().get_context_data(**kwargs)
        conference = self.conference
        now = timezone.now()

        # --- Revenue ---
        revenue_agg = Order.objects.filter(
            conference=conference,
            status=Order.Status.PAID,
        ).aggregate(
            total_revenue=Sum("total"),
        )

        # Comment 1: compute refunds from Credit records tied to source orders
        # rather than summing Order.total for REFUNDED orders (which overstates
        # partial refunds).
        refund_agg = Credit.objects.filter(
            conference=conference,
            source_order__isnull=False,
        ).aggregate(
            total_refunded=Sum("amount"),
        )

        total_revenue = revenue_agg["total_revenue"] or _ZERO
        total_refunded = refund_agg["total_refunded"] or _ZERO
        net_revenue = total_revenue - total_refunded

        # Comment 4 & 6: "Credits Outstanding" should reflect the remaining
        # spendable balance, not the total ever issued.
        credits_agg = Credit.objects.filter(conference=conference).aggregate(
            total_issued=Sum("amount"),
            total_outstanding=Sum(
                "remaining_amount",
                filter=Q(status=Credit.Status.AVAILABLE),
            ),
            total_applied=Sum(
                "amount",
                filter=Q(status=Credit.Status.APPLIED),
            ),
        )
        total_credits_issued = credits_agg["total_issued"] or _ZERO
        total_credits_outstanding = credits_agg["total_outstanding"] or _ZERO
        total_credits_applied = credits_agg["total_applied"] or _ZERO

        context["revenue"] = {
            "total": total_revenue,
            "refunded": total_refunded,
            "net": net_revenue,
            "credits_issued": total_credits_issued,
            "credits_outstanding": total_credits_outstanding,
            "credits_applied": total_credits_applied,
        }

        # --- Orders by status (Comment 7: single aggregated query) ---
        order_qs = Order.objects.filter(conference=conference)
        order_status_rows = order_qs.values("status").annotate(
            count=Count("id"), total=Coalesce(Sum("total"), Value(_ZERO))
        )
        orders_by_status: dict[str, dict[str, object]] = {
            status_value: {"count": 0, "total": _ZERO} for status_value, _label in Order.Status.choices
        }
        for row in order_status_rows:
            orders_by_status[row["status"]] = {"count": row["count"], "total": row["total"] or _ZERO}
        total_orders = sum(d["count"] for d in orders_by_status.values())  # type: ignore[arg-type]
        context["orders_by_status"] = orders_by_status
        context["total_orders"] = total_orders

        # --- Carts by status ---
        cart_qs = Cart.objects.filter(conference=conference)
        active_cart_count = cart_qs.filter(
            Q(status=Cart.Status.OPEN),
            Q(expires_at__isnull=True) | Q(expires_at__gt=now),
        ).count()
        expired_cart_count = cart_qs.filter(status=Cart.Status.EXPIRED).count()
        checked_out_cart_count = cart_qs.filter(status=Cart.Status.CHECKED_OUT).count()
        abandoned_cart_count = cart_qs.filter(status=Cart.Status.ABANDONED).count()

        context["carts_by_status"] = {
            "active": active_cart_count,
            "expired": expired_cart_count,
            "checked_out": checked_out_cart_count,
            "abandoned": abandoned_cart_count,
        }

        # --- Payments by method (single aggregated query) ---
        payments_qs = Payment.objects.filter(order__conference=conference)
        method_labels: dict[str, str] = {v: str(label) for v, label in Payment.Method.choices}
        payments_by_method: dict[str, dict[str, object]] = {
            method_value: {"label": method_labels[method_value], "count": 0, "total_amount": _ZERO}
            for method_value in method_labels
        }
        for row in payments_qs.values("method").annotate(count=Count("id"), total_amount=Sum("amount")):
            payments_by_method[row["method"]] = {
                "label": method_labels[row["method"]],
                "count": row["count"],
                "total_amount": row["total_amount"] or _ZERO,
            }
        context["payments_by_method"] = payments_by_method

        # --- Payments by status (Comment 2: single aggregated query) ---
        payment_status_rows = payments_qs.values("status").annotate(count=Count("id"))
        payments_by_status: dict[str, int] = {status_value: 0 for status_value, _label in Payment.Status.choices}
        for row in payment_status_rows:
            payments_by_status[row["status"]] = row["count"]
        total_payments = sum(payments_by_status.values())
        context["payments_by_status"] = payments_by_status
        context["total_payments"] = total_payments

        # --- Ticket sales (Comment 3: Sum of quantity, include PARTIALLY_REFUNDED) ---
        paid_order_ids = Order.objects.filter(
            conference=conference,
            status__in=[Order.Status.PAID, Order.Status.PARTIALLY_REFUNDED],
        ).values_list("id", flat=True)

        ticket_sales: QuerySet[TicketType] = (
            TicketType.objects.filter(conference=conference)
            .annotate(
                sold_count=Coalesce(
                    Sum(
                        "order_line_items__quantity",
                        filter=Q(order_line_items__order_id__in=paid_order_ids),
                    ),
                    Value(0),
                ),
                ticket_revenue=Sum(
                    "order_line_items__line_total",
                    filter=Q(order_line_items__order_id__in=paid_order_ids),
                ),
            )
            .order_by("order", "name")
        )
        context["ticket_sales"] = ticket_sales

        # --- Recent orders ---
        recent_orders = Order.objects.filter(conference=conference).select_related("user").order_by("-created_at")[:20]
        context["recent_orders"] = recent_orders

        # --- Active carts ---
        active_carts = (
            Cart.objects.filter(
                conference=conference,
                status=Cart.Status.OPEN,
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .select_related("user")
            .annotate(item_count=Count("items"))
            .order_by("-created_at")
        )
        context["active_carts"] = active_carts

        # --- Chart JSON data for template partials ---
        context.update(_build_chart_context(conference, orders_by_status, payments_by_method))

        # Budget vs actuals
        budget = _build_financial_budget_context(conference, total_revenue)
        if budget:
            context["budget"] = budget
            context["chart_budget_json"] = json.dumps(
                {k: float(v) if isinstance(v, Decimal) else v for k, v in budget.items()}
            )

        # --- Expense & ROI data ---
        from django_program.manage.reports_analytics import (  # noqa: PLC0415
            get_event_roi,
            get_expense_summary,
        )

        expense_summary = get_expense_summary(conference)
        context["expense_summary"] = expense_summary

        roi_data = get_event_roi(conference)
        context["roi"] = roi_data
        context["chart_expense_json"] = json.dumps(
            {
                "by_category": [
                    {
                        "name": c["name"],
                        "budget": float(c["budget"]) if c["budget"] else 0,
                        "actual": float(c["actual"]),
                    }
                    for c in expense_summary["by_category"]
                ],
                "total_expenses": float(expense_summary["total_expenses"]),
                "total_budget": float(expense_summary["total_budget"]),
            }
        )

        context["active_nav"] = "financial"
        return context
