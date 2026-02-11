"""Refund service for processing order refunds and credit applications.

Handles Stripe refund creation, store credit issuance, and credit-as-payment
application. All methods are stateless and operate on model instances directly.
"""

import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import models, transaction

from django_program.registration.models import Credit, Order, Payment
from django_program.registration.signals import order_paid
from django_program.registration.stripe_client import StripeClient

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser

logger = logging.getLogger(__name__)


class RefundService:
    """Stateless service for refund and credit operations.

    Processes full and partial Stripe refunds, issues store credits,
    and applies existing credits as payment toward new orders.
    """

    @staticmethod
    @transaction.atomic
    def create_refund(
        order: Order,
        *,
        amount: Decimal,
        reason: str = "requested_by_customer",
        staff_user: AbstractBaseUser | None = None,
    ) -> Credit:
        """Issue a full or partial refund for a Stripe-paid order.

        Validates the order state, calculates the refundable balance, calls the
        Stripe API to create the refund, and issues a store Credit record. The
        order status is updated to REFUNDED or PARTIALLY_REFUNDED depending on
        whether the cumulative refund total covers the full order amount.

        Args:
            order: The order to refund. Must be PAID or PARTIALLY_REFUNDED.
            amount: The refund amount. Must be positive and not exceed the
                remaining refundable balance.
            reason: The Stripe refund reason string (e.g.
                ``"requested_by_customer"``, ``"duplicate"``, ``"fraudulent"``).
            staff_user: Optional staff user initiating the refund, recorded on
                the credit note for audit purposes.

        Returns:
            The newly created Credit with AVAILABLE status.

        Raises:
            ValidationError: If the order is not in a refundable state, the
                amount is invalid, or no Stripe payment exists on the order.
        """
        order = Order.objects.select_for_update().get(pk=order.pk)

        refundable_statuses = {Order.Status.PAID, Order.Status.PARTIALLY_REFUNDED}
        if order.status not in refundable_statuses:
            raise ValidationError(
                f"Only paid or partially refunded orders can be refunded. This order is '{order.get_status_display()}'."
            )

        if amount <= Decimal("0.00"):
            raise ValidationError("Refund amount must be greater than zero.")

        payment = order.payments.filter(
            method=Payment.Method.STRIPE,
            status=Payment.Status.SUCCEEDED,
        ).first()
        if payment is None:
            raise ValidationError("No succeeded Stripe payment found on this order.")

        total_paid = order.payments.filter(
            method=Payment.Method.STRIPE,
            status=Payment.Status.SUCCEEDED,
        ).aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")
        total_refunded = order.issued_credits.aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")
        refundable = total_paid - total_refunded

        if amount > refundable:
            raise ValidationError(f"Refund amount {amount} exceeds the refundable balance of {refundable}.")

        StripeClient(order.conference).create_refund(
            payment.stripe_payment_intent_id,
            amount,
            reason,
        )

        staff_label = f" by {staff_user}" if staff_user is not None else ""
        credit = Credit.objects.create(
            user=order.user,
            conference=order.conference,
            amount=amount,
            status=Credit.Status.AVAILABLE,
            source_order=order,
            note=f"Refund for order {order.reference}: {reason}{staff_label}",
        )

        new_total_refunded = total_refunded + amount
        if new_total_refunded >= order.total:
            order.status = Order.Status.REFUNDED
        else:
            order.status = Order.Status.PARTIALLY_REFUNDED
        order.save(update_fields=["status", "updated_at"])

        logger.info(
            "Refund of %s created for order %s (new status: %s)",
            amount,
            order.reference,
            order.status,
        )

        return credit

    @staticmethod
    @transaction.atomic
    def apply_credit_as_refund(credit: Credit, target_order: Order) -> Payment:
        """Apply an existing store credit as payment toward an order.

        Deducts the applied amount from the credit's remaining balance and
        creates a CREDIT payment on the target order. If the credit is fully
        consumed it transitions to APPLIED. If the order becomes fully paid
        it transitions to PAID and the ``order_paid`` signal fires.

        Args:
            credit: The available store credit to apply.
            target_order: The pending order to apply the credit toward.

        Returns:
            The created Payment record with CREDIT method and SUCCEEDED status.

        Raises:
            ValidationError: If the credit is not available, has no remaining
                balance, the order is not pending, or the credit and order
                belong to different users or conferences.
        """
        credit = Credit.objects.select_for_update().get(pk=credit.pk)
        target_order = Order.objects.select_for_update().get(pk=target_order.pk)

        if credit.status != Credit.Status.AVAILABLE:
            raise ValidationError("Only available credits can be applied.")

        if credit.remaining_amount <= Decimal("0.00"):
            raise ValidationError("Credit has no remaining balance.")

        if target_order.status != Order.Status.PENDING:
            raise ValidationError(
                f"Credits can only be applied to pending orders. This order is '{target_order.get_status_display()}'."
            )

        if credit.user_id != target_order.user_id:
            raise ValidationError("Credit does not belong to the same user as the order.")

        if credit.conference_id != target_order.conference_id:
            raise ValidationError("Credit does not belong to the same conference as the order.")

        existing_paid = target_order.payments.filter(
            status=Payment.Status.SUCCEEDED,
        ).aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")
        remaining_balance = target_order.total - existing_paid

        if remaining_balance <= Decimal("0.00"):
            raise ValidationError("Order is already fully paid.")

        apply_amount = min(credit.remaining_amount, remaining_balance)

        payment = Payment.objects.create(
            order=target_order,
            method=Payment.Method.CREDIT,
            status=Payment.Status.SUCCEEDED,
            amount=apply_amount,
        )

        credit.remaining_amount -= apply_amount
        if credit.remaining_amount <= Decimal("0.00"):
            credit.status = Credit.Status.APPLIED
        credit.applied_to_order = target_order
        credit.save(update_fields=["remaining_amount", "status", "applied_to_order", "updated_at"])

        new_paid = existing_paid + apply_amount
        if new_paid >= target_order.total:
            target_order.status = Order.Status.PAID
            target_order.hold_expires_at = None
            target_order.save(update_fields=["status", "hold_expires_at", "updated_at"])
            order_paid.send(sender=Order, order=target_order, user=target_order.user)

        logger.info(
            "Applied credit %s (%s) to order %s",
            credit.pk,
            apply_amount,
            target_order.reference,
        )

        return payment
