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
    OrderConfirmationView,
    OrderDetailView,
    TicketSelectView,
)
from django_program.registration.webhooks import stripe_webhook

app_name = "registration"

urlpatterns = [
    path("", TicketSelectView.as_view(), name="ticket-select"),
    path("cart/", CartView.as_view(), name="cart"),
    path("checkout/", CheckoutView.as_view(), name="checkout"),
    path("orders/<str:reference>/", OrderDetailView.as_view(), name="order-detail"),
    path("orders/<str:reference>/confirmation/", OrderConfirmationView.as_view(), name="order-confirmation"),
    path("webhooks/stripe/<slug:conference_slug>/", stripe_webhook, name="stripe-webhook"),
]
