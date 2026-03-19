"""Visa invitation letter request model for conference attendees.

Tracks the lifecycle of invitation letter requests from submission through
review, PDF generation, and delivery. Used by attendees who need a formal
invitation letter for visa applications.
"""

from django.conf import settings
from django.db import models


class LetterRequest(models.Model):
    """A request for a visa invitation letter from a conference attendee.

    Captures passport and travel details needed to produce a formal letter
    for embassy submission. Progresses through a review workflow from
    ``SUBMITTED`` to ``SENT`` (or ``REJECTED``).
    """

    class Status(models.TextChoices):
        """Workflow states for a letter request."""

        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under Review"
        APPROVED = "approved", "Approved"
        GENERATED = "generated", "Generated"
        SENT = "sent", "Sent"
        REJECTED = "rejected", "Rejected"

    ALLOWED_TRANSITIONS: dict[str, set[str]] = {
        Status.SUBMITTED: {Status.UNDER_REVIEW, Status.APPROVED, Status.REJECTED},
        Status.UNDER_REVIEW: {Status.APPROVED, Status.REJECTED},
        Status.APPROVED: {Status.GENERATED},
        Status.GENERATED: {Status.SENT},
    }

    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="letter_requests",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="letter_requests",
    )
    attendee = models.ForeignKey(
        "program_registration.Attendee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="letter_requests",
    )

    passport_name = models.CharField(max_length=300)
    passport_number = models.CharField(max_length=50)
    nationality = models.CharField(max_length=100)
    date_of_birth = models.DateField(null=True, blank=True)
    travel_from = models.DateField()
    travel_until = models.DateField()
    destination_address = models.TextField()
    embassy_name = models.CharField(max_length=300, blank=True, default="")

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SUBMITTED,
    )
    rejection_reason = models.TextField(blank=True, default="")
    generated_pdf = models.FileField(upload_to="letters/", blank=True, null=True)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_letter_requests",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("user", "conference")]

    def __str__(self) -> str:
        return f"{self.passport_name} — {self.conference} ({self.get_status_display()})"

    def transition_to(self, new_status: str) -> None:
        """Transition this request to a new workflow status.

        Validates that the transition is allowed before applying it.

        Args:
            new_status: The target status value (one of ``Status`` choices).

        Raises:
            ValueError: If the transition from the current status to
                ``new_status`` is not permitted.
        """
        allowed = self.ALLOWED_TRANSITIONS.get(str(self.status), set())
        if new_status not in allowed:
            msg = (
                f"Cannot transition from '{self.get_status_display()}' to '{new_status}'. Allowed: {allowed or 'none'}"
            )
            raise ValueError(msg)
        self.status = new_status
