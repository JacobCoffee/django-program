"""URL configuration for the registration app.

Includes ticket selection, cart operations, checkout, order views, and
Stripe webhook endpoints. Mount these under a conference-scoped prefix
in the host project::

    urlpatterns = [
        path(
            "<slug:conference_slug>/registration/",
            include("django_program.registration.urls"),
        ),
    ]
"""

from django.urls import path

from django_program.registration.views import (
    CartView,
    CheckoutView,
    LetterRequestCreateView,
    LetterRequestDetailView,
    LetterRequestDownloadView,
    OrderConfirmationView,
    OrderDetailView,
    TicketSelectView,
)
from django_program.registration.views_checkin import (
    LookupView,
    OfflinePreloadView,
    RedeemView,
    ScanView,
)
from django_program.registration.views_terminal import (
    CancelPaymentView,
    CapturePaymentView,
    CartOperationsView,
    ConnectionTokenView,
    CreatePaymentIntentView,
    FetchAttendeeView,
    FetchInventoryView,
    ListReadersView,
)
from django_program.registration.webhooks import stripe_webhook

app_name = "registration"

urlpatterns = [
    path("", TicketSelectView.as_view(), name="ticket-select"),
    path("cart/", CartView.as_view(), name="cart"),
    path("checkout/", CheckoutView.as_view(), name="checkout"),
    path("orders/<str:reference>/", OrderDetailView.as_view(), name="order-detail"),
    path("orders/<str:reference>/confirmation/", OrderConfirmationView.as_view(), name="order-confirmation"),
    path("visa-letter/", LetterRequestCreateView.as_view(), name="letter-request"),
    path("visa-letter/status/", LetterRequestDetailView.as_view(), name="letter-request-detail"),
    path("visa-letter/download/", LetterRequestDownloadView.as_view(), name="letter-request-download"),
    path("webhooks/stripe/", stripe_webhook, name="stripe-webhook"),
    # Check-in API (staff-only, JSON endpoints for scanner UI)
    path("checkin/scan/", ScanView.as_view(), name="checkin-scan"),
    path("checkin/lookup/<str:access_code>/", LookupView.as_view(), name="checkin-lookup"),
    path("checkin/redeem/", RedeemView.as_view(), name="checkin-redeem"),
    path("checkin/preload/", OfflinePreloadView.as_view(), name="checkin-preload"),
    # Stripe Terminal API (staff-only, JSON endpoints for POS UI)
    path("terminal/connection-token/", ConnectionTokenView.as_view(), name="terminal-connection-token"),
    path("terminal/create-payment-intent/", CreatePaymentIntentView.as_view(), name="terminal-create-intent"),
    path("terminal/capture/", CapturePaymentView.as_view(), name="terminal-capture"),
    path("terminal/cancel/", CancelPaymentView.as_view(), name="terminal-cancel"),
    path("terminal/attendee/<str:access_code>/", FetchAttendeeView.as_view(), name="terminal-attendee"),
    path("terminal/inventory/", FetchInventoryView.as_view(), name="terminal-inventory"),
    path("terminal/cart/", CartOperationsView.as_view(), name="terminal-cart"),
    path("terminal/readers/", ListReadersView.as_view(), name="terminal-readers"),
]
