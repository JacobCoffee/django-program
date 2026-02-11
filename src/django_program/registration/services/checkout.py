"""Checkout service for converting carts into orders.

Handles the atomic checkout flow, credit application, and order cancellation.
All methods are stateless and operate on model instances directly.
"""

import json
import secrets
import string
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
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

        Re-validates stock, pricing, and voucher validity at checkout time to
        prevent stale-cart issues. Creates an Order with PENDING status,
        snapshots each CartItem into OrderLineItems, records voucher details,
        and marks the cart as CHECKED_OUT.

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
        now = timezone.now()
        _expire_stale_pending_orders(conference_id=cart.conference_id, now=now)
        cart = Cart.objects.select_for_update().select_related("voucher").get(pk=cart.pk)

        if cart.status != Cart.Status.OPEN:
            raise ValidationError("Only open carts can be checked out.")

        if cart.expires_at and cart.expires_at < now:
            raise ValidationError("Cart has expired.")

        items = list(cart.items.select_for_update().select_related("ticket_type", "addon"))
        if not items:
            raise ValidationError("Cannot check out an empty cart.")

        _revalidate_stock(items)

        summary = CartService.get_summary(cart)

        voucher = cart.voucher
        _validate_voucher_for_checkout(voucher)
        voucher_code = voucher.code if voucher else ""
        voucher_details = _snapshot_voucher(voucher) if voucher else ""
        hold_expires_at = now + timedelta(minutes=get_config().pending_order_expiry_minutes)
        while True:
            reference = _generate_reference()
            try:
                order_kwargs = {
                    "conference": cart.conference,
                    "user": cart.user,
                    "status": Order.Status.PENDING,
                    "subtotal": summary.subtotal,
                    "discount_amount": summary.discount,
                    "total": summary.total,
                    "voucher_code": voucher_code,
                    "voucher_details": voucher_details,
                    "billing_name": billing_name,
                    "billing_email": billing_email,
                    "billing_company": billing_company,
                    "reference": reference,
                }
                if _order_has_hold_expires_at():
                    order_kwargs["hold_expires_at"] = hold_expires_at
                order = Order.objects.create(**order_kwargs)
                break
            except IntegrityError:
                continue

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

        _increment_voucher_usage(voucher=voucher, now=now)

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
        order = Order.objects.select_for_update().get(pk=order.pk)
        credit = Credit.objects.select_for_update().get(pk=credit.pk)

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

        if credit.remaining_amount <= Decimal("0.00"):
            raise ValidationError("Credit has no remaining balance.")

        apply_amount = min(credit.remaining_amount, remaining_balance)

        payment = Payment.objects.create(
            order=order,
            method=Payment.Method.CREDIT,
            status=Payment.Status.SUCCEEDED,
            amount=apply_amount,
        )

        credit.remaining_amount -= apply_amount
        credit.status = Credit.Status.APPLIED if credit.remaining_amount <= Decimal("0.00") else Credit.Status.AVAILABLE
        credit.applied_to_order = order
        credit.save(update_fields=["remaining_amount", "status", "applied_to_order", "updated_at"])

        new_paid = paid_so_far + apply_amount
        if new_paid >= order.total:
            order.status = Order.Status.PAID
            if _order_has_hold_expires_at():
                order.hold_expires_at = None
                order.save(update_fields=["status", "hold_expires_at", "updated_at"])
            else:
                order.save(update_fields=["status", "updated_at"])
            order_paid.send(sender=Order, order=order, user=order.user)

        return payment

    @staticmethod
    @transaction.atomic
    def cancel_order(order: Order) -> Order:
        """Cancel a pending order and release associated resources.

        Reverses any succeeded credit payments (restoring the Credit to
        AVAILABLE), transitions the order to CANCELLED, and decrements the
        voucher usage counter if a voucher was used.

        Args:
            order: The order to cancel.

        Returns:
            The updated Order with CANCELLED status.

        Raises:
            ValidationError: If the order cannot be cancelled (not PENDING).
        """
        order = Order.objects.select_for_update().get(pk=order.pk)

        if order.status != Order.Status.PENDING:
            raise ValidationError(
                f"Only pending orders can be cancelled. This order is '{order.get_status_display()}'."
            )

        _reverse_credit_payments(order)

        order.status = Order.Status.CANCELLED
        if _order_has_hold_expires_at():
            order.hold_expires_at = None
            order.save(update_fields=["status", "hold_expires_at", "updated_at"])
        else:
            order.save(update_fields=["status", "updated_at"])

        if order.voucher_code:
            Voucher.objects.filter(
                conference=order.conference,
                code=order.voucher_code,
                times_used__gt=0,
            ).update(times_used=models.F("times_used") - 1)

        return order


def _reverse_credit_payments(order: Order) -> None:
    """Reverse any succeeded credit payments on a pending order.

    Marks each CREDIT payment as REFUNDED and restores the associated
    Credit back to AVAILABLE so it can be reused on a future order.
    """
    credit_payments = order.payments.filter(
        method=Payment.Method.CREDIT,
        status=Payment.Status.SUCCEEDED,
    )
    for payment in credit_payments:
        payment.status = Payment.Status.REFUNDED
        payment.save(update_fields=["status"])

        credit = Credit.objects.select_for_update().filter(applied_to_order=order).first()
        if credit is None:
            continue
        credit.remaining_amount += payment.amount
        credit.status = Credit.Status.AVAILABLE
        credit.applied_to_order = None
        credit.save(update_fields=["remaining_amount", "status", "applied_to_order", "updated_at"])


def _validate_voucher_for_checkout(voucher: Voucher | None) -> None:
    """Fail checkout if the attached voucher is no longer valid."""
    if voucher is not None and not voucher.is_valid:
        raise ValidationError(f"Voucher code '{voucher.code}' is no longer valid.")


def _increment_voucher_usage(*, voucher: Voucher | None, now: object) -> None:
    """Atomically increment voucher usage, enforcing validity constraints."""
    if voucher is None:
        return

    voucher_updated = (
        Voucher.objects.filter(
            pk=voucher.pk,
            is_active=True,
            times_used__lt=models.F("max_uses"),
        )
        .filter(
            models.Q(valid_from__isnull=True) | models.Q(valid_from__lte=now),
        )
        .filter(
            models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=now),
        )
        .update(times_used=models.F("times_used") + 1)
    )
    if voucher_updated != 1:
        raise ValidationError(f"Voucher code '{voucher.code}' is no longer valid.")


def _revalidate_stock(items: list[object]) -> None:
    """Re-validate stock availability for all cart items at checkout time.

    Raises:
        ValidationError: If any item has insufficient stock.
    """
    now = timezone.now()
    for item in items:
        if item.ticket_type is not None:
            _revalidate_ticket_stock(item)
        elif item.addon is not None:
            _revalidate_addon_stock(item, now)


def _revalidate_ticket_stock(item: object) -> None:
    """Validate a ticket type is still available with sufficient stock."""
    tt = item.ticket_type
    if not tt.is_available:
        raise ValidationError(f"Ticket type '{tt.name}' is no longer available.")
    remaining = tt.remaining_quantity
    if remaining is not None and remaining < item.quantity:
        raise ValidationError(f"Only {remaining} tickets of type '{tt.name}' remaining, but {item.quantity} requested.")


def _revalidate_addon_stock(item: object, now: object) -> None:
    """Validate an add-on is still available within its window and has stock."""
    addon = item.addon
    if not addon.is_active:
        raise ValidationError(f"Add-on '{addon.name}' is no longer active.")
    if addon.available_from and now < addon.available_from:
        raise ValidationError(f"Add-on '{addon.name}' is not yet available.")
    if addon.available_until and now > addon.available_until:
        raise ValidationError(f"Add-on '{addon.name}' is no longer available.")
    if addon.total_quantity > 0:
        sold = (
            OrderLineItem.objects.filter(addon=addon)
            .filter(
                models.Q(order__status__in=[Order.Status.PAID, Order.Status.PARTIALLY_REFUNDED])
                | models.Q(order__status=Order.Status.PENDING, order__hold_expires_at__gt=now)
            )
            .aggregate(total=models.Sum("quantity"))["total"]
            or 0
        )
        remaining = addon.total_quantity - sold
        if remaining < item.quantity:
            raise ValidationError(
                f"Only {remaining} of add-on '{addon.name}' remaining, but {item.quantity} requested."
            )


def _expire_stale_pending_orders(*, conference_id: int, now: object) -> None:
    """Mark stale pending orders as cancelled so holds no longer reserve stock."""
    if not _order_has_hold_expires_at():
        return
    Order.objects.filter(
        conference_id=conference_id,
        status=Order.Status.PENDING,
        hold_expires_at__isnull=False,
        hold_expires_at__lte=now,
    ).update(status=Order.Status.CANCELLED, hold_expires_at=None)


def _order_has_hold_expires_at() -> bool:
    """Return True when the Order model has hold_expires_at in this runtime."""
    return hasattr(Order, "hold_expires_at")
