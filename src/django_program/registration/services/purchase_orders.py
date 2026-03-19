"""Service layer for purchase order lifecycle management.

Handles PO creation, payment recording, credit note issuance, status
transitions, cancellation, and invoice PDF generation. All state-mutating
functions use atomic transactions to maintain consistency.
"""

import io
import logging
import secrets
import string
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

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
        ValueError: If the amount is not positive, the method is invalid,
            or the PO is cancelled.
    """
    if amount <= Decimal("0.00"):
        msg = f"Payment amount must be positive, got {amount}"
        raise ValueError(msg)

    valid_methods = {choice.value for choice in PurchaseOrderPayment.Method}
    if method not in valid_methods:
        msg = f"Invalid payment method '{method}', must be one of {sorted(valid_methods)}"
        raise ValueError(msg)

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
        ValueError: If the amount is not positive or the PO is cancelled.
    """
    if amount <= Decimal("0.00"):
        msg = f"Credit note amount must be positive, got {amount}"
        raise ValueError(msg)

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


def generate_invoice_pdf(purchase_order: PurchaseOrder) -> bytes:
    """Generate a professional invoice PDF for a purchase order.

    Produces a PDF with conference letterhead, billing details, line items,
    financial summary, and payment history. Uses the same reportlab pattern
    as the invitation letter generator.

    Args:
        purchase_order: The purchase order to generate an invoice for.

    Returns:
        The raw PDF bytes.
    """
    from reportlab.lib.pagesizes import A4  # noqa: PLC0415
    from reportlab.lib.units import mm  # noqa: PLC0415
    from reportlab.pdfgen import canvas  # noqa: PLC0415

    from django_program.settings import get_config  # noqa: PLC0415

    buf = io.BytesIO()
    width, height = A4
    c = canvas.Canvas(buf, pagesize=A4)
    margin = 25 * mm
    usable_width = width - 2 * margin

    conference = purchase_order.conference
    currency_sym = get_config().currency_symbol or "$"

    y = _draw_invoice_letterhead(c, conference, margin, height - margin, width)
    y = _draw_invoice_title(c, purchase_order, margin, y)
    y = _draw_bill_to(c, purchase_order, margin, y)
    y = _draw_line_items_table(c, purchase_order, margin, y, usable_width, currency_sym)
    y = _draw_financial_summary(c, purchase_order, margin, y, usable_width, currency_sym)
    y = _draw_payment_history(c, purchase_order, margin, y, usable_width, currency_sym)
    _draw_invoice_footer(c, conference, margin, y, width)

    c.showPage()
    c.save()
    return buf.getvalue()


def _draw_invoice_letterhead(c: object, conference: object, margin: float, y: float, width: float) -> float:
    """Draw conference letterhead at the top of the invoice.

    Args:
        c: The reportlab Canvas instance.
        conference: The conference model instance.
        margin: Left margin in points.
        y: Current y position.
        width: Page width in points.

    Returns:
        Updated y position after the letterhead.
    """
    from reportlab.lib.units import mm  # noqa: PLC0415

    c.setFont("Helvetica-Bold", 16)  # type: ignore[attr-defined]
    c.drawString(margin, y, str(conference.name))  # type: ignore[attr-defined]
    y -= 7 * mm

    if conference.venue or conference.address:
        c.setFont("Helvetica", 10)  # type: ignore[attr-defined]
        venue_line = ", ".join(filter(None, [str(conference.venue), str(conference.address)]))
        c.drawString(margin, y, venue_line)  # type: ignore[attr-defined]
        y -= 5 * mm

    if conference.website_url:
        c.setFont("Helvetica", 9)  # type: ignore[attr-defined]
        c.drawString(margin, y, str(conference.website_url))  # type: ignore[attr-defined]
        y -= 5 * mm

    y -= 5 * mm
    c.setStrokeColorRGB(0.7, 0.7, 0.7)  # type: ignore[attr-defined]
    c.line(margin, y, width - margin, y)  # type: ignore[attr-defined]
    y -= 10 * mm

    return y


def _draw_invoice_title(c: object, purchase_order: PurchaseOrder, margin: float, y: float) -> float:
    """Draw the invoice title and date.

    Args:
        c: The reportlab Canvas instance.
        purchase_order: The purchase order.
        margin: Left margin in points.
        y: Current y position.

    Returns:
        Updated y position after the title block.
    """
    from reportlab.lib.units import mm  # noqa: PLC0415

    c.setFont("Helvetica-Bold", 18)  # type: ignore[attr-defined]
    c.drawString(margin, y, f"INVOICE {purchase_order.reference}")  # type: ignore[attr-defined]
    y -= 8 * mm

    c.setFont("Helvetica", 10)  # type: ignore[attr-defined]
    today_str = timezone.now().strftime("%B %d, %Y")
    c.drawString(margin, y, f"Date: {today_str}")  # type: ignore[attr-defined]
    y -= 5 * mm

    c.drawString(margin, y, f"Status: {purchase_order.get_status_display()}")  # type: ignore[attr-defined]
    y -= 10 * mm

    return y


def _draw_bill_to(c: object, purchase_order: PurchaseOrder, margin: float, y: float) -> float:
    """Draw the Bill To section with organization and contact details.

    Args:
        c: The reportlab Canvas instance.
        purchase_order: The purchase order.
        margin: Left margin in points.
        y: Current y position.

    Returns:
        Updated y position after the billing section.
    """
    from reportlab.lib.units import mm  # noqa: PLC0415

    c.setFont("Helvetica-Bold", 11)  # type: ignore[attr-defined]
    c.drawString(margin, y, "Bill To:")  # type: ignore[attr-defined]
    y -= 6 * mm

    c.setFont("Helvetica", 10)  # type: ignore[attr-defined]
    c.drawString(margin + 5 * mm, y, str(purchase_order.organization_name))  # type: ignore[attr-defined]
    y -= 5 * mm

    if purchase_order.contact_name:
        c.drawString(margin + 5 * mm, y, str(purchase_order.contact_name))  # type: ignore[attr-defined]
        y -= 5 * mm

    c.drawString(margin + 5 * mm, y, str(purchase_order.contact_email))  # type: ignore[attr-defined]
    y -= 5 * mm

    if purchase_order.billing_address:
        for addr_line in str(purchase_order.billing_address).split("\n"):
            stripped = addr_line.strip()
            if stripped:
                c.drawString(margin + 5 * mm, y, stripped)  # type: ignore[attr-defined]
                y -= 5 * mm

    y -= 8 * mm
    return y


def _draw_line_items_table(  # noqa: PLR0913
    c: object, purchase_order: PurchaseOrder, margin: float, y: float, usable_width: float, currency_sym: str = "$"
) -> float:
    """Draw the line items table with headers and rows.

    Args:
        c: The reportlab Canvas instance.
        purchase_order: The purchase order.
        margin: Left margin in points.
        y: Current y position.
        usable_width: Available text width in points.
        currency_sym: Currency symbol to display before monetary values.

    Returns:
        Updated y position after the table.
    """
    from reportlab.lib.units import mm  # noqa: PLC0415

    col_desc_x = margin
    col_qty_x = margin + usable_width * 0.55
    col_price_x = margin + usable_width * 0.70
    col_total_x = margin + usable_width * 0.85

    c.setFont("Helvetica-Bold", 10)  # type: ignore[attr-defined]
    c.drawString(col_desc_x, y, "Description")  # type: ignore[attr-defined]
    c.drawRightString(col_qty_x + 30, y, "Qty")  # type: ignore[attr-defined]
    c.drawRightString(col_price_x + 40, y, "Unit Price")  # type: ignore[attr-defined]
    c.drawRightString(col_total_x + 40, y, "Line Total")  # type: ignore[attr-defined]
    y -= 3 * mm

    c.setStrokeColorRGB(0.7, 0.7, 0.7)  # type: ignore[attr-defined]
    c.line(margin, y, margin + usable_width, y)  # type: ignore[attr-defined]
    y -= 5 * mm

    c.setFont("Helvetica", 10)  # type: ignore[attr-defined]
    line_items = purchase_order.line_items.all()
    for item in line_items:
        desc_text = str(item.description)
        wrapped = _invoice_wrap_text(c, desc_text, "Helvetica", 10, usable_width * 0.52)
        for i, segment in enumerate(wrapped):
            c.drawString(col_desc_x, y, segment)  # type: ignore[attr-defined]
            if i == 0:
                c.drawRightString(col_qty_x + 30, y, str(item.quantity))  # type: ignore[attr-defined]
                c.drawRightString(col_price_x + 40, y, f"{currency_sym}{item.unit_price}")  # type: ignore[attr-defined]
                c.drawRightString(col_total_x + 40, y, f"{currency_sym}{item.line_total}")  # type: ignore[attr-defined]
            y -= 5 * mm

    y -= 3 * mm
    c.setStrokeColorRGB(0.7, 0.7, 0.7)  # type: ignore[attr-defined]
    c.line(margin, y, margin + usable_width, y)  # type: ignore[attr-defined]
    y -= 6 * mm

    return y


def _draw_financial_summary(  # noqa: PLR0913
    c: object, purchase_order: PurchaseOrder, margin: float, y: float, usable_width: float, currency_sym: str = "$"
) -> float:
    """Draw the financial summary (subtotal, total, paid, credits, balance).

    Args:
        c: The reportlab Canvas instance.
        purchase_order: The purchase order.
        margin: Left margin in points.
        y: Current y position.
        usable_width: Available text width in points.
        currency_sym: Currency symbol to display before monetary values.

    Returns:
        Updated y position after the summary.
    """
    from reportlab.lib.units import mm  # noqa: PLC0415

    value_x = margin + usable_width * 0.85 + 40

    summary_lines: list[tuple[str, str, str, bool]] = [
        ("Subtotal:", f"{currency_sym}{purchase_order.subtotal}", "Helvetica", False),
        ("Total:", f"{currency_sym}{purchase_order.total}", "Helvetica-Bold", False),
        ("Total Paid:", f"{currency_sym}{purchase_order.total_paid}", "Helvetica", False),
    ]

    total_credited = purchase_order.total_credited
    if total_credited:
        summary_lines.append(("Total Credits:", f"{currency_sym}{total_credited}", "Helvetica", False))

    summary_lines.append(("Balance Due:", f"{currency_sym}{purchase_order.balance_due}", "Helvetica-Bold", True))

    for label, value, font, is_large in summary_lines:
        size = 12 if is_large else 10
        c.setFont(font, size)  # type: ignore[attr-defined]
        c.drawRightString(value_x - 50, y, label)  # type: ignore[attr-defined]
        c.drawRightString(value_x, y, value)  # type: ignore[attr-defined]
        y -= 6 * mm

    y -= 4 * mm
    return y


def _draw_payment_history(  # noqa: PLR0913
    c: object, purchase_order: PurchaseOrder, margin: float, y: float, usable_width: float, currency_sym: str = "$"
) -> float:
    """Draw the payment history section.

    Args:
        c: The reportlab Canvas instance.
        purchase_order: The purchase order.
        margin: Left margin in points.
        y: Current y position.
        usable_width: Available text width in points.
        currency_sym: Currency symbol to display before monetary values.

    Returns:
        Updated y position after the payment history.
    """
    from reportlab.lib.units import mm  # noqa: PLC0415

    payments = purchase_order.payments.all()
    if not payments:
        return y

    c.setFont("Helvetica-Bold", 11)  # type: ignore[attr-defined]
    c.drawString(margin, y, "Payment History")  # type: ignore[attr-defined]
    y -= 6 * mm

    c.setStrokeColorRGB(0.7, 0.7, 0.7)  # type: ignore[attr-defined]
    c.line(margin, y, margin + usable_width, y)  # type: ignore[attr-defined]
    y -= 5 * mm

    c.setFont("Helvetica", 9)  # type: ignore[attr-defined]
    for payment in payments:
        date_str = payment.payment_date.strftime("%b %d, %Y")
        method_str = payment.get_method_display()
        ref_str = f" (ref: {payment.reference})" if payment.reference else ""
        line = f"{date_str}  —  {method_str}  —  {currency_sym}{payment.amount}{ref_str}"
        c.drawString(margin, y, line)  # type: ignore[attr-defined]
        y -= 5 * mm

    y -= 4 * mm
    return y


def _draw_invoice_footer(c: object, conference: object, margin: float, _y: float, width: float) -> None:
    """Draw the invoice footer with generation date and conference name.

    Args:
        c: The reportlab Canvas instance.
        conference: The conference model instance.
        margin: Left margin in points.
        _y: Current y position (accepted for calling convention; footer draws at fixed position).
        width: Page width in points.
    """
    from reportlab.lib.units import mm  # noqa: PLC0415

    footer_y = 20 * mm

    c.setStrokeColorRGB(0.85, 0.85, 0.85)  # type: ignore[attr-defined]
    c.line(margin, footer_y + 5 * mm, width - margin, footer_y + 5 * mm)  # type: ignore[attr-defined]

    c.setFont("Helvetica", 8)  # type: ignore[attr-defined]
    today_str = timezone.now().strftime("%B %d, %Y")
    c.drawString(margin, footer_y, f"Generated on {today_str}")  # type: ignore[attr-defined]
    c.drawRightString(width - margin, footer_y, str(conference.name))  # type: ignore[attr-defined]


def _invoice_wrap_text(canvas_obj: object, text: str, font: str, size: int, max_width: float) -> list[str]:
    """Wrap text to fit within a given width on a reportlab canvas.

    Args:
        canvas_obj: The reportlab Canvas instance.
        text: The text to wrap.
        font: Font name for width calculation.
        size: Font size in points.
        max_width: Maximum line width in points.

    Returns:
        A list of text segments, each fitting within ``max_width``.
    """
    words = text.split()
    lines: list[str] = []
    current_line = ""

    for word in words:
        test_line = f"{current_line} {word}".strip() if current_line else word
        tw = canvas_obj.stringWidth(test_line, font, size)  # type: ignore[attr-defined]
        if tw <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines or [""]
