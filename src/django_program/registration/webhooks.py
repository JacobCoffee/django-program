"""Stripe webhook handling for the registration app.

Provides a registry-based dispatch system for processing Stripe webhook events.
Each event kind (e.g. ``payment_intent.succeeded``) maps to a handler class that
encapsulates idempotent processing, signal dispatch, and error capture.

The ``stripe_webhook`` view verifies event signatures per-conference, deduplicates
by Stripe event ID, and delegates to the appropriate handler.

Usage in URL configuration::

    from django_program.registration.webhooks import stripe_webhook

    urlpatterns = [
        path("webhooks/stripe/", stripe_webhook),
    ]
"""

import logging
import traceback
from typing import TYPE_CHECKING

import stripe
from django.db import transaction
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from django_program.conference.models import Conference
from django_program.registration.models import (
    EventProcessingException,
    Order,
    Payment,
    StripeEvent,
)
from django_program.registration.signals import order_paid
from django_program.registration.stripe_utils import convert_amount_for_db
from django_program.settings import get_config

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class WebhookRegistry:
    """Singleton registry mapping Stripe event kinds to handler classes.

    Handlers are registered at module load time and looked up by the webhook
    view when an event arrives.
    """

    def __init__(self) -> None:
        """Initialize an empty handler registry."""
        self._registry: dict[str, type[Webhook]] = {}

    def register(self, kind: str, handler_class: type[Webhook]) -> None:
        """Register a handler class for a Stripe event kind.

        Args:
            kind: The Stripe event type string (e.g. ``"payment_intent.succeeded"``).
            handler_class: A ``Webhook`` subclass that handles this event kind.
        """
        self._registry[kind] = handler_class

    def get(self, kind: str) -> type[Webhook] | None:
        """Return the handler class for a given event kind, or ``None``.

        Args:
            kind: The Stripe event type string.

        Returns:
            The registered handler class, or ``None`` if no handler exists.
        """
        return self._registry.get(kind)

    def keys(self) -> list[str]:
        """Return all registered event kinds.

        Returns:
            A list of Stripe event type strings that have registered handlers.
        """
        return list(self._registry.keys())


registry = WebhookRegistry()


# ---------------------------------------------------------------------------
# Base handler
# ---------------------------------------------------------------------------


class Webhook:
    """Abstract base class for Stripe webhook event handlers.

    Subclasses must set ``name`` to the Stripe event kind they handle and
    implement ``process_webhook()`` with the actual business logic. The base
    ``process()`` method wraps execution in idempotency checks and exception
    capture.

    Attributes:
        name: The Stripe event kind this handler processes.
        event: The ``StripeEvent`` model instance being handled.
    """

    name: str = ""

    def __init__(self, event: StripeEvent) -> None:
        """Bind the handler to a specific Stripe event record.

        Args:
            event: The persisted ``StripeEvent`` to process.
        """
        self.event = event

    def process(self) -> None:
        """Run the handler with idempotency and error capture.

        Skips events that have already been processed. On success, marks the
        event as processed and fires any associated Django signal. On failure,
        captures the traceback to ``EventProcessingException`` and re-raises.
        """
        if self.event.processed:
            logger.info("Event %s already processed, skipping", self.event.stripe_id)
            return

        try:
            self.process_webhook()
            self.send_signal()
            self.event.processed = True
            self.event.save(update_fields=["processed"])
        except Exception:
            self.log_exception()
            raise

    def process_webhook(self) -> None:
        """Implement event-specific processing logic.

        Raises:
            NotImplementedError: Subclasses must override this method.
        """
        raise NotImplementedError

    def send_signal(self) -> None:
        """Send a Django signal after successful processing.

        The default implementation is a no-op. Subclasses that need to fire
        signals should override this method.
        """

    def log_exception(self) -> None:
        """Capture the current exception to ``EventProcessingException``."""
        tb = traceback.format_exc()
        logger.error(
            "Error processing webhook %s (event %s): %s",
            self.name,
            self.event.stripe_id,
            tb,
        )
        EventProcessingException.objects.create(
            event=self.event,
            data=str(self.event.payload),
            message=str(tb)[:500],
            traceback=tb,
        )


def _event_data_object(event: StripeEvent) -> dict[str, object]:
    """Extract the ``data.object`` dict from a StripeEvent payload.

    Performs runtime type narrowing so ``ty`` can verify subscript access
    on the JSONField value.
    """
    payload = event.payload
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            obj = data.get("object")
            if isinstance(obj, dict):
                return obj
    return {}


# ---------------------------------------------------------------------------
# Concrete handlers
# ---------------------------------------------------------------------------


class PaymentIntentSucceededWebhook(Webhook):
    """Handles ``payment_intent.succeeded`` events.

    Creates a Payment record, transitions the Order from PENDING to PAID,
    clears the inventory hold, and fires the ``order_paid`` signal.
    """

    name = "payment_intent.succeeded"

    @transaction.atomic
    def process_webhook(self) -> None:
        """Create a payment and mark the order as paid."""
        intent = _event_data_object(self.event)
        metadata = intent.get("metadata", {})
        order_id = metadata["order_id"] if isinstance(metadata, dict) else str(metadata)
        order = Order.objects.select_for_update().get(pk=order_id)

        config = get_config()
        amount = convert_amount_for_db(int(intent["amount"]), config.currency)

        intent_id = str(intent.get("id", ""))
        payment = Payment.objects.filter(
            order=order,
            stripe_payment_intent_id=intent_id,
            status=Payment.Status.PENDING,
        ).first()

        latest_charge = intent.get("latest_charge")

        if payment is not None:
            payment.status = Payment.Status.SUCCEEDED
            payment.amount = amount
            update = ["status", "amount"]
            if latest_charge:
                payment.stripe_charge_id = str(latest_charge)
                update.append("stripe_charge_id")
            payment.save(update_fields=update)
        else:
            payment_kwargs: dict[str, object] = {
                "order": order,
                "method": Payment.Method.STRIPE,
                "status": Payment.Status.SUCCEEDED,
                "stripe_payment_intent_id": intent_id,
                "amount": amount,
            }
            if latest_charge:
                payment_kwargs["stripe_charge_id"] = str(latest_charge)
            Payment.objects.create(**payment_kwargs)

        order.status = Order.Status.PAID
        update_fields = ["status", "updated_at"]
        if hasattr(order, "hold_expires_at"):
            order.hold_expires_at = None
            update_fields.append("hold_expires_at")
        order.save(update_fields=update_fields)

        logger.info(
            "Order %s marked PAID via payment_intent %s",
            order.reference,
            intent.get("id"),
        )

    def send_signal(self) -> None:
        """Fire the ``order_paid`` signal for downstream listeners."""
        intent = _event_data_object(self.event)
        metadata = intent.get("metadata", {})
        order_id = metadata["order_id"] if isinstance(metadata, dict) else str(metadata)
        order = Order.objects.get(pk=order_id)
        order_paid.send(sender=Order, order=order, user=order.user)


class PaymentIntentPaymentFailedWebhook(Webhook):
    """Handles ``payment_intent.payment_failed`` events.

    Locates the PENDING payment record for the failed intent and updates its
    status to FAILED with the error reason from Stripe.
    """

    name = "payment_intent.payment_failed"

    @transaction.atomic
    def process_webhook(self) -> None:
        """Mark the matching payment as failed and log the reason."""
        intent = _event_data_object(self.event)
        metadata = intent.get("metadata", {})
        order_id = metadata["order_id"] if isinstance(metadata, dict) else str(metadata)
        intent_id = str(intent.get("id", ""))

        payment = (
            Payment.objects.select_for_update()
            .filter(
                order_id=order_id,
                stripe_payment_intent_id=intent_id,
                status__in=[Payment.Status.PENDING, Payment.Status.PROCESSING],
            )
            .first()
        )

        if payment is None:
            logger.warning(
                "No pending payment found for intent %s on order %s",
                intent_id,
                order_id,
            )
            return

        payment.status = Payment.Status.FAILED
        payment.save(update_fields=["status"])

        error = intent.get("last_payment_error")
        reason = "No error details"
        if isinstance(error, dict):
            msg = error.get("message")
            reason = str(msg) if isinstance(msg, str) else "Unknown error"
        logger.warning(
            "Payment failed for intent %s (order %s): %s",
            intent_id,
            order_id,
            reason,
        )


class ChargeRefundedWebhook(Webhook):
    """Handles ``charge.refunded`` events.

    Determines whether the refund is full or partial by comparing
    ``amount_refunded`` to ``amount``, then updates Payment and Order statuses
    accordingly.
    """

    name = "charge.refunded"

    @transaction.atomic
    def process_webhook(self) -> None:
        """Update payment and order status based on refund amount."""
        charge = _event_data_object(self.event)
        intent_id = str(charge.get("payment_intent", ""))

        payment = Payment.objects.select_for_update().filter(stripe_payment_intent_id=intent_id).first()
        if payment is None:
            logger.warning(
                "No payment found for payment_intent %s during refund processing",
                intent_id,
            )
            return

        config = get_config()
        amount_refunded = convert_amount_for_db(int(charge["amount_refunded"]), config.currency)
        amount_total = convert_amount_for_db(int(charge["amount"]), config.currency)
        is_full_refund = amount_refunded >= amount_total

        order = Order.objects.select_for_update().get(pk=payment.order_id)

        if is_full_refund:
            payment.status = Payment.Status.REFUNDED
            payment.save(update_fields=["status"])
            order.status = Order.Status.REFUNDED
        else:
            order.status = Order.Status.PARTIALLY_REFUNDED

        order.save(update_fields=["status", "updated_at"])

        logger.info(
            "%s refund processed for payment_intent %s (order %s)",
            "Full" if is_full_refund else "Partial",
            intent_id,
            order.reference,
        )


class ChargeDisputeCreatedWebhook(Webhook):
    """Handles ``charge.dispute.created`` events.

    Logs the dispute for manual review. No automated actions are taken; the
    event is simply recorded and marked as processed.
    """

    name = "charge.dispute.created"

    def process_webhook(self) -> None:
        """Log the dispute details."""
        dispute = _event_data_object(self.event)
        logger.warning(
            "Stripe dispute created: id=%s, charge=%s, amount=%s, reason=%s",
            dispute.get("id"),
            dispute.get("charge"),
            dispute.get("amount"),
            dispute.get("reason"),
        )


# ---------------------------------------------------------------------------
# Handler registration
# ---------------------------------------------------------------------------

registry.register("payment_intent.succeeded", PaymentIntentSucceededWebhook)
registry.register("payment_intent.payment_failed", PaymentIntentPaymentFailedWebhook)
registry.register("charge.refunded", ChargeRefundedWebhook)
registry.register("charge.dispute.created", ChargeDisputeCreatedWebhook)


# ---------------------------------------------------------------------------
# Webhook endpoint view
# ---------------------------------------------------------------------------


@csrf_exempt
@require_POST
def stripe_webhook(request: HttpRequest, conference_slug: str) -> HttpResponse:
    """Receive and process Stripe webhook events for a specific conference.

    Verifies the event signature against the conference's webhook secret,
    deduplicates by Stripe event ID, persists the raw event, and dispatches
    to the registered handler.

    Always returns HTTP 200 to acknowledge receipt, even when processing
    fails. Errors are logged and captured to ``EventProcessingException``.

    Args:
        request: The incoming HTTP request from Stripe.
        conference_slug: URL slug identifying which conference this webhook
            is for.

    Returns:
        An ``HttpResponse`` with status 200.
    """
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

    try:
        conference = Conference.objects.get(slug=conference_slug, is_active=True)
    except Conference.DoesNotExist:
        logger.warning("Webhook received for unknown conference slug: %s", conference_slug)
        return HttpResponse(status=200)

    webhook_secret = conference.stripe_webhook_secret
    if not webhook_secret:
        logger.error("Conference '%s' has no webhook secret configured", conference_slug)
        return HttpResponse(status=200)

    config = get_config()
    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            str(webhook_secret),
            tolerance=config.stripe.webhook_tolerance,
        )
    except stripe.SignatureVerificationError, ValueError:
        logger.warning("Invalid Stripe webhook payload or signature for conference '%s'", conference_slug)
        return HttpResponse(status=200)

    stripe_id = event["id"]
    kind = event["type"]

    if StripeEvent.objects.filter(stripe_id=stripe_id).exists():
        logger.info("Duplicate Stripe event %s, returning 200", stripe_id)
        return HttpResponse(status=200)

    customer_id = ""
    data_object = event.get("data", {}).get("object", {})
    if isinstance(data_object, dict):
        customer_id = data_object.get("customer", "") or ""

    stripe_event = StripeEvent.objects.create(
        stripe_id=stripe_id,
        kind=kind,
        livemode=event.get("livemode", False),
        payload=dict(event),
        customer_id=str(customer_id),
        api_version=event.get("api_version", ""),
    )

    handler_class = registry.get(kind)
    if handler_class is None:
        logger.info("No handler registered for event kind '%s'", kind)
        return HttpResponse(status=200)

    try:
        handler = handler_class(stripe_event)
        handler.process()
    except Exception:
        logger.exception(
            "Error processing Stripe event %s (kind=%s)",
            stripe_id,
            kind,
        )

    return HttpResponse(status=200)
