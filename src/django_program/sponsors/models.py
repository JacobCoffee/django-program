"""Sponsor level, sponsor, and benefit models for django-program."""

from django.db import models


class SponsorLevel(models.Model):
    """A sponsorship tier for a conference.

    Defines a named tier (e.g. "Gold", "Silver", "Bronze") with pricing,
    a description of included benefits, and the number of complimentary
    tickets that sponsors at this level receive automatically.
    """

    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="sponsor_levels",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    cost = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True, default="")
    benefits_summary = models.TextField(
        blank=True,
        default="",
        help_text="Plain text summary of benefits for this level.",
    )
    comp_ticket_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of complimentary tickets to auto-generate for sponsors at this level.",
    )
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "name"]
        unique_together = [("conference", "slug")]

    def __str__(self) -> str:
        return f"{self.name} ({self.conference.slug})"


class Sponsor(models.Model):
    """A sponsoring organization for a conference.

    Represents a company or organization that has purchased a sponsorship
    package. Each sponsor belongs to a single level and conference, with
    contact details and branding assets for the conference website.
    """

    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="sponsors",
    )
    level = models.ForeignKey(
        SponsorLevel,
        on_delete=models.CASCADE,
        related_name="sponsors",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    website_url = models.URLField(blank=True, default="")
    logo = models.ImageField(upload_to="sponsors/logos/", blank=True, default="")
    description = models.TextField(blank=True, default="")
    contact_name = models.CharField(max_length=200, blank=True, default="")
    contact_email = models.EmailField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["level__order", "name"]
        unique_together = [("conference", "slug")]

    def __str__(self) -> str:
        return f"{self.name} ({self.level.name})"


class SponsorBenefit(models.Model):
    """A specific benefit tracked for a sponsor.

    Tracks individual deliverables owed to a sponsor as part of their
    sponsorship package (e.g. "Logo on website", "Booth space"). The
    ``is_complete`` flag marks whether the benefit has been fulfilled.
    """

    sponsor = models.ForeignKey(
        Sponsor,
        on_delete=models.CASCADE,
        related_name="benefits",
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    is_complete = models.BooleanField(default=False)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} - {self.sponsor.name}"
