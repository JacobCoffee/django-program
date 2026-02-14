"""Financial overview dashboard views for conference management.

Provides revenue summaries, order/cart/payment breakdowns, ticket sales
analytics, and recent transaction listings -- all scoped to the current
conference.
"""

from decimal import Decimal

from django.db.models import Count, Q, QuerySet, Sum
from django.utils import timezone
from django.views.generic import TemplateView

from django_program.manage.views import ManagePermissionMixin
from django_program.registration.models import (
    Cart,
    Credit,
    Order,
    Payment,
    TicketType,
)

_ZERO = Decimal("0.00")


class FinancialDashboardView(ManagePermissionMixin, TemplateView):
    """Comprehensive financial overview for a conference.

    Computes revenue totals, order/cart/payment breakdowns, ticket sales
    analytics, and surfaces recent orders and active carts.  All data is
    scoped to ``self.conference`` (resolved by ``ManagePermissionMixin``).
    """

    template_name = "django_program/manage/financial_dashboard.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
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
        refunded_agg = Order.objects.filter(
            conference=conference,
            status__in=[Order.Status.REFUNDED, Order.Status.PARTIALLY_REFUNDED],
        ).aggregate(
            total_refunded=Sum("total"),
        )

        total_revenue = revenue_agg["total_revenue"] or _ZERO
        total_refunded = refunded_agg["total_refunded"] or _ZERO
        net_revenue = total_revenue - total_refunded

        credits_agg = Credit.objects.filter(conference=conference).aggregate(
            total_issued=Sum("amount"),
            total_applied=Sum(
                "amount",
                filter=Q(status=Credit.Status.APPLIED),
            ),
        )
        total_credits_issued = credits_agg["total_issued"] or _ZERO
        total_credits_applied = credits_agg["total_applied"] or _ZERO

        context["revenue"] = {
            "total": total_revenue,
            "refunded": total_refunded,
            "net": net_revenue,
            "credits_issued": total_credits_issued,
            "credits_applied": total_credits_applied,
        }

        # --- Orders by status ---
        order_qs = Order.objects.filter(conference=conference)
        orders_by_status: dict[str, int] = {}
        for status_value, _label in Order.Status.choices:
            orders_by_status[status_value] = order_qs.filter(status=status_value).count()
        total_orders = order_qs.count()
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

        # --- Payments by method ---
        payments_qs = Payment.objects.filter(order__conference=conference)
        payments_by_method: dict[str, dict[str, object]] = {}
        for method_value, method_label in Payment.Method.choices:
            method_agg = payments_qs.filter(method=method_value).aggregate(
                count=Count("id"),
                total_amount=Sum("amount"),
            )
            payments_by_method[method_value] = {
                "label": str(method_label),
                "count": method_agg["count"] or 0,
                "total_amount": method_agg["total_amount"] or _ZERO,
            }
        context["payments_by_method"] = payments_by_method

        # --- Payments by status ---
        payments_by_status: dict[str, int] = {}
        for status_value, _label in Payment.Status.choices:
            payments_by_status[status_value] = payments_qs.filter(status=status_value).count()
        context["payments_by_status"] = payments_by_status

        # --- Ticket sales ---
        paid_order_ids = Order.objects.filter(
            conference=conference,
            status=Order.Status.PAID,
        ).values_list("id", flat=True)

        ticket_sales: QuerySet[TicketType] = (
            TicketType.objects.filter(conference=conference)
            .annotate(
                sold_count=Count(
                    "order_line_items",
                    filter=Q(order_line_items__order_id__in=paid_order_ids),
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

        context["active_nav"] = "financial"
        return context
