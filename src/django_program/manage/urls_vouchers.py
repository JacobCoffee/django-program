"""URL patterns for voucher bulk operations.

Included under ``<slug:conference_slug>/vouchers/bulk/`` in the main
management URL configuration.
"""

from django.urls import path

from django_program.manage.views_vouchers import VoucherBulkGenerateView

urlpatterns = [
    path("generate/", VoucherBulkGenerateView.as_view(), name="voucher-bulk-generate"),
]
