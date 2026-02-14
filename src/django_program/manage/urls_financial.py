"""URL patterns for the financial overview dashboard."""

from django.urls import path

from django_program.manage.views_financial import FinancialDashboardView

urlpatterns = [
    path("", FinancialDashboardView.as_view(), name="financial-dashboard"),
]
