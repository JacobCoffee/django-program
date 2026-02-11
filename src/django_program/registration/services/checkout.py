"""Checkout service for converting carts into orders.

Handles the atomic checkout flow, credit application, and order cancellation.
All methods are stateless and operate on model instances directly.
"""

import json
import secrets
import string
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from django_program.registration.models import (
    Cart,
    Credit,
    Order,
    OrderLineItem,
    Payment,
    Voucher,
)
from django_program.registration.services.cart import CartService
from django_program.registration.signals import order_paid
from django_program.settings import get_config


def _generate_reference() -> str:
    """Generate a unique order reference using the configured prefix.

    The prefix is set via ``DJANGO_PROGRAM["order_reference_prefix"]``
    (default ``"ORD"``), producing references like ``PYCON-A1B2C3D4``.
    """
    config = get_config()
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(chars) for _ in range(8))
    return f"{config.order_reference_prefix}-{suffix}"


def _snapshot_voucher(voucher: Voucher) -> str:
    """Serialize voucher state at checkout time as JSON."""
    return json.dumps(
        {
            "code": voucher.code,
            "voucher_type": voucher.voucher_type,
            "discount_value": str(voucher.discount_value),
            "unlocks_hidden_tickets": voucher.unlocks_hidden_tickets,
        }
    )


class CheckoutService:
    """Stateless service for checkout operations.

    Converts carts into orders, applies credits, and handles cancellations.
    """

    @staticmethod
    @transaction.atomic
    def checkout(
        cart: Cart,
        *,
        billing_name: str = "",
        billing_email: str = "",
        billing_company: str = "",
    ) -> Order:
        """Convert a cart into an order atomically.

        Re-validates stock and prices at checkout time to prevent stale-cart
        issues. Creates an Order with PENDING status, snapshots each CartItem
        into OrderLineItems, records voucher details, and marks the cart as
        CHECKED_OUT.

        Args:
            cart: The open cart to check out.
            billing_name: Customer billing name.
            billing_email: Customer billing email.
            billing_company: Customer billing company.

        Returns:
            The newly created Order with PENDING status.

        Raises:
            ValidationError: If the cart is empty, expired, not open, or if
                stock/price validation fails at checkout time.
        """
        if cart.status != Cart.Status.OPEN:
            raise ValidationError("Only open carts can be checked out.")

        if cart.expires_at and cart.expires_at < timezone.now():
            raise ValidationError("Cart has expired.")

        items = list(cart.items.select_related("ticket_type", "addon"))
        if not items:
            raise ValidationError("Cannot check out an empty cart.")

        _revalidate_stock(items)

        summary = CartService.get_summary(cart)

        reference = _generate_reference()
        while Order.objects.filter(reference=reference).exists():
            reference = _generate_reference()

        voucher = cart.voucher
        voucher_code = voucher.code if voucher else ""
        voucher_details = _snapshot_voucher(voucher) if voucher else ""

        order = Order.objects.create(
            conference=cart.conference,
            user=cart.user,
            status=Order.Status.PENDING,
            subtotal=summary.subtotal,
            discount_amount=summary.discount,
            total=summary.total,
            voucher_code=voucher_code,
            voucher_details=voucher_details,
            billing_name=billing_name,
            billing_email=billing_email,
            billing_company=billing_company,
            reference=reference,
        )

        for line in summary.items:
            cart_item = next(i for i in items if i.pk == line.item_id)
            OrderLineItem.objects.create(
                order=order,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                discount_amount=line.discount,
                line_total=line.line_total,
                ticket_type=cart_item.ticket_type,
                addon=cart_item.addon,
            )

        cart.status = Cart.Status.CHECKED_OUT
        cart.save(update_fields=["status", "updated_at"])

        if voucher:
            Voucher.objects.filter(pk=voucher.pk).update(
                times_used=models.F("times_used") + 1,
            )

        return order

    @staticmethod
    @transaction.atomic
    def apply_credit(order: Order, credit: Credit) -> Payment:
        """Apply a store credit to an order.

        Creates a CREDIT payment record and marks the credit as APPLIED.
        If the credit covers the full remaining balance, transitions the
        order to PAID and fires the ``order_paid`` signal.

        Args:
            order: The order to apply the credit to.
            credit: The available credit to apply.

        Returns:
            The created Payment record.

        Raises:
            ValidationError: If the order is not PENDING, the credit is not
                AVAILABLE, or the credit belongs to a different conference/user.
        """
        if order.status != Order.Status.PENDING:
            raise ValidationError("Credits can only be applied to pending orders.")

        if credit.status != Credit.Status.AVAILABLE:
            raise ValidationError("Only available credits can be applied.")

        if credit.user_id != order.user_id:
            raise ValidationError("Credit does not belong to this user.")

        if credit.conference_id != order.conference_id:
            raise ValidationError("Credit does not belong to this conference.")

        existing_payments = order.payments.filter(status=Payment.Status.SUCCEEDED).aggregate(total=models.Sum("amount"))
        paid_so_far = existing_payments["total"] or Decimal("0.00")
        remaining_balance = order.total - paid_so_far

        if remaining_balance <= Decimal("0.00"):
            raise ValidationError("Order is already fully paid.")

        apply_amount = min(credit.amount, remaining_balance)

        payment = Payment.objects.create(
            order=order,
            method=Payment.Method.CREDIT,
            status=Payment.Status.SUCCEEDED,
            amount=apply_amount,
        )

        credit.status = Credit.Status.APPLIED
        credit.applied_to_order = order
        credit.save(update_fields=["status", "applied_to_order", "updated_at"])

        new_paid = paid_so_far + apply_amount
        if new_paid >= order.total:
            order.status = Order.Status.PAID
            order.save(update_fields=["status", "updated_at"])
            order_paid.send(sender=Order, order=order, user=order.user)

        return payment

    @staticmethod
    @transaction.atomic
    def cancel_order(order: Order) -> Order:
        """Cancel a pending order and release associated resources.

        Transitions the order to CANCELLED, decrements the voucher usage
        counter if a voucher was used, and releases inventory back to the pool.

        Args:
            order: The order to cancel.

        Returns:
            The updated Order with CANCELLED status.

        Raises:
            ValidationError: If the order cannot be cancelled (not PENDING).
        """
        if order.status != Order.Status.PENDING:
            raise ValidationError(
                f"Only pending orders can be cancelled. This order is '{order.get_status_display()}'."
            )

        order.status = Order.Status.CANCELLED
        order.save(update_fields=["status", "updated_at"])

        if order.voucher_code:
            Voucher.objects.filter(
                conference=order.conference,
                code=order.voucher_code,
                times_used__gt=0,
            ).update(times_used=models.F("times_used") - 1)

        return order


def _revalidate_stock(items: list[object]) -> None:
    """Re-validate stock availability for all cart items at checkout time.

    Raises:
        ValidationError: If any item has insufficient stock.
    """
    for item in items:
        if item.ticket_type is not None:
            tt = item.ticket_type
            if not tt.is_available:
                raise ValidationError(f"Ticket type '{tt.name}' is no longer available.")
            remaining = tt.remaining_quantity
            if remaining is not None and remaining < item.quantity:
                raise ValidationError(
                    f"Only {remaining} tickets of type '{tt.name}' remaining, but {item.quantity} requested."
                )

        elif item.addon is not None:
            addon = item.addon
            if not addon.is_active:
                raise ValidationError(f"Add-on '{addon.name}' is no longer active.")
            if addon.total_quantity > 0:
                sold = (
                    OrderLineItem.objects.filter(
                        addon=addon,
                        order__status__in=[
                            Order.Status.PAID,
                            Order.Status.PARTIALLY_REFUNDED,
                        ],
                    ).aggregate(total=models.Sum("quantity"))["total"]
                    or 0
                )
                remaining = addon.total_quantity - sold
                if remaining < item.quantity:
                    raise ValidationError(
                        f"Only {remaining} of add-on '{addon.name}' remaining, but {item.quantity} requested."
                    )
