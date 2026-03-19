"""Stripe Invoicing integration for purchase orders.

Creates, sends, and syncs Stripe Invoices for corporate POs. Uses the
per-conference ``StripeClient`` pattern so each conference's Stripe account
handles its own invoices. Supports card and ACH payments via Stripe's
hosted invoice page.
"""

import datetime
import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import transaction

from django_program.registration.purchase_order import (
    PurchaseOrder,
    PurchaseOrderLineItem,
)
from django_program.registration.services.purchase_orders import (
    record_payment,
    update_po_status,
)
from django_program.registration.stripe_client import StripeClient
from django_program.registration.stripe_utils import (
    convert_amount_for_api,
    convert_amount_for_db,
)
from django_program.settings import get_config

if TYPE_CHECKING:
    import stripe

    from django_program.conference.models import Conference

logger = logging.getLogger(__name__)


def _get_stripe_client(conference: Conference) -> stripe.StripeClient:
    """Build a raw ``stripe.StripeClient`` for the conference.

    Uses the same validation as :class:`StripeClient` but returns the
    underlying SDK client for direct API access to invoicing endpoints.

    Args:
        conference: The conference whose Stripe keys will be used.

    Returns:
        A configured ``stripe.StripeClient`` instance.

    Raises:
        ValueError: If the conference has no Stripe secret key configured.
    """
    sc = StripeClient(conference)
    return sc.client


def _get_or_create_invoice_customer(
    client: stripe.StripeClient,
    *,
    email: str,
    name: str,
    conference_slug: str,
) -> str:
    """Find an existing Stripe Customer by email or create one.

    Searches the conference's Stripe account for a customer matching the
    given email. If none exists, creates a new one with the organization
    name as metadata.

    Args:
        client: The Stripe SDK client.
        email: Customer email address.
        name: Organization or contact name.
        conference_slug: Conference slug for metadata tagging.

    Returns:
        The Stripe Customer ID.
    """
    existing = client.v1.customers.list(params={"email": email, "limit": 1})
    if existing.data:
        return existing.data[0].id

    customer = client.v1.customers.create(
        params={
            "email": email,
            "name": name,
            "metadata": {
                "conference_slug": conference_slug,
                "source": "purchase_order",
            },
        },
    )
    return customer.id


def create_stripe_invoice(purchase_order: PurchaseOrder) -> str:
    """Create and send a Stripe Invoice for a purchase order.

    Builds a Stripe Invoice with line items matching the PO, finalizes it,
    and stores the invoice ID and hosted URL on the PO record.

    Args:
        purchase_order: The purchase order to invoice.

    Returns:
        The Stripe-hosted invoice URL where the customer can pay.

    Raises:
        ValueError: If the conference has no Stripe key, or if the PO
            already has a Stripe invoice attached.
        stripe.StripeError: On any Stripe API failure.
    """
    if purchase_order.stripe_invoice_id:
        msg = f"PO {purchase_order.reference} already has a Stripe invoice: {purchase_order.stripe_invoice_id}"
        raise ValueError(msg)

    conference = purchase_order.conference
    client = _get_stripe_client(conference)
    config = get_config()
    currency = config.currency.lower()

    customer_id = _get_or_create_invoice_customer(
        client,
        email=str(purchase_order.contact_email),
        name=str(purchase_order.organization_name),
        conference_slug=str(conference.slug),
    )

    invoice = client.v1.invoices.create(
        params={
            "customer": customer_id,
            "collection_method": "send_invoice",
            "days_until_due": 30,
            "currency": currency,
            "metadata": {
                "purchase_order_id": str(purchase_order.pk),
                "purchase_order_ref": str(purchase_order.reference),
                "conference_slug": str(conference.slug),
            },
        },
    )

    line_items = PurchaseOrderLineItem.objects.filter(purchase_order=purchase_order)
    for item in line_items:
        unit_amount = convert_amount_for_api(item.unit_price, currency)
        client.v1.invoice_items.create(
            params={
                "customer": customer_id,
                "invoice": invoice.id,
                "description": str(item.description),
                "quantity": item.quantity,
                "unit_amount": unit_amount,
                "currency": currency,
            },
        )

    finalized = client.v1.invoices.finalize_invoice(invoice.id)

    client.v1.invoices.send_invoice(finalized.id)

    hosted_url = finalized.hosted_invoice_url or ""

    purchase_order.stripe_invoice_id = finalized.id
    purchase_order.stripe_invoice_url = hosted_url
    purchase_order.save(
        update_fields=[
            "stripe_invoice_id",
            "stripe_invoice_url",
            "updated_at",
        ]
    )

    logger.info(
        "Created Stripe invoice %s for PO %s (customer %s)",
        finalized.id,
        purchase_order.reference,
        customer_id,
    )
    return hosted_url


def sync_stripe_invoice_status(purchase_order: PurchaseOrder) -> None:
    """Fetch the Stripe invoice and sync payment status to the PO.

    If Stripe reports the invoice as fully paid, records a payment via
    :func:`record_payment` with method ``stripe``. Handles partial payments
    when ``amount_paid < amount_due``.

    Args:
        purchase_order: The PO with a ``stripe_invoice_id`` to sync.

    Raises:
        ValueError: If the PO has no Stripe invoice ID.
        stripe.StripeError: On any Stripe API failure.
    """
    if not purchase_order.stripe_invoice_id:
        msg = f"PO {purchase_order.reference} has no Stripe invoice to sync"
        raise ValueError(msg)

    conference = purchase_order.conference
    client = _get_stripe_client(conference)
    config = get_config()
    currency = config.currency

    invoice = client.v1.invoices.retrieve(purchase_order.stripe_invoice_id)

    amount_paid = convert_amount_for_db(invoice.amount_paid or 0, currency)
    already_recorded = purchase_order.total_paid

    new_amount = amount_paid - already_recorded
    if new_amount <= Decimal("0.00"):
        logger.debug(
            "No new payment to record for PO %s (Stripe paid=%s, recorded=%s)",
            purchase_order.reference,
            amount_paid,
            already_recorded,
        )
        return

    today = datetime.date.today()  # noqa: DTZ011
    record_payment(
        purchase_order,
        amount=new_amount,
        method="stripe",
        reference=purchase_order.stripe_invoice_id,
        payment_date=today,
        note=f"Auto-synced from Stripe invoice {purchase_order.stripe_invoice_id}",
    )

    logger.info(
        "Synced Stripe payment of %s for PO %s (invoice status: %s)",
        new_amount,
        purchase_order.reference,
        invoice.status,
    )


def handle_invoice_paid_webhook(stripe_event_payload: dict[str, object]) -> None:
    """Process an ``invoice.paid`` webhook event from Stripe.

    Looks up the PO by the Stripe invoice ID embedded in the event data.
    If found, records the payment amount and updates the PO status.

    Args:
        stripe_event_payload: The full Stripe event payload dict. Expected
            to contain ``data.object`` with invoice fields.
    """
    data_wrapper: object = stripe_event_payload.get("data", {})
    if not isinstance(data_wrapper, dict):
        logger.warning("Unexpected webhook payload structure")
        return

    invoice_data: object = data_wrapper["object"] if "object" in data_wrapper else {}  # noqa: SIM401
    if not isinstance(invoice_data, dict):
        logger.warning("Unexpected invoice data type in webhook payload")
        return

    stripe_invoice_id = str(invoice_data["id"]) if "id" in invoice_data else ""
    if not stripe_invoice_id:
        logger.warning("No invoice ID in webhook payload")
        return

    with transaction.atomic():
        try:
            po = PurchaseOrder.objects.select_for_update().get(
                stripe_invoice_id=stripe_invoice_id,
            )
        except PurchaseOrder.DoesNotExist:
            logger.debug(
                "No PO found for Stripe invoice %s (may not be a PO invoice)",
                stripe_invoice_id,
            )
            return

        if po.status in (PurchaseOrder.Status.PAID, PurchaseOrder.Status.CANCELLED):
            logger.info(
                "PO %s already %s, skipping webhook for invoice %s",
                po.reference,
                po.status,
                stripe_invoice_id,
            )
            return

        config = get_config()
        currency = config.currency
        amount_paid_cents = invoice_data["amount_paid"] if "amount_paid" in invoice_data else 0  # noqa: SIM401
        amount_paid = convert_amount_for_db(int(amount_paid_cents), currency)

        already_recorded = po.total_paid
        new_amount = amount_paid - already_recorded

        if new_amount <= Decimal("0.00"):
            logger.debug(
                "Webhook for invoice %s: no new amount to record (paid=%s, recorded=%s)",
                stripe_invoice_id,
                amount_paid,
                already_recorded,
            )
            update_po_status(po)
            return

        today = datetime.date.today()  # noqa: DTZ011
        record_payment(
            po,
            amount=new_amount,
            method="stripe",
            reference=stripe_invoice_id,
            payment_date=today,
            note=f"Stripe webhook invoice.paid ({stripe_invoice_id})",
        )

        logger.info(
            "Processed invoice.paid webhook: recorded %s for PO %s",
            new_amount,
            po.reference,
        )
