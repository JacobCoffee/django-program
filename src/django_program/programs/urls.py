"""URL configuration for the programs app.

Provides activity listing, detail, signup, travel grant application,
status, accept, decline, withdraw, edit, provide-info, and messaging
endpoints scoped to a conference slug.
"""

from django.urls import path

from django_program.programs.views import (
    ActivityDetailView,
    ActivityListView,
    ActivitySignupView,
    PaymentInfoView,
    ReceiptDeleteView,
    ReceiptUploadView,
    TravelGrantAcceptView,
    TravelGrantApplyView,
    TravelGrantDeclineView,
    TravelGrantEditView,
    TravelGrantMessageView,
    TravelGrantProvideInfoView,
    TravelGrantStatusView,
    TravelGrantWithdrawView,
)

app_name = "programs"

urlpatterns = [
    path("", ActivityListView.as_view(), name="activity-list"),
    path("travel-grants/apply/", TravelGrantApplyView.as_view(), name="travel-grant-apply"),
    path("travel-grants/status/", TravelGrantStatusView.as_view(), name="travel-grant-status"),
    path("travel-grants/edit/", TravelGrantEditView.as_view(), name="travel-grant-edit"),
    path("travel-grants/accept/", TravelGrantAcceptView.as_view(), name="travel-grant-accept"),
    path("travel-grants/decline/", TravelGrantDeclineView.as_view(), name="travel-grant-decline"),
    path("travel-grants/withdraw/", TravelGrantWithdrawView.as_view(), name="travel-grant-withdraw"),
    path("travel-grants/provide-info/", TravelGrantProvideInfoView.as_view(), name="travel-grant-provide-info"),
    path("travel-grants/message/", TravelGrantMessageView.as_view(), name="travel-grant-message"),
    path("travel-grants/receipts/", ReceiptUploadView.as_view(), name="travel-grant-receipts"),
    path("travel-grants/receipts/<int:pk>/delete/", ReceiptDeleteView.as_view(), name="travel-grant-receipt-delete"),
    path("travel-grants/payment-info/", PaymentInfoView.as_view(), name="travel-grant-payment-info"),
    path("<slug:slug>/", ActivityDetailView.as_view(), name="activity-detail"),
    path("<slug:slug>/signup/", ActivitySignupView.as_view(), name="activity-signup"),
]
