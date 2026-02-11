"""URL configuration for the registration app.

Includes webhook endpoints, cart operations, checkout, and payment initiation.
Mount these under a conference-scoped prefix in the host project::

    urlpatterns = [
        path(
            "<slug:conference_slug>/registration/",
            include("django_program.registration.urls"),
        ),
    ]
"""

from django.urls import path

from django_program.registration.webhooks import stripe_webhook

app_name = "registration"

urlpatterns = [
    path("webhooks/stripe/<slug:conference_slug>/", stripe_webhook, name="stripe-webhook"),
]
