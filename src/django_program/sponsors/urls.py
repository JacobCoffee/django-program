"""URL configuration for the sponsors app.

Provides sponsor listing and detail endpoints scoped to a conference slug.
Mount these under a conference-scoped prefix in the host project::

    urlpatterns = [
        path("<slug:conference_slug>/sponsors/", include("django_program.sponsors.urls")),
    ]
"""

from django.urls import path

from django_program.sponsors.views import SponsorDetailView, SponsorListView

app_name = "sponsors"

urlpatterns = [
    path("", SponsorListView.as_view(), name="sponsor-list"),
    path("<slug:slug>/", SponsorDetailView.as_view(), name="sponsor-detail"),
]
