"""Admin reporting dashboard views for conference management.

Provides attendee manifest, product inventory, voucher usage, and discount
effectiveness reports with CSV export support. All views are scoped to the
current conference and gated by report-level permissions.
"""

import csv

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.views import View
from django.views.generic import ListView, TemplateView

from django_program.conference.models import Conference
from django_program.manage.reports import (
    get_addon_inventory,
    get_attendee_manifest,
    get_attendee_summary,
    get_discount_conditions,
    get_discount_summary,
    get_ticket_inventory,
    get_voucher_summary,
    get_voucher_usage,
)
from django_program.registration.models import TicketType

_REPORTS_GROUP_NAME = "Program: Reports"


def _safe_csv_cell(value: object) -> str:
    """Return a CSV-safe string that cannot be interpreted as a formula."""
    text = str(value or "")
    stripped = text.lstrip()
    if stripped and stripped[0] in ("=", "+", "-", "@"):
        return f"'{text}"
    return text


class ReportPermissionMixin(LoginRequiredMixin):
    """Permission mixin for report-scoped management views.

    Resolves the conference from the ``conference_slug`` URL kwarg and
    checks that the authenticated user satisfies at least one of:

    * is a superuser,
    * holds the ``program_conference.change_conference`` permission, or
    * belongs to the "Program: Reports" group.

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
            or user.groups.filter(name=_REPORTS_GROUP_NAME).exists()
        )
        if not allowed:
            raise PermissionDenied

        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add the conference and active_nav to the template context.

        Args:
            **kwargs: Additional context data.

        Returns:
            Template context with ``conference`` and ``active_nav`` included.
        """
        context: dict[str, object] = super().get_context_data(**kwargs)
        context["conference"] = self.conference
        context["active_nav"] = "reports"
        return context


class ReportsDashboardView(ReportPermissionMixin, TemplateView):
    """Landing page for all admin reports with summary statistics."""

    template_name = "django_program/manage/reports_dashboard.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Build context with summary stats for all report types.

        Args:
            **kwargs: Additional context data.

        Returns:
            Template context with attendee, inventory, voucher, and discount summaries.
        """
        context: dict[str, object] = super().get_context_data(**kwargs)
        conference = self.conference

        context["attendee_summary"] = get_attendee_summary(conference)
        context["ticket_types"] = get_ticket_inventory(conference)
        context["voucher_summary"] = get_voucher_summary(conference)
        context["discount_summary"] = get_discount_summary(conference)

        return context


class AttendeeManifestView(ReportPermissionMixin, ListView):
    """Filterable attendee manifest with pagination."""

    template_name = "django_program/manage/report_attendee_manifest.html"
    context_object_name = "attendees"
    paginate_by = 50

    def get_queryset(self) -> object:
        """Return the filtered attendee queryset.

        Returns:
            A queryset of Attendee objects filtered by request parameters.
        """
        return get_attendee_manifest(
            self.conference,
            ticket_type_id=self.request.GET.get("ticket_type") or None,
            checked_in=self.request.GET.get("checked_in", ""),
            completed=self.request.GET.get("completed", ""),
        )

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add filter options and summary stats to context.

        Args:
            **kwargs: Additional context data.

        Returns:
            Template context with ticket types for filter dropdowns and summary stats.
        """
        context: dict[str, object] = super().get_context_data(**kwargs)
        context["ticket_types"] = TicketType.objects.filter(conference=self.conference).order_by("order", "name")
        context["attendee_summary"] = get_attendee_summary(self.conference)
        context["current_ticket_type"] = self.request.GET.get("ticket_type", "")
        context["current_checked_in"] = self.request.GET.get("checked_in", "")
        context["current_completed"] = self.request.GET.get("completed", "")
        return context


class AttendeeManifestExportView(ReportPermissionMixin, View):
    """CSV export of the attendee manifest."""

    def get(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Return a CSV download of the attendee manifest.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments.

        Returns:
            An HttpResponse with CSV content.
        """
        qs = get_attendee_manifest(
            self.conference,
            ticket_type_id=request.GET.get("ticket_type") or None,
            checked_in=request.GET.get("checked_in", ""),
            completed=request.GET.get("completed", ""),
        )

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{self.conference.slug}-attendees.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "Username",
                "Email",
                "Full Name",
                "Ticket Type",
                "Check-in Time",
                "Access Code",
                "Completed Registration",
            ]
        )

        for attendee in qs:
            # Determine ticket type from order line items
            ticket_name = ""
            if attendee.order:
                ticket_items = [li for li in attendee.order.line_items.all() if li.ticket_type_id is not None]
                if ticket_items:
                    ticket_name = ticket_items[0].description

            writer.writerow(
                [
                    _safe_csv_cell(attendee.user.username),
                    _safe_csv_cell(attendee.user.email),
                    _safe_csv_cell(attendee.user.get_full_name()),
                    _safe_csv_cell(ticket_name),
                    attendee.checked_in_at.isoformat() if attendee.checked_in_at else "",
                    _safe_csv_cell(attendee.access_code),
                    "Yes" if attendee.completed_registration else "No",
                ]
            )

        return response


class InventoryReportView(ReportPermissionMixin, TemplateView):
    """Product inventory and stock status report."""

    template_name = "django_program/manage/report_inventory.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Build context with ticket type and add-on inventory data.

        Args:
            **kwargs: Additional context data.

        Returns:
            Template context with ticket_types and addons querysets.
        """
        context: dict[str, object] = super().get_context_data(**kwargs)
        context["ticket_types"] = get_ticket_inventory(self.conference)
        context["addons"] = get_addon_inventory(self.conference)
        return context


class InventoryReportExportView(ReportPermissionMixin, View):
    """CSV export of product inventory."""

    def get(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Return a CSV download of inventory data.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments.

        Returns:
            An HttpResponse with CSV content.
        """
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{self.conference.slug}-inventory.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "Type",
                "Name",
                "Price",
                "Total Quantity",
                "Sold",
                "Reserved",
                "Remaining",
                "Active",
                "Available From",
                "Available Until",
            ]
        )

        for tt in get_ticket_inventory(self.conference):
            remaining = tt.total_quantity - tt.sold_count - tt.reserved_count if tt.total_quantity > 0 else "Unlimited"
            writer.writerow(
                [
                    "Ticket",
                    _safe_csv_cell(str(tt.name)),
                    str(tt.price),
                    tt.total_quantity if tt.total_quantity > 0 else "Unlimited",
                    tt.sold_count,
                    tt.reserved_count,
                    remaining,
                    "Yes" if tt.is_active else "No",
                    tt.available_from.isoformat() if tt.available_from else "",
                    tt.available_until.isoformat() if tt.available_until else "",
                ]
            )

        for addon in get_addon_inventory(self.conference):
            remaining = (
                addon.total_quantity - addon.sold_count - addon.reserved_count
                if addon.total_quantity > 0
                else "Unlimited"
            )
            writer.writerow(
                [
                    "Add-on",
                    _safe_csv_cell(str(addon.name)),
                    str(addon.price),
                    addon.total_quantity if addon.total_quantity > 0 else "Unlimited",
                    addon.sold_count,
                    addon.reserved_count,
                    remaining,
                    "Yes" if addon.is_active else "No",
                    addon.available_from.isoformat() if addon.available_from else "",
                    addon.available_until.isoformat() if addon.available_until else "",
                ]
            )

        return response


class VoucherUsageReportView(ReportPermissionMixin, TemplateView):
    """Voucher usage and redemption rates report."""

    template_name = "django_program/manage/report_voucher_usage.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Build context with voucher usage data and summary stats.

        Args:
            **kwargs: Additional context data.

        Returns:
            Template context with vouchers queryset and summary.
        """
        context: dict[str, object] = super().get_context_data(**kwargs)
        context["vouchers"] = get_voucher_usage(self.conference)
        context["voucher_summary"] = get_voucher_summary(self.conference)
        return context


class VoucherUsageExportView(ReportPermissionMixin, View):
    """CSV export of voucher usage data."""

    def get(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Return a CSV download of voucher usage data.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments.

        Returns:
            An HttpResponse with CSV content.
        """
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{self.conference.slug}-vouchers.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "Code",
                "Type",
                "Discount Value",
                "Max Uses",
                "Times Used",
                "Redemption Rate",
                "Revenue Impact",
                "Active",
                "Valid From",
                "Valid Until",
            ]
        )

        for voucher in get_voucher_usage(self.conference):
            redemption_rate = f"{(voucher.times_used / voucher.max_uses * 100):.1f}%" if voucher.max_uses > 0 else "N/A"
            writer.writerow(
                [
                    _safe_csv_cell(str(voucher.code)),
                    voucher.get_voucher_type_display(),
                    str(voucher.discount_value),
                    voucher.max_uses,
                    voucher.times_used,
                    redemption_rate,
                    str(voucher.revenue_impact),
                    "Yes" if voucher.is_active else "No",
                    voucher.valid_from.isoformat() if voucher.valid_from else "",
                    voucher.valid_until.isoformat() if voucher.valid_until else "",
                ]
            )

        return response


class DiscountEffectivenessView(ReportPermissionMixin, TemplateView):
    """Discount conditions overview and effectiveness report."""

    template_name = "django_program/manage/report_discount_effectiveness.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Build context with discount conditions and summary stats.

        Args:
            **kwargs: Additional context data.

        Returns:
            Template context with conditions grouped by type and summary.
        """
        context: dict[str, object] = super().get_context_data(**kwargs)
        context["conditions_by_type"] = get_discount_conditions(self.conference)
        context["discount_summary"] = get_discount_summary(self.conference)
        return context


class DiscountEffectivenessExportView(ReportPermissionMixin, View):
    """CSV export of discount effectiveness data."""

    def get(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Return a CSV download of discount conditions data.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments.

        Returns:
            An HttpResponse with CSV content.
        """
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{self.conference.slug}-discounts.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "Name",
                "Type",
                "Active",
                "Priority",
                "Discount Type",
                "Discount Value",
                "Times Used",
                "Limit",
                "Applicable Products",
            ]
        )

        conditions_by_type = get_discount_conditions(self.conference)
        for conditions in conditions_by_type.values():
            for cond in conditions:
                writer.writerow(
                    [
                        _safe_csv_cell(cond["name"]),
                        cond["type"],
                        "Yes" if cond["is_active"] else "No",
                        cond["priority"],
                        cond.get("discount_type", ""),
                        str(cond.get("discount_value", "")),
                        cond.get("times_used", ""),
                        cond.get("limit", ""),
                        "; ".join(str(p) for p in cond.get("applicable_products", [])),
                    ]
                )

        return response
