"""Bulk purchase service for sponsor voucher checkout flows.

Orchestrates the lifecycle of a sponsor's bulk voucher purchase: creating the
purchase record, initiating a Stripe Checkout Session, fulfilling the order
with generated voucher codes after payment, and handling the webhook callback.
"""

import datetime
import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import transaction

from django_program.registration.models import AddOn, TicketType, Voucher
from django_program.registration.services.voucher_service import (
    VoucherBulkConfig,
    generate_voucher_codes,
)
from django_program.registration.stripe_client import StripeClient
from django_program.registration.stripe_utils import convert_amount_for_api
from django_program.settings import get_config
from django_program.sponsors.models import BulkPurchase, BulkPurchaseVoucher

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser

    from django_program.sponsors.models import Sponsor

logger = logging.getLogger(__name__)


def _parse_datetime(value: object) -> datetime.datetime | None:
    """Coerce a JSON-serialized datetime value to a ``datetime`` object.

    Handles ``None``, ISO-format strings, and already-parsed ``datetime``
    instances (which Django's JSONField may produce depending on the backend).

    Args:
        value: The raw value from the voucher_config JSONField.

    Returns:
        A ``datetime`` instance, or ``None`` if the value is empty.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, str):
        return datetime.datetime.fromisoformat(value)
    return None


class BulkPurchaseError(Exception):
    """Raised when a bulk purchase operation fails."""


class BulkPurchaseService:
    """Stateless service for sponsor bulk voucher purchase operations.

    Manages the full purchase lifecycle from creation through Stripe Checkout
    to voucher code generation upon successful payment.
    """

    @staticmethod
    @transaction.atomic
    def create_bulk_purchase(  # noqa: PLR0913
        sponsor: Sponsor,
        quantity: int,
        ticket_type: TicketType | None,
        unit_price: Decimal,
        requested_by: AbstractBaseUser | None = None,
        voucher_config: dict[str, object] | None = None,
        addon: AddOn | None = None,
    ) -> BulkPurchase:
        """Create a new bulk purchase record in PENDING state.

        Args:
            sponsor: The sponsor placing the order.
            quantity: Number of voucher codes to generate on fulfillment.
            ticket_type: Optional ticket type the vouchers will be tied to.
            unit_price: Per-voucher price.
            requested_by: The user initiating the purchase.
            voucher_config: Dict of voucher generation parameters (voucher_type,
                discount_value, max_uses, valid_from, valid_until, etc.).
            addon: Optional add-on the vouchers will be tied to.

        Returns:
            The newly created ``BulkPurchase`` in PENDING status.

        Raises:
            BulkPurchaseError: If quantity is less than 1 or unit_price is negative.
        """
        if quantity < 1:
            msg = "Quantity must be at least 1."
            raise BulkPurchaseError(msg)

        if unit_price < Decimal("0.00"):
            msg = "Unit price cannot be negative."
            raise BulkPurchaseError(msg)

        total_amount = unit_price * quantity
        product_description = ""
        if ticket_type is not None:
            product_description = f"{quantity}x {ticket_type.name} voucher codes"

        bp = BulkPurchase(
            conference=sponsor.conference,
            sponsor=sponsor,
            quantity=quantity,
            ticket_type=ticket_type,
            addon=addon,
            unit_price=unit_price,
            total_amount=total_amount,
            product_description=product_description,
            payment_status=BulkPurchase.PaymentStatus.PENDING,
            requested_by=requested_by,
            voucher_config=voucher_config or {},
        )
        bp.full_clean()
        bp.save()
        return bp

    @staticmethod
    def create_checkout_session(
        bulk_purchase: BulkPurchase,
        success_url: str,
        cancel_url: str,
    ) -> str:
        """Create a Stripe Checkout Session for the bulk purchase total.

        Uses the conference's Stripe credentials to create a Checkout Session
        in ``payment`` mode. Stores the session ID on the ``BulkPurchase``
        record and transitions the status to PROCESSING.

        Args:
            bulk_purchase: The bulk purchase to create a session for.
            success_url: URL Stripe redirects to after successful payment.
            cancel_url: URL Stripe redirects to if the user cancels.

        Returns:
            The Stripe Checkout Session URL for redirecting the user.

        Raises:
            BulkPurchaseError: If the purchase is not in PENDING state or has
                a zero total.
            ValueError: If the conference has no Stripe secret key.
        """
        if bulk_purchase.payment_status != BulkPurchase.PaymentStatus.PENDING:
            msg = f"Cannot create checkout for purchase in '{bulk_purchase.get_payment_status_display()}' state."
            raise BulkPurchaseError(msg)

        if bulk_purchase.total_amount <= Decimal("0.00"):
            msg = "Cannot create a checkout session for a zero-amount purchase."
            raise BulkPurchaseError(msg)

        conference = bulk_purchase.conference
        stripe_client = StripeClient(conference)
        config = get_config()
        currency = config.currency
        amount = convert_amount_for_api(bulk_purchase.total_amount, currency)

        description = bulk_purchase.product_description or (f"Bulk voucher purchase ({bulk_purchase.quantity} codes)")

        session = stripe_client.client.v1.checkout.sessions.create(
            params={
                "mode": "payment",
                "line_items": [
                    {
                        "price_data": {
                            "currency": currency.lower(),
                            "unit_amount": convert_amount_for_api(bulk_purchase.unit_price, currency),
                            "product_data": {
                                "name": description,
                                "metadata": {
                                    "bulk_purchase_id": str(bulk_purchase.pk),
                                    "sponsor_id": str(bulk_purchase.sponsor_id),
                                },
                            },
                        },
                        "quantity": bulk_purchase.quantity,
                    }
                ],
                "metadata": {
                    "bulk_purchase_id": str(bulk_purchase.pk),
                    "conference_id": str(conference.pk),
                    "sponsor_id": str(bulk_purchase.sponsor_id),
                },
                "success_url": success_url,
                "cancel_url": cancel_url,
            },
            options={
                "idempotency_key": f"bulk-purchase-{bulk_purchase.pk}",
            },
        )

        with transaction.atomic():
            bp = BulkPurchase.objects.select_for_update().get(pk=bulk_purchase.pk)
            bp.stripe_checkout_session_id = session.id
            bp.payment_status = BulkPurchase.PaymentStatus.PROCESSING
            bp.save(update_fields=["stripe_checkout_session_id", "payment_status", "updated_at"])

        logger.info(
            "Created Stripe Checkout Session %s for BulkPurchase #%s (sponsor=%s, amount=%s)",
            session.id,
            bulk_purchase.pk,
            bulk_purchase.sponsor.name,
            amount,
        )

        return str(session.url)

    @staticmethod
    @transaction.atomic
    def fulfill_bulk_purchase(bulk_purchase: BulkPurchase) -> list[Voucher]:
        """Generate voucher codes for a paid bulk purchase.

        Idempotent: returns an empty list if the purchase is already fulfilled
        (status is PAID and vouchers have been generated). Generates codes using
        the voucher service's ``generate_voucher_codes()`` and creates
        ``BulkPurchaseVoucher`` links.

        Args:
            bulk_purchase: The bulk purchase to fulfill.

        Returns:
            List of newly created ``Voucher`` instances, or an empty list
            if already fulfilled.

        Raises:
            BulkPurchaseError: If the purchase is in a state that cannot be
                fulfilled (e.g. PENDING, FAILED, REFUNDED).
        """
        bp = BulkPurchase.objects.select_for_update().get(pk=bulk_purchase.pk)

        if bp.is_fulfilled and bp.payment_status == BulkPurchase.PaymentStatus.PAID:
            logger.info("BulkPurchase #%s already fulfilled, skipping", bp.pk)
            return []

        if bp.payment_status not in (
            BulkPurchase.PaymentStatus.APPROVED,
            BulkPurchase.PaymentStatus.PROCESSING,
            BulkPurchase.PaymentStatus.PAID,
        ):
            msg = f"Cannot fulfill BulkPurchase #{bp.pk} in '{bp.get_payment_status_display()}' state."
            raise BulkPurchaseError(msg)

        vc = bp.voucher_config if isinstance(bp.voucher_config, dict) else {}

        if not vc.get("voucher_type") or vc.get("discount_value") is None:
            msg = (
                f"Cannot fulfill BulkPurchase #{bp.pk}: voucher_config is missing "
                f"required fields (voucher_type, discount_value). "
                f"Configure these via the manage dashboard before fulfillment."
            )
            raise BulkPurchaseError(msg)
        voucher_type = str(vc.get("voucher_type", Voucher.VoucherType.COMP))
        discount_value = Decimal(str(vc.get("discount_value", 0)))
        max_uses = int(vc.get("max_uses", 1))

        sponsor_slug = (bp.sponsor.slug or "").upper()
        prefix = str(vc.get("prefix", f"BULK-{sponsor_slug}-"))

        valid_from = _parse_datetime(vc.get("valid_from"))
        valid_until = _parse_datetime(vc.get("valid_until"))

        applicable_ticket_types = None
        if bp.ticket_type_id is not None:
            applicable_ticket_types = TicketType.objects.filter(pk=bp.ticket_type_id)

        applicable_addons = None
        if bp.addon_id is not None:
            applicable_addons = AddOn.objects.filter(pk=bp.addon_id)

        config = VoucherBulkConfig(
            conference=bp.conference,
            prefix=prefix,
            count=bp.quantity,
            voucher_type=voucher_type,
            discount_value=discount_value,
            max_uses=max_uses,
            valid_from=valid_from,
            valid_until=valid_until,
            unlocks_hidden_tickets=bool(vc.get("unlocks_hidden_tickets", False)),
            applicable_ticket_types=applicable_ticket_types,
            applicable_addons=applicable_addons,
        )

        vouchers = generate_voucher_codes(config)

        links = [BulkPurchaseVoucher(bulk_purchase=bp, voucher=v) for v in vouchers]
        BulkPurchaseVoucher.objects.bulk_create(links)

        bp.payment_status = BulkPurchase.PaymentStatus.PAID
        bp.save(update_fields=["payment_status", "updated_at"])

        logger.info(
            "Fulfilled BulkPurchase #%s: generated %d voucher codes for sponsor %s",
            bp.pk,
            len(vouchers),
            bp.sponsor.name,
        )

        return vouchers

    @staticmethod
    def handle_checkout_webhook(session_id: str) -> BulkPurchase | None:
        """Handle a Stripe ``checkout.session.completed`` event for bulk purchases.

        Looks up the ``BulkPurchase`` by its stored checkout session ID,
        extracts the payment intent ID from the session data, and fulfills the
        purchase by generating voucher codes.

        Args:
            session_id: The Stripe Checkout Session ID from the webhook event.

        Returns:
            The fulfilled ``BulkPurchase``, or ``None`` if no matching purchase
            was found (the event may belong to a regular registration checkout).
        """
        try:
            bp = BulkPurchase.objects.select_related("sponsor", "conference").get(
                stripe_checkout_session_id=session_id,
            )
        except BulkPurchase.DoesNotExist:
            logger.debug(
                "No BulkPurchase found for checkout session %s (likely a regular checkout)",
                session_id,
            )
            return None

        if bp.is_fulfilled and bp.payment_status == BulkPurchase.PaymentStatus.PAID:
            logger.info(
                "BulkPurchase #%s already fulfilled for session %s",
                bp.pk,
                session_id,
            )
            return bp

        try:
            BulkPurchaseService.fulfill_bulk_purchase(bp)
        except BulkPurchaseError:
            logger.exception(
                "Failed to fulfill BulkPurchase #%s from webhook (session=%s)",
                bp.pk,
                session_id,
            )
            with transaction.atomic():
                BulkPurchase.objects.filter(pk=bp.pk).update(
                    payment_status=BulkPurchase.PaymentStatus.FAILED,
                )
            return None

        bp.refresh_from_db()
        return bp

    @staticmethod
    def mark_failed(bulk_purchase: BulkPurchase) -> None:
        """Transition a bulk purchase to FAILED state.

        Used when a checkout session expires or the payment is declined.
        Only transitions from PENDING or PROCESSING to avoid overwriting
        a purchase that has already been fulfilled (PAID) or refunded.

        Args:
            bulk_purchase: The bulk purchase to mark as failed.
        """
        with transaction.atomic():
            updated = (
                BulkPurchase.objects.select_for_update()
                .filter(
                    pk=bulk_purchase.pk,
                    payment_status__in=[
                        BulkPurchase.PaymentStatus.PENDING,
                        BulkPurchase.PaymentStatus.PROCESSING,
                    ],
                )
                .update(payment_status=BulkPurchase.PaymentStatus.FAILED)
            )
        if updated:
            logger.info("Marked BulkPurchase #%s as FAILED", bulk_purchase.pk)
        else:
            logger.info(
                "Skipped marking BulkPurchase #%s as FAILED (current status is not PENDING/PROCESSING)",
                bulk_purchase.pk,
            )
