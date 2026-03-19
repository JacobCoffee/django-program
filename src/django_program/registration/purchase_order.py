"""Purchase order and corporate invoicing models.

Supports offline corporate purchases where organizations pay via wire transfer,
ACH, check, or other non-card methods. Each purchase order tracks line items,
partial payments, and credit notes independently of the cart/checkout flow.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models


class PurchaseOrder(models.Model):
    """A corporate purchase order for bulk or invoiced ticket purchases.

    Purchase orders exist outside the normal cart/checkout flow and support
    partial payments over time via wire, ACH, check, or Stripe. The
    ``balance_due`` property tracks the remaining amount after payments
    and credit notes.
    """

    class Status(models.TextChoices):
        """Lifecycle states for a purchase order."""

        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        PARTIALLY_PAID = "partially_paid", "Partially Paid"
        PAID = "paid", "Paid"
        OVERPAID = "overpaid", "Overpaid"
        CANCELLED = "cancelled", "Cancelled"

    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="purchase_orders",
    )
    organization_name = models.CharField(max_length=300)
    contact_email = models.EmailField()
    contact_name = models.CharField(max_length=200)
    billing_address = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    stripe_invoice_id = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Stripe Invoice ID (e.g. in_xxx) when sent via Stripe Invoicing.",
    )
    stripe_invoice_url = models.URLField(
        max_length=500,
        blank=True,
        default="",
        help_text="Stripe-hosted invoice URL for the customer to pay online.",
    )
    qbo_invoice_id = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="QuickBooks Online Invoice ID, set after invoice creation.",
    )
    qbo_invoice_url = models.URLField(
        max_length=500,
        blank=True,
        default="",
        help_text="Public URL to the QBO invoice for the customer.",
    )
    notes = models.TextField(blank=True, default="")
    reference = models.CharField(
        max_length=100,
        unique=True,
        help_text='Unique PO reference, e.g. "PO-A1B2C3".',
    )
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_purchase_orders",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.reference} ({self.status})"

    @property
    def total_paid(self) -> Decimal:
        """Return the sum of all recorded payment amounts.

        Uses the ``_annotated_total_paid`` annotation when available (set by
        list views) to avoid per-row aggregate queries.
        """
        annotated = getattr(self, "_annotated_total_paid", None)
        if annotated is not None:
            return Decimal(str(annotated))
        return self.payments.aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")

    @property
    def total_credited(self) -> Decimal:
        """Return the sum of all credit note amounts.

        Uses the ``_annotated_total_credited`` annotation when available (set by
        list views) to avoid per-row aggregate queries.
        """
        annotated = getattr(self, "_annotated_total_credited", None)
        if annotated is not None:
            return Decimal(str(annotated))
        return self.credit_notes.aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")

    @property
    def balance_due(self) -> Decimal:
        """Return the outstanding balance after payments and credit notes."""
        return self.total - self.total_paid - self.total_credited


class PurchaseOrderLineItem(models.Model):
    """A single line item on a purchase order.

    Each line references an optional ticket type or add-on for traceability,
    but the description and pricing are snapshotted at creation time.
    """

    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="line_items",
    )
    description = models.CharField(max_length=300)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    line_total = models.DecimalField(max_digits=10, decimal_places=2)
    ticket_type = models.ForeignKey(
        "program_registration.TicketType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_order_line_items",
    )
    addon = models.ForeignKey(
        "program_registration.AddOn",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_order_line_items",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.quantity}x {self.description}"


class PurchaseOrderPayment(models.Model):
    """A payment recorded against a purchase order.

    Tracks individual payments received via wire transfer, ACH, check,
    Stripe, or other methods. Multiple payments can be recorded as
    partial payments arrive.
    """

    class Method(models.TextChoices):
        """Supported payment methods for purchase orders."""

        WIRE = "wire", "Wire Transfer"
        ACH = "ach", "ACH"
        CHECK = "check", "Check"
        STRIPE = "stripe", "Stripe"
        OTHER = "other", "Other"

    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="payments",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reference = models.CharField(max_length=200, blank=True, default="")
    method = models.CharField(
        max_length=20,
        choices=Method.choices,
        default=Method.WIRE,
    )
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entered_po_payments",
    )
    payment_date = models.DateField()
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-payment_date"]

    def __str__(self) -> str:
        return f"{self.get_method_display()} {self.amount} on {self.payment_date}"


class PurchaseOrderCreditNote(models.Model):
    """A credit note issued against a purchase order.

    Reduces the effective balance due on the purchase order. Used for
    adjustments, corrections, or partial cancellations.
    """

    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="credit_notes",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField()
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issued_po_credit_notes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Credit {self.amount} — {str(self.reason)[:50]}"
