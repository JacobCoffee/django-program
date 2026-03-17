"""Attendee profile models for conference registration.

Provides an abstract base for projects that need custom attendee profile fields,
and a concrete ``Attendee`` model that links users to conferences with check-in
tracking and access codes.
"""

import secrets
import string

from django.conf import settings
from django.db import models


def generate_access_code() -> str:
    """Generate an 8-character uppercase alphanumeric access code.

    Returns:
        A random string of 8 uppercase letters and digits.
    """
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


class AttendeeProfileBase(models.Model):
    """Abstract base for attendee profiles.

    Projects extend this with custom fields (e.g. dietary restrictions,
    t-shirt size) by subclassing and pointing ``DJANGO_PROGRAM.attendee_profile_model``
    at the concrete subclass.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="%(class)s",
    )
    access_code = models.CharField(max_length=20, unique=True, editable=False)
    completed_registration = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def save(self, *args: object, **kwargs: object) -> None:
        """Auto-generate access code on first save if not already set."""
        if not self.access_code:
            self.access_code = generate_access_code()
        super().save(*args, **kwargs)


class Attendee(models.Model):
    """Links a user to a conference with registration state and check-in tracking."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="attendees",
    )
    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="attendees",
    )
    order = models.OneToOneField(
        "program_registration.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendee",
    )
    access_code = models.CharField(max_length=20, unique=True, editable=False)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    completed_registration = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "conference")]

    def __str__(self) -> str:
        return f"{self.user} @ {self.conference}"

    def save(self, *args: object, **kwargs: object) -> None:
        """Auto-generate access code on first save if not already set."""
        if not self.access_code:
            self.access_code = generate_access_code()
        super().save(*args, **kwargs)
