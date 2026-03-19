"""On-site check-in and product redemption models for conference registration.

Provides models for tracking attendee check-ins at the conference venue,
per-product door checks (tutorials, meals, events), and product redemption
to prevent double-use of purchased items.
"""

from django.conf import settings
from django.db import models


class CheckIn(models.Model):
    """Records a single check-in event for an attendee at the conference.

    Multiple check-ins per attendee are allowed to support re-entry scenarios
    (e.g. leaving for lunch and returning). Each record captures who performed
    the check-in and at which station.
    """

    attendee = models.ForeignKey(
        "program_registration.Attendee",
        on_delete=models.CASCADE,
        related_name="checkins",
    )
    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="checkins",
    )
    checked_in_at = models.DateTimeField(auto_now_add=True)
    checked_in_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="performed_checkins",
        help_text="Staff member who performed this check-in.",
    )
    station = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text='Station identifier, e.g. "Door A", "Registration Desk 1".',
    )
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-checked_in_at"]

    def __str__(self) -> str:
        return f"CheckIn: {self.attendee} at {self.checked_in_at}"


class DoorCheck(models.Model):
    """Per-product admission tracking for a specific ticket type or add-on.

    Used for checking attendees into sub-events such as tutorials, meals,
    or social events that require separate admission control beyond the
    main conference check-in.
    """

    attendee = models.ForeignKey(
        "program_registration.Attendee",
        on_delete=models.CASCADE,
        related_name="door_checks",
    )
    ticket_type = models.ForeignKey(
        "program_registration.TicketType",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="door_checks",
    )
    addon = models.ForeignKey(
        "program_registration.AddOn",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="door_checks",
    )
    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="door_checks",
    )
    checked_at = models.DateTimeField(auto_now_add=True)
    checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="performed_door_checks",
        help_text="Staff member who performed this door check.",
    )
    station = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text='Station identifier, e.g. "Tutorial Room 1", "Meal Hall".',
    )

    class Meta:
        ordering = ["-checked_at"]

    def __str__(self) -> str:
        product = self.ticket_type or self.addon or "unknown"
        return f"DoorCheck: {self.attendee} → {product} at {self.checked_at}"


class ProductRedemption(models.Model):
    """Tracks redemption of a purchased order line item.

    Each attendee can redeem a given order line item up to its purchased
    ``quantity`` times. The business-layer limit is enforced by
    ``RedemptionService.redeem_product()`` with row-level locking; no
    unique constraint exists at the DB level so that quantity > 1 items
    can produce multiple redemption rows.
    """

    attendee = models.ForeignKey(
        "program_registration.Attendee",
        on_delete=models.CASCADE,
        related_name="redemptions",
    )
    order_line_item = models.ForeignKey(
        "program_registration.OrderLineItem",
        on_delete=models.CASCADE,
        related_name="redemptions",
    )
    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="redemptions",
    )
    redeemed_at = models.DateTimeField(auto_now_add=True)
    redeemed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="performed_redemptions",
        help_text="Staff member who performed this redemption.",
    )
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-redeemed_at"]

    def __str__(self) -> str:
        return f"Redemption: {self.attendee} → {self.order_line_item}"
