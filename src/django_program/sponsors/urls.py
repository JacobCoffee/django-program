"""URL configuration for the sponsors app.

Provides sponsor listing and detail endpoints scoped to a conference slug,
plus the sponsor self-service portal for viewing purchases and requesting
bulk voucher codes.

Mount these under a conference-scoped prefix in the host project::

    urlpatterns = [
        path("<slug:conference_slug>/sponsors/", include("django_program.sponsors.urls")),
    ]
"""

from django.urls import path

from django_program.sponsors.views import (
    BulkPurchaseDetailView,
    BulkPurchaseExportCSVView,
    BulkPurchaseRequestView,
    SponsorDetailView,
    SponsorListView,
    SponsorPortalView,
)

app_name = "sponsors"

urlpatterns = [
    path("", SponsorListView.as_view(), name="sponsor-list"),
    # Sponsor self-service portal (must be above the slug catch-all)
    path("portal/", SponsorPortalView.as_view(), name="portal-home"),
    path("portal/purchases/<int:pk>/", BulkPurchaseDetailView.as_view(), name="portal-purchase-detail"),
    path("portal/purchases/<int:pk>/export/", BulkPurchaseExportCSVView.as_view(), name="portal-purchase-export"),
    path("portal/purchases/request/", BulkPurchaseRequestView.as_view(), name="portal-purchase-request"),
    # Slug catch-all must be last
    path("<slug:slug>/", SponsorDetailView.as_view(), name="sponsor-detail"),
]
