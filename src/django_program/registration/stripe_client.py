"""Stripe client wrapper for per-conference Stripe API operations.

Each conference has its own Stripe account keys, so the client is initialized
with a Conference instance and uses the modern ``stripe.StripeClient`` pattern
(v1 namespace) for all API calls.
"""

import logging
from typing import TYPE_CHECKING

import stripe
from django.db import IntegrityError, transaction

from django_program.registration.models import StripeCustomer
from django_program.registration.stripe_utils import convert_amount_for_api
from django_program.settings import get_config

if TYPE_CHECKING:
    from decimal import Decimal

    from django.contrib.auth.models import AbstractBaseUser

    from django_program.conference.models import Conference
    from django_program.registration.models import Order

logger = logging.getLogger(__name__)


class StripeClient:
    """Per-conference Stripe API client.

    Wraps ``stripe.StripeClient`` (v1 namespace) and binds every call to the
    conference's secret key and the globally configured API version.

    Args:
        conference: The conference whose Stripe keys will be used.

    Raises:
        ValueError: If the conference has no Stripe secret key configured.
    """

    def __init__(self, conference: Conference) -> None:
        """Initialize the client with per-conference Stripe credentials.

        Args:
            conference: A Conference instance with ``stripe_secret_key`` set.

        Raises:
            ValueError: If the conference has no Stripe secret key.
        """
        raw_key = conference.stripe_secret_key
        if not raw_key:
            msg = (
                f"Conference '{conference.slug}' does not have a Stripe secret key configured. "
                f"Set 'stripe_secret_key' on the Conference record before initializing StripeClient."
            )
            raise ValueError(msg)

        secret_key = str(raw_key)
        self.conference = conference
        config = get_config()
        self.client = stripe.StripeClient(
            secret_key,
            stripe_version=config.stripe.api_version,
        )

        logger.info("Initialized StripeClient for conference '%s'", conference.slug)

    def get_or_create_customer(self, user: AbstractBaseUser) -> StripeCustomer:
        """Return an existing StripeCustomer or create one via the Stripe API.

        Looks up the local ``StripeCustomer`` record for this user and
        conference. If none exists, creates a Stripe customer in the
        conference's Stripe account and persists the mapping locally.

        Args:
            user: The Django user to map to a Stripe customer.

        Returns:
            The ``StripeCustomer`` record linking the user to a Stripe customer ID.
        """
        existing = StripeCustomer.objects.filter(
            user=user,
            conference=self.conference,
        ).first()
        if existing is not None:
            return existing

        get_name = getattr(user, "get_full_name", None)
        full_name = get_name() if callable(get_name) else ""
        customer = self.client.v1.customers.create(
            params={
                "email": getattr(user, "email", ""),
                "name": full_name,
                "metadata": {
                    "user_id": str(user.pk),
                    "conference_slug": self.conference.slug,
                },
            },
        )

        try:
            with transaction.atomic():
                return StripeCustomer.objects.create(
                    user=user,
                    conference=self.conference,
                    stripe_customer_id=customer.id,
                )
        except IntegrityError:
            return StripeCustomer.objects.get(
                user=user,
                conference=self.conference,
            )

    def create_payment_intent(self, order: Order, customer_id: str) -> str:
        """Create a Stripe PaymentIntent for the given order.

        Converts the order total to the smallest currency unit and passes the
        order reference as an idempotency key so retried requests are safe.

        Args:
            order: The order to collect payment for.
            customer_id: The Stripe customer ID to associate with the intent.

        Returns:
            The ``client_secret`` string for the frontend payment flow.
        """
        config = get_config()
        currency = config.currency
        amount = convert_amount_for_api(order.total, currency)

        intent = self.client.v1.payment_intents.create(
            params={
                "amount": amount,
                "currency": currency.lower(),
                "customer": customer_id,
                "metadata": {
                    "order_id": str(order.pk),
                    "conference_id": str(self.conference.pk),
                    "reference": order.reference,
                },
                "description": f"Order {order.reference} for {self.conference.name}",
            },
            options={
                "idempotency_key": order.reference,
            },
        )

        client_secret = intent.client_secret
        if client_secret is None:
            msg = f"Stripe returned no client_secret for order {order.reference}"
            raise ValueError(msg)
        return client_secret

    def capture_payment_intent(self, intent_id: str) -> stripe.PaymentIntent:
        """Capture a previously authorized PaymentIntent.

        Args:
            intent_id: The Stripe PaymentIntent ID to capture.

        Returns:
            The captured ``stripe.PaymentIntent`` object.
        """
        return self.client.v1.payment_intents.capture(intent_id)

    def create_refund(
        self,
        payment_intent_id: str,
        amount: Decimal | None = None,
        reason: str = "requested_by_customer",
    ) -> stripe.Refund:
        """Create a full or partial refund for a PaymentIntent.

        Args:
            payment_intent_id: The Stripe PaymentIntent ID to refund.
            amount: Optional partial refund amount as a ``Decimal``. When
                ``None`` the full PaymentIntent amount is refunded.
            reason: The Stripe refund reason string (e.g.
                ``"requested_by_customer"``, ``"duplicate"``, ``"fraudulent"``).

        Returns:
            The created ``stripe.Refund`` object.
        """
        params: dict[str, object] = {
            "payment_intent": payment_intent_id,
            "reason": reason,
        }

        if amount is not None:
            config = get_config()
            params["amount"] = convert_amount_for_api(amount, config.currency)

        return self.client.v1.refunds.create(params=params)
