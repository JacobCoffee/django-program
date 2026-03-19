"""URL patterns for bulk purchase management.

Included under ``<slug:conference_slug>/bulk-purchases/`` in the main
management URL configuration.
"""

from django.urls import path

from django_program.manage.views_bulk_purchases import (
    BulkPurchaseApproveView,
    BulkPurchaseCreateView,
    BulkPurchaseDetailView,
    BulkPurchaseFulfillView,
    BulkPurchaseListView,
)

urlpatterns = [
    path("", BulkPurchaseListView.as_view(), name="bulk-purchase-list"),
    path("add/", BulkPurchaseCreateView.as_view(), name="bulk-purchase-add"),
    path("<int:pk>/", BulkPurchaseDetailView.as_view(), name="bulk-purchase-detail"),
    path("<int:pk>/approve/", BulkPurchaseApproveView.as_view(), name="bulk-purchase-approve"),
    path("<int:pk>/fulfill/", BulkPurchaseFulfillView.as_view(), name="bulk-purchase-fulfill"),
]
