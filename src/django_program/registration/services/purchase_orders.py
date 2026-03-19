"""Service layer for purchase order lifecycle management.

Handles PO creation, payment recording, credit note issuance, status
transitions, and cancellation. All state-mutating functions use atomic
transactions to maintain consistency.
"""

import logging
import secrets
import string
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import transaction

from django_program.registration.purchase_order import (
    PurchaseOrder,
    PurchaseOrderCreditNote,
    PurchaseOrderLineItem,
    PurchaseOrderPayment,
)

if TYPE_CHECKING:
    import datetime

    from django.contrib.auth.models import AbstractBaseUser

    from django_program.conference.models import Conference

logger = logging.getLogger(__name__)

_PO_REFERENCE_LENGTH = 6
_PO_REFERENCE_PREFIX = "PO"
_MAX_REFERENCE_ATTEMPTS = 10


def generate_po_reference() -> str:
    """Generate a unique PO reference like ``PO-A1B2C3``.

    Uses cryptographically random alphanumeric characters. Retries on
    collision up to a fixed limit.

    Returns:
        A unique reference string.

    Raises:
        RuntimeError: If a unique reference cannot be generated after
            multiple attempts.
    """
    chars = string.ascii_uppercase + string.digits
    for _ in range(_MAX_REFERENCE_ATTEMPTS):
        suffix = "".join(secrets.choice(chars) for _ in range(_PO_REFERENCE_LENGTH))
        ref = f"{_PO_REFERENCE_PREFIX}-{suffix}"
        if not PurchaseOrder.objects.filter(reference=ref).exists():
            return ref
    msg = "Could not generate a unique PO reference after multiple attempts"
    raise RuntimeError(msg)


LineItemData = dict[str, object]


@transaction.atomic
def create_purchase_order(  # noqa: PLR0913
    *,
    conference: Conference,
    organization_name: str,
    contact_email: str,
    contact_name: str,
    billing_address: str = "",
    line_items: list[LineItemData],
    notes: str = "",
    created_by: AbstractBaseUser | None = None,
) -> PurchaseOrder:
    """Create a purchase order with line items and computed totals.

    Each entry in ``line_items`` should be a dict with keys:
    ``description``, ``quantity``, ``unit_price``, and optionally
    ``ticket_type`` and ``addon`` (model instances or None).

    Args:
        conference: The conference this PO belongs to.
        organization_name: Name of the purchasing organization.
        contact_email: Primary contact email address.
        contact_name: Primary contact person name.
        billing_address: Optional billing address text.
        line_items: List of line item dicts to create.
        notes: Optional internal notes.
        created_by: The staff user creating the PO.

    Returns:
        The newly created PurchaseOrder with line items.

    Raises:
        RuntimeError: If a unique reference cannot be generated.
        IntegrityError: On reference collision (extremely unlikely).
    """
    reference = generate_po_reference()

    po = PurchaseOrder.objects.create(
        conference=conference,
        organization_name=organization_name,
        contact_email=contact_email,
        contact_name=contact_name,
        billing_address=billing_address,
        status=PurchaseOrder.Status.DRAFT,
        notes=notes,
        reference=reference,
        created_by=created_by,
    )

    subtotal = Decimal("0.00")
    for item_data in line_items:
        quantity = int(item_data.get("quantity", 1))
        unit_price = Decimal(str(item_data["unit_price"]))
        line_total = unit_price * quantity
        subtotal += line_total

        PurchaseOrderLineItem.objects.create(
            purchase_order=po,
            description=str(item_data["description"]),
            quantity=quantity,
            unit_price=unit_price,
            line_total=line_total,
            ticket_type=item_data.get("ticket_type"),
            addon=item_data.get("addon"),
        )

    po.subtotal = subtotal
    po.total = subtotal
    po.save(update_fields=["subtotal", "total", "updated_at"])

    logger.info("Created purchase order %s for %s", reference, organization_name)
    return po


@transaction.atomic
def record_payment(  # noqa: PLR0913
    purchase_order: PurchaseOrder,
    *,
    amount: Decimal,
    method: str,
    reference: str = "",
    payment_date: datetime.date,
    entered_by: AbstractBaseUser | None = None,
    note: str = "",
) -> PurchaseOrderPayment:
    """Record a payment against a purchase order and update its status.

    Args:
        purchase_order: The PO to record payment against.
        amount: Payment amount (must be positive).
        method: Payment method (one of PurchaseOrderPayment.Method values).
        reference: Optional external reference (e.g. wire transfer ID).
        payment_date: Date the payment was received.
        entered_by: Staff user recording the payment.
        note: Optional note about the payment.

    Returns:
        The newly created PurchaseOrderPayment.

    Raises:
        ValueError: If the PO is cancelled.
    """
    # Lock the PO row to prevent concurrent status races.
    po = PurchaseOrder.objects.select_for_update().get(pk=purchase_order.pk)
    if po.status == PurchaseOrder.Status.CANCELLED:
        msg = f"Cannot record payment on cancelled PO {po.reference}"
        raise ValueError(msg)

    payment = PurchaseOrderPayment.objects.create(
        purchase_order=po,
        amount=amount,
        method=method,
        reference=reference,
        payment_date=payment_date,
        entered_by=entered_by,
        note=note,
    )

    update_po_status(po)

    logger.info(
        "Recorded %s payment of %s for PO %s",
        method,
        amount,
        purchase_order.reference,
    )
    return payment


@transaction.atomic
def issue_credit_note(
    purchase_order: PurchaseOrder,
    *,
    amount: Decimal,
    reason: str,
    issued_by: AbstractBaseUser | None = None,
) -> PurchaseOrderCreditNote:
    """Issue a credit note against a purchase order and update its status.

    Args:
        purchase_order: The PO to issue a credit note against.
        amount: Credit note amount (must be positive).
        reason: Explanation for the credit.
        issued_by: Staff user issuing the credit note.

    Returns:
        The newly created PurchaseOrderCreditNote.

    Raises:
        ValueError: If the PO is cancelled.
    """
    # Lock the PO row to prevent concurrent status races.
    po = PurchaseOrder.objects.select_for_update().get(pk=purchase_order.pk)
    if po.status == PurchaseOrder.Status.CANCELLED:
        msg = f"Cannot issue credit note on cancelled PO {po.reference}"
        raise ValueError(msg)

    credit_note = PurchaseOrderCreditNote.objects.create(
        purchase_order=po,
        amount=amount,
        reason=reason,
        issued_by=issued_by,
    )

    update_po_status(po)

    logger.info(
        "Issued credit note of %s for PO %s: %s",
        amount,
        purchase_order.reference,
        reason[:80],
    )
    return credit_note


def update_po_status(purchase_order: PurchaseOrder) -> None:
    """Recompute and save the PO status based on payments and credits.

    Status transitions:
    - ``draft`` remains if no payments/credits and status is draft
    - ``paid`` when balance_due is exactly zero and financial activity exists
    - ``overpaid`` when balance_due is negative
    - ``partially_paid`` when some payments exist but balance remains
    - ``sent`` when no payments exist and status is not draft

    This function expects the caller to hold a row-level lock on the PO
    (via ``select_for_update``) when called inside a transaction.

    Args:
        purchase_order: The PO whose status should be recomputed.
    """
    purchase_order.refresh_from_db()

    if purchase_order.status == PurchaseOrder.Status.CANCELLED:
        return

    balance = purchase_order.balance_due
    total_paid = purchase_order.total_paid
    total_credited = purchase_order.total_credited
    has_financial_activity = total_paid > Decimal("0.00") or total_credited > Decimal("0.00")

    if balance == Decimal("0.00") and has_financial_activity:
        new_status = PurchaseOrder.Status.PAID
    elif balance < Decimal("0.00"):
        new_status = PurchaseOrder.Status.OVERPAID
    elif total_paid > Decimal("0.00"):
        new_status = PurchaseOrder.Status.PARTIALLY_PAID
    elif purchase_order.status == PurchaseOrder.Status.DRAFT:
        new_status = PurchaseOrder.Status.DRAFT
    else:
        new_status = PurchaseOrder.Status.SENT

    if new_status != purchase_order.status:
        purchase_order.status = new_status
        purchase_order.save(update_fields=["status", "updated_at"])


def send_purchase_order(purchase_order: PurchaseOrder) -> None:
    """Transition a draft purchase order to sent status.

    Args:
        purchase_order: The PO to mark as sent.

    Raises:
        ValueError: If the PO is not in draft status.
    """
    if purchase_order.status != PurchaseOrder.Status.DRAFT:
        msg = f"Only draft POs can be sent (current status: {purchase_order.status})"
        raise ValueError(msg)
    purchase_order.status = PurchaseOrder.Status.SENT
    purchase_order.save(update_fields=["status", "updated_at"])
    logger.info("Marked purchase order %s as sent", purchase_order.reference)


def cancel_purchase_order(purchase_order: PurchaseOrder) -> None:
    """Cancel a purchase order.

    Sets the status to CANCELLED. Does not delete any associated payment
    or credit note records for audit purposes.

    Args:
        purchase_order: The PO to cancel.
    """
    purchase_order.status = PurchaseOrder.Status.CANCELLED
    purchase_order.save(update_fields=["status", "updated_at"])
    logger.info("Cancelled purchase order %s", purchase_order.reference)
