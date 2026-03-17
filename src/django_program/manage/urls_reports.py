"""URL patterns for the admin reports dashboard."""

from django.urls import path

from django_program.manage.views_reports import (
    AttendeeManifestExportView,
    AttendeeManifestView,
    DiscountEffectivenessExportView,
    DiscountEffectivenessView,
    InventoryReportExportView,
    InventoryReportView,
    ReportsDashboardView,
    VoucherUsageExportView,
    VoucherUsageReportView,
)

urlpatterns = [
    path("", ReportsDashboardView.as_view(), name="reports-dashboard"),
    path("attendees/", AttendeeManifestView.as_view(), name="report-attendee-manifest"),
    path("attendees/export/", AttendeeManifestExportView.as_view(), name="report-attendee-export"),
    path("inventory/", InventoryReportView.as_view(), name="report-inventory"),
    path("inventory/export/", InventoryReportExportView.as_view(), name="report-inventory-export"),
    path("vouchers/", VoucherUsageReportView.as_view(), name="report-voucher-usage"),
    path("vouchers/export/", VoucherUsageExportView.as_view(), name="report-voucher-export"),
    path("discounts/", DiscountEffectivenessView.as_view(), name="report-discount-effectiveness"),
    path("discounts/export/", DiscountEffectivenessExportView.as_view(), name="report-discount-export"),
]
