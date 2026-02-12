"""Activity, signup, and travel grant models for django-program."""

from django.conf import settings
from django.db import models


class Activity(models.Model):
    """A conference activity such as a sprint, workshop, or social event.

    Represents a scheduled or unscheduled activity that attendees can
    sign up for.  The ``max_participants`` field caps signups when set,
    and ``spots_remaining`` computes the live availability.
    """

    class ActivityType(models.TextChoices):
        """Classification of conference activities."""

        SPRINT = "sprint", "Sprint"
        WORKSHOP = "workshop", "Workshop"
        TUTORIAL = "tutorial", "Tutorial"
        LIGHTNING_TALK = "lightning_talk", "Lightning Talk"
        SOCIAL = "social", "Social Event"
        OPEN_SPACE = "open_space", "Open Space"
        OTHER = "other", "Other"

    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="activities",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    activity_type = models.CharField(
        max_length=20,
        choices=ActivityType.choices,
        default=ActivityType.OTHER,
    )
    description = models.TextField(blank=True, default="")
    location = models.CharField(max_length=200, blank=True, default="")
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    max_participants = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Leave blank for unlimited.",
    )
    requires_ticket = models.BooleanField(
        default=False,
        help_text="Whether a conference ticket is required to sign up.",
    )
    external_url = models.URLField(
        blank=True,
        default="",
        help_text="External link for more details.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_time", "name"]
        unique_together = [("conference", "slug")]

    def __str__(self) -> str:
        return str(self.name)

    @property
    def spots_remaining(self) -> int | None:
        """Return the number of remaining spots, or None if unlimited."""
        if self.max_participants is None:
            return None
        return max(0, self.max_participants - self.signups.count())


class ActivitySignup(models.Model):
    """A user's signup for an activity.

    Each user may sign up for a given activity at most once, enforced
    by the ``unique_together`` constraint.
    """

    activity = models.ForeignKey(
        Activity,
        on_delete=models.CASCADE,
        related_name="signups",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="activity_signups",
    )
    note = models.TextField(
        blank=True,
        default="",
        help_text="Optional note from the attendee.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("activity", "user")]

    def __str__(self) -> str:
        return f"{self.user} - {self.activity.name}"


class TravelGrant(models.Model):
    """A travel grant application for a conference.

    Tracks a financial assistance request from an attendee, including
    the amount requested, origin city, and reviewer decision.
    """

    class GrantStatus(models.TextChoices):
        """Lifecycle states for a travel grant application."""

        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="travel_grants",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="travel_grants",
    )
    status = models.CharField(
        max_length=20,
        choices=GrantStatus.choices,
        default=GrantStatus.PENDING,
    )
    requested_amount = models.DecimalField(max_digits=10, decimal_places=2)
    approved_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    travel_from = models.CharField(
        max_length=200,
        help_text="City or region the applicant is traveling from.",
    )
    reason = models.TextField(help_text="Why the applicant needs a travel grant.")
    reviewer_notes = models.TextField(blank=True, default="")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_grants",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("conference", "user")]

    def __str__(self) -> str:
        return f"Travel grant: {self.user} ({self.status})"
