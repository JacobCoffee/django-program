"""URL patterns for the analytics and KPI dashboards."""

from django.urls import path

from django_program.manage.views_analytics import (
    AnalyticsDashboardView,
    CrossEventDashboardView,
    SponsorAnalyticsView,
)

urlpatterns = [
    path("", AnalyticsDashboardView.as_view(), name="analytics-dashboard"),
    path("sponsors/", SponsorAnalyticsView.as_view(), name="sponsor-analytics"),
    path("cross-event/", CrossEventDashboardView.as_view(), name="cross-event-dashboard"),
]
