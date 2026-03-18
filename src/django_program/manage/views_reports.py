"""Admin reporting dashboard views for conference management.

Provides attendee manifest, product inventory, voucher usage, and discount
effectiveness reports with CSV export support. All views are scoped to the
current conference and gated by report-level permissions.
"""

import csv
import datetime

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views import View
from django.views.generic import ListView, TemplateView

from django_program.conference.models import Conference
from django_program.manage.reports import (
    get_addon_inventory,
    get_attendee_manifest,
    get_attendee_summary,
    get_credit_notes,
    get_credit_summary,
    get_discount_conditions,
    get_discount_summary,
    get_reconciliation,
    get_registration_flow,
    get_sales_by_date,
    get_speaker_registrations,
    get_ticket_inventory,
    get_voucher_summary,
    get_voucher_usage,
)
from django_program.manage.views import _safe_csv_cell
from django_program.pretalx.models import Speaker
from django_program.registration.models import Order, Payment, TicketType

_REPORTS_GROUP_NAME = "Program: Reports"


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
        context["credit_summary"] = get_credit_summary(conference)
        context["speaker_count"] = Speaker.objects.filter(conference=conference).count()

        thirty_days_ago = timezone.now().date() - datetime.timedelta(days=30)
        recent_sales = get_sales_by_date(conference, date_from=thirty_days_ago)
        context["recent_sales_total"] = sum(row["revenue"] for row in recent_sales)

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

        # Precompute ticket descriptions to avoid trailing-comma issues in template
        attendees = context.get("attendees") or []
        for attendee in attendees:  # type: ignore[union-attr]
            if attendee.order:
                ticket_items = [li for li in attendee.order.line_items.all() if li.ticket_type_id is not None]
                attendee.ticket_descriptions = ", ".join(li.description for li in ticket_items)  # type: ignore[attr-defined]
            else:
                attendee.ticket_descriptions = ""  # type: ignore[attr-defined]

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
            # Join all ticket line item descriptions
            ticket_name = ""
            if attendee.order:
                ticket_items = [li for li in attendee.order.line_items.all() if li.ticket_type_id is not None]
                if ticket_items:
                    ticket_name = ", ".join(li.description for li in ticket_items)

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
            remaining = (
                max(0, tt.total_quantity - tt.sold_count - tt.reserved_count) if tt.total_quantity > 0 else "Unlimited"
            )
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
                max(0, addon.total_quantity - addon.sold_count - addon.reserved_count)
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
                        _safe_csv_cell("; ".join(str(p) for p in cond.get("applicable_products", []))),
                    ]
                )

        return response


def _parse_date_param(value: str | None) -> datetime.date | None:
    """Parse an ISO date string from a GET parameter.

    Args:
        value: A date string in YYYY-MM-DD format, or None/empty.

    Returns:
        A ``datetime.date`` instance, or ``None`` if parsing fails.
    """
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


class SalesByDateView(ReportPermissionMixin, TemplateView):
    """Daily sales aggregation report with date filtering."""

    template_name = "django_program/manage/report_sales_by_date.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Build context with daily sales data and summary totals.

        Args:
            **kwargs: Additional context data.

        Returns:
            Template context with sales rows and aggregate totals.
        """
        context: dict[str, object] = super().get_context_data(**kwargs)
        date_from = _parse_date_param(self.request.GET.get("date_from"))
        date_until = _parse_date_param(self.request.GET.get("date_until"))
        rows = get_sales_by_date(self.conference, date_from=date_from, date_until=date_until)

        context["sales_rows"] = rows
        context["total_orders"] = sum(r["count"] for r in rows)
        context["total_revenue"] = sum(r["revenue"] for r in rows)
        context["current_date_from"] = self.request.GET.get("date_from", "")
        context["current_date_until"] = self.request.GET.get("date_until", "")
        return context


class SalesByDateExportView(ReportPermissionMixin, View):
    """CSV export of daily sales data."""

    def get(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Return a CSV download of daily sales.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments.

        Returns:
            An HttpResponse with CSV content.
        """
        date_from = _parse_date_param(request.GET.get("date_from"))
        date_until = _parse_date_param(request.GET.get("date_until"))
        rows = get_sales_by_date(self.conference, date_from=date_from, date_until=date_until)

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{self.conference.slug}-sales-by-date.csv"'
        writer = csv.writer(response)
        writer.writerow(["Date", "Orders", "Revenue"])

        for row in rows:
            writer.writerow(
                [
                    row["date"].isoformat(),
                    row["count"],
                    str(row["revenue"]),
                ]
            )

        return response


class CreditNotesView(ReportPermissionMixin, TemplateView):
    """Credit notes listing with summary statistics."""

    template_name = "django_program/manage/report_credit_notes.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Build context with credit records and summary stats.

        Args:
            **kwargs: Additional context data.

        Returns:
            Template context with credits queryset and summary.
        """
        context: dict[str, object] = super().get_context_data(**kwargs)
        context["credits"] = get_credit_notes(self.conference)
        context["credit_summary"] = get_credit_summary(self.conference)
        return context


class CreditNotesExportView(ReportPermissionMixin, View):
    """CSV export of credit notes."""

    def get(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Return a CSV download of credit notes.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments.

        Returns:
            An HttpResponse with CSV content.
        """
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{self.conference.slug}-credit-notes.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "User",
                "Email",
                "Amount",
                "Remaining",
                "Status",
                "Source Order",
                "Applied To Order",
                "Note",
                "Created",
            ]
        )

        for credit in get_credit_notes(self.conference):
            writer.writerow(
                [
                    _safe_csv_cell(credit.user.get_full_name() or credit.user.username),
                    _safe_csv_cell(credit.user.email),
                    str(credit.amount),
                    str(credit.remaining_amount),
                    credit.get_status_display(),
                    credit.source_order.reference if credit.source_order else "",
                    credit.applied_to_order.reference if credit.applied_to_order else "",
                    _safe_csv_cell(credit.note),
                    credit.created_at.isoformat(),
                ]
            )

        return response


class SpeakerRegistrationView(ReportPermissionMixin, TemplateView):
    """Speaker registration status report."""

    template_name = "django_program/manage/report_speaker_registration.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Build context with speaker registration data.

        Args:
            **kwargs: Additional context data.

        Returns:
            Template context with speakers queryset.
        """
        context: dict[str, object] = super().get_context_data(**kwargs)
        speakers = get_speaker_registrations(self.conference)
        context["speakers"] = speakers
        total = speakers.count()
        registered = sum(1 for s in speakers if s.has_paid_order)
        context["total_speakers"] = total
        context["registered_count"] = registered
        context["unregistered_count"] = total - registered
        return context


class SpeakerRegistrationExportView(ReportPermissionMixin, View):
    """CSV export of speaker registration data."""

    def get(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Return a CSV download of speaker registration status.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments.

        Returns:
            An HttpResponse with CSV content.
        """
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{self.conference.slug}-speaker-registrations.csv"'
        writer = csv.writer(response)
        writer.writerow(["Name", "Email", "Talk Count", "Registered"])

        for speaker in get_speaker_registrations(self.conference):
            writer.writerow(
                [
                    _safe_csv_cell(str(speaker.name)),
                    _safe_csv_cell(speaker.email or (speaker.user.email if speaker.user else "")),
                    speaker.talk_count,
                    "Yes" if speaker.has_paid_order else "No",
                ]
            )

        return response


class ReconciliationView(ReportPermissionMixin, TemplateView):
    """Financial reconciliation report with stat cards and detail tables."""

    template_name = "django_program/manage/report_reconciliation.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Build context with reconciliation data.

        Args:
            **kwargs: Additional context data.

        Returns:
            Template context with reconciliation summary and breakdowns.
        """
        context: dict[str, object] = super().get_context_data(**kwargs)
        context["recon"] = get_reconciliation(self.conference)
        return context


class ReconciliationExportView(ReportPermissionMixin, View):
    """CSV export of financial reconciliation data."""

    def get(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Return a CSV download of reconciliation data.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments.

        Returns:
            An HttpResponse with CSV content.
        """
        recon = get_reconciliation(self.conference)

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{self.conference.slug}-reconciliation.csv"'
        writer = csv.writer(response)

        writer.writerow(["Section", "Item", "Count", "Amount"])
        writer.writerow(["Summary", "Total Sales", "", str(recon["sales_total"])])
        writer.writerow(["Summary", "Total Payments", "", str(recon["payments_total"])])
        writer.writerow(["Summary", "Credits Issued (Refunds)", "", str(recon["refunds_total"])])
        writer.writerow(["Summary", "Credits Outstanding", "", str(recon["credits_outstanding"])])
        writer.writerow(["Summary", "Discrepancy", "", str(recon["discrepancy"])])

        for row in recon["by_payment_method"]:
            label = dict(Payment.Method.choices).get(row["method"], row["method"])
            writer.writerow(["Payment Method", label, row["count"], str(row["total"])])

        for row in recon["by_order_status"]:
            label = dict(Order.Status.choices).get(row["status"], row["status"])
            writer.writerow(["Order Status", label, row["count"], str(row["total"])])

        return response


class RegistrationFlowView(ReportPermissionMixin, TemplateView):
    """Daily registrations and cancellations flow report."""

    template_name = "django_program/manage/report_registration_flow.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Build context with daily registration flow data.

        Args:
            **kwargs: Additional context data.

        Returns:
            Template context with flow rows and totals.
        """
        context: dict[str, object] = super().get_context_data(**kwargs)
        date_from = _parse_date_param(self.request.GET.get("date_from"))
        date_until = _parse_date_param(self.request.GET.get("date_until"))
        rows = get_registration_flow(self.conference, date_from=date_from, date_until=date_until)

        for row in rows:
            row["net"] = row["registrations"] - row["cancellations"]

        context["flow_rows"] = rows
        context["total_registrations"] = sum(r["registrations"] for r in rows)
        context["total_cancellations"] = sum(r["cancellations"] for r in rows)
        context["current_date_from"] = self.request.GET.get("date_from", "")
        context["current_date_until"] = self.request.GET.get("date_until", "")
        return context


class RegistrationFlowExportView(ReportPermissionMixin, View):
    """CSV export of registration flow data."""

    def get(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Return a CSV download of daily registration flow.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments.

        Returns:
            An HttpResponse with CSV content.
        """
        date_from = _parse_date_param(request.GET.get("date_from"))
        date_until = _parse_date_param(request.GET.get("date_until"))
        rows = get_registration_flow(self.conference, date_from=date_from, date_until=date_until)

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{self.conference.slug}-registration-flow.csv"'
        writer = csv.writer(response)
        writer.writerow(["Date", "Registrations", "Cancellations", "Net"])

        for row in rows:
            net = row["registrations"] - row["cancellations"]
            writer.writerow(
                [
                    row["date"].isoformat(),
                    row["registrations"],
                    row["cancellations"],
                    net,
                ]
            )

        return response
