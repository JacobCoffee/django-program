"""Stripe Terminal payment model for in-person POS transactions.

Records terminal-specific metadata (reader ID, card details, capture lifecycle)
alongside the base Payment record created during checkout at the registration desk.
"""

from django.db import models


class TerminalPayment(models.Model):
    """Records an in-person Stripe Terminal payment at the registration desk.

    Extends the payment tracking with terminal-specific fields for reader
    identification, pre-authorization state, and capture lifecycle.
    """

    class CaptureStatus(models.TextChoices):
        """Lifecycle states for a terminal payment capture."""

        AUTHORIZED = "authorized", "Authorized"
        CAPTURED = "captured", "Captured"
        CANCELLED = "cancelled", "Cancelled"
        FAILED = "failed", "Failed"

    payment = models.OneToOneField(
        "program_registration.Payment",
        on_delete=models.CASCADE,
        related_name="terminal_detail",
    )
    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="terminal_payments",
    )
    terminal_id = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Stripe Terminal Location ID.",
    )
    reader_id = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Stripe Terminal Reader ID that processed the payment.",
    )
    payment_intent_id = models.CharField(
        max_length=200,
        help_text="Stripe PaymentIntent ID for this terminal transaction.",
    )
    capture_status = models.CharField(
        max_length=20,
        choices=CaptureStatus.choices,
        default=CaptureStatus.AUTHORIZED,
    )
    captured_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    card_brand = models.CharField(max_length=50, blank=True, default="")
    card_last4 = models.CharField(max_length=4, blank=True, default="")
    receipt_url = models.URLField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Terminal {self.payment_intent_id} ({self.capture_status})"
