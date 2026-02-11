"""Payment service for processing order payments.

Handles Stripe payment initiation, complimentary order fulfillment,
and manual staff-entered payments. All methods are stateless and
operate on model instances directly.
"""

import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import models, transaction

from django_program.registration.models import Order, Payment
from django_program.registration.signals import order_paid
from django_program.registration.stripe_client import StripeClient

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser

logger = logging.getLogger(__name__)


def _order_has_hold_expires_at() -> bool:
    """Return True when the Order model has hold_expires_at in this runtime."""
    return hasattr(Order, "hold_expires_at")


def _extract_payment_intent_id(client_secret: str) -> str:
    """Extract the PaymentIntent ID from a Stripe client_secret string.

    The client_secret format is ``pi_xxx_secret_yyy``, so the intent ID
    is everything before the ``_secret_`` delimiter.

    Args:
        client_secret: The full client_secret returned by Stripe.

    Returns:
        The PaymentIntent ID (e.g. ``pi_xxx``).

    Raises:
        ValueError: If the client_secret does not contain ``_secret_``.
    """
    delimiter = "_secret_"
    idx = client_secret.find(delimiter)
    if idx == -1:
        msg = f"Unexpected client_secret format: missing '{delimiter}' delimiter"
        raise ValueError(msg)
    return client_secret[:idx]


def _mark_order_paid(order: Order) -> None:
    """Transition an order to PAID, clear hold, and fire the signal.

    Args:
        order: The order to mark as paid (must already be locked for update).
    """
    order.status = Order.Status.PAID
    update_fields = ["status", "updated_at"]
    if _order_has_hold_expires_at():
        order.hold_expires_at = None
        update_fields.append("hold_expires_at")
    order.save(update_fields=update_fields)
    order_paid.send(sender=Order, order=order, user=order.user)


class PaymentService:
    """Stateless service for payment operations.

    Orchestrates Stripe payment flows, complimentary order fulfillment,
    and manual staff payments against registration orders.
    """

    @staticmethod
    @transaction.atomic
    def initiate_payment(order: Order) -> str:
        """Initiate a Stripe payment flow for the given order.

        Creates a Stripe customer (if needed), a PaymentIntent, and a
        pending Payment record. Returns the client_secret for the
        frontend to confirm via Stripe.js.

        Args:
            order: The order to collect payment for.

        Returns:
            The Stripe client_secret string for frontend confirmation.

        Raises:
            ValidationError: If the order is not in PENDING status.
            ValueError: If the conference has no Stripe key configured,
                or if the client_secret format is unexpected.
        """
        if order.status != Order.Status.PENDING:
            raise ValidationError("Payment can only be initiated for pending orders.")

        stripe_client = StripeClient(order.conference)
        customer = stripe_client.get_or_create_customer(order.user)
        client_secret = stripe_client.create_payment_intent(order, customer.stripe_customer_id)
        payment_intent_id = _extract_payment_intent_id(client_secret)

        Payment.objects.create(
            order=order,
            method=Payment.Method.STRIPE,
            status=Payment.Status.PENDING,
            amount=order.total,
            stripe_payment_intent_id=payment_intent_id,
        )

        logger.info(
            "Initiated Stripe payment for order %s (intent %s)",
            order.reference,
            payment_intent_id,
        )
        return client_secret

    @staticmethod
    @transaction.atomic
    def record_comp(order: Order) -> Payment:
        """Record a complimentary payment for a zero-total order.

        Used for speaker comps, 100% voucher discounts, or any other
        scenario where the order total is zero.

        Args:
            order: The order to fulfill as complimentary.

        Returns:
            The created Payment record with SUCCEEDED status.

        Raises:
            ValidationError: If the order is not PENDING or has a
                non-zero total.
        """
        if order.status != Order.Status.PENDING:
            raise ValidationError("Comp payments can only be recorded for pending orders.")

        if order.total > Decimal("0.00"):
            raise ValidationError("Comp payments are only valid for orders with a zero total.")

        payment = Payment.objects.create(
            order=order,
            method=Payment.Method.COMP,
            status=Payment.Status.SUCCEEDED,
            amount=Decimal("0.00"),
        )

        _mark_order_paid(order)

        logger.info("Recorded comp payment for order %s", order.reference)
        return payment

    @staticmethod
    @transaction.atomic
    def record_manual(
        order: Order,
        *,
        amount: Decimal,
        reference: str = "",
        note: str = "",
        staff_user: AbstractBaseUser | None = None,
    ) -> Payment:
        """Record a manual payment entered by staff.

        Used for at-the-door cash payments, wire transfers, or other
        off-platform payment methods. If the cumulative succeeded
        payments meet or exceed the order total, the order is
        transitioned to PAID.

        Args:
            order: The order to record payment against.
            amount: The payment amount (must be positive).
            reference: An optional external reference (e.g. receipt number).
            note: An optional staff note about the payment.
            staff_user: The staff member recording the payment.

        Returns:
            The created Payment record with SUCCEEDED status.

        Raises:
            ValidationError: If the order is not PENDING or the amount
                is not positive.
        """
        if order.status != Order.Status.PENDING:
            raise ValidationError("Manual payments can only be recorded for pending orders.")

        if amount <= Decimal("0.00"):
            raise ValidationError("Payment amount must be greater than zero.")

        payment = Payment.objects.create(
            order=order,
            method=Payment.Method.MANUAL,
            status=Payment.Status.SUCCEEDED,
            amount=amount,
            reference=reference,
            note=note,
            created_by=staff_user,
        )

        paid_total = order.payments.filter(status=Payment.Status.SUCCEEDED).aggregate(total=models.Sum("amount"))[
            "total"
        ] or Decimal("0.00")

        if paid_total >= order.total:
            _mark_order_paid(order)

        logger.info(
            "Recorded manual payment of %s for order %s (paid %s / %s)",
            amount,
            order.reference,
            paid_total,
            order.total,
        )
        return payment
