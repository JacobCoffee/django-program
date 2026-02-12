"""Conference and Section models for django-program."""

from django.db import models
from encrypted_fields import EncryptedCharField


class Conference(models.Model):
    """A conference event with dates, venue, and integration settings.

    The central model that all other apps reference. Stores Pretalx and Stripe
    configuration so each conference can be managed independently.
    """

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    start_date = models.DateField()
    end_date = models.DateField()
    timezone = models.CharField(max_length=100, default="UTC")
    venue = models.CharField(max_length=300, blank=True, default="")
    address = models.CharField(max_length=500, blank=True, default="")
    website_url = models.URLField(blank=True, default="")

    pretalx_event_slug = models.CharField(max_length=200, blank=True, default="")

    stripe_secret_key = EncryptedCharField(max_length=200, blank=True, null=True, default=None)
    stripe_publishable_key = EncryptedCharField(max_length=200, blank=True, null=True, default=None)
    stripe_webhook_secret = EncryptedCharField(max_length=200, blank=True, null=True, default=None)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date"]

    def __str__(self) -> str:
        return self.name


class Section(models.Model):
    """A distinct segment of a conference (e.g. Tutorials, Talks, Sprints).

    Sections divide a conference into logical time blocks, each with their own
    date range. They are ordered by the ``order`` field for display purposes.
    """

    conference = models.ForeignKey(
        Conference,
        on_delete=models.CASCADE,
        related_name="sections",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    start_date = models.DateField()
    end_date = models.DateField()
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "start_date"]
        unique_together = [("conference", "slug")]

    def __str__(self) -> str:
        return f"{self.name} ({self.conference.slug})"
