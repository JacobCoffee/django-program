"""URL configuration for the programs app.

Provides activity listing, detail, signup, and travel grant endpoints
scoped to a conference slug.  Mount these under a conference-scoped
prefix in the host project::

    urlpatterns = [
        path("<slug:conference_slug>/programs/", include("django_program.programs.urls")),
    ]
"""

from django.urls import path

from django_program.programs.views import (
    ActivityDetailView,
    ActivityListView,
    ActivitySignupView,
    TravelGrantApplyView,
)

app_name = "programs"

urlpatterns = [
    path("", ActivityListView.as_view(), name="activity-list"),
    path("<slug:slug>/", ActivityDetailView.as_view(), name="activity-detail"),
    path("<slug:slug>/signup/", ActivitySignupView.as_view(), name="activity-signup"),
    path("travel-grants/apply/", TravelGrantApplyView.as_view(), name="travel-grant-apply"),
]
