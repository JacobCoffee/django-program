"""Financial overview dashboard views for conference management.

Provides revenue summaries, order/cart/payment breakdowns, ticket sales
analytics, and recent transaction listings -- all scoped to the current
conference.
"""

from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, QuerySet, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpRequest, HttpResponse  # noqa: TC002
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.generic import TemplateView

from django_program.conference.models import Conference
from django_program.registration.models import (
    Cart,
    Credit,
    Order,
    Payment,
    TicketType,
)

_ZERO = Decimal("0.00")

_FINANCE_GROUP_NAME = "Program: Finance & Accounting"


class FinancePermissionMixin(LoginRequiredMixin):
    """Permission mixin for finance-scoped management views.

    Resolves the conference from the ``conference_slug`` URL kwarg and
    checks that the authenticated user satisfies at least one of:

    * is a superuser,
    * holds the ``program_conference.change_conference`` permission
      (Conference Organizers), or
    * belongs to the "Program: Finance & Accounting" group.

    Stores the resolved conference on ``self.conference`` and injects it
    into the template context alongside ``active_nav``.

    Raises:
        PermissionDenied: If the user fails all three checks.
    """

    conference: Conference
    kwargs: dict[str, str]

    def dispatch(self, request: HttpRequest, *args: str, **kwargs: str) -> HttpResponse:
        """Resolve the conference and enforce permissions before dispatch.

        Args:
            request: The incoming HTTP request.
            *args: Positional arguments from the URL resolver.
            **kwargs: Keyword arguments from the URL pattern.

        Returns:
            The HTTP response from the downstream view.

        Raises:
            PermissionDenied: If the user is not authorized.
        """
        if not request.user.is_authenticated:
            return self.handle_no_permission()  # type: ignore[return-value]

        self.conference = get_object_or_404(Conference, slug=kwargs.get("conference_slug", ""))

        user = request.user
        allowed = (
            user.is_superuser
            or user.has_perm("program_conference.change_conference")
            or user.groups.filter(name=_FINANCE_GROUP_NAME).exists()
        )
        if not allowed:
            raise PermissionDenied

        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add the conference to the template context.

        Args:
            **kwargs: Additional context data.

        Returns:
            Template context with ``conference`` included.
        """
        context: dict[str, object] = super().get_context_data(**kwargs)
        context["conference"] = self.conference
        return context


class FinancialDashboardView(FinancePermissionMixin, TemplateView):
    """Comprehensive financial overview for a conference.

    Computes revenue totals, order/cart/payment breakdowns, ticket sales
    analytics, and surfaces recent orders and active carts.  All data is
    scoped to ``self.conference`` (resolved by ``FinancePermissionMixin``).
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
        order_status_rows = order_qs.values("status").annotate(count=Count("id"))
        orders_by_status: dict[str, int] = {status_value: 0 for status_value, _label in Order.Status.choices}
        for row in order_status_rows:
            orders_by_status[row["status"]] = row["count"]
        total_orders = sum(orders_by_status.values())
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

        context["active_nav"] = "financial"
        return context
