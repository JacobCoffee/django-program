"""Sponsor level, sponsor, and benefit models for django-program."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify

from django_program.pretalx.models import AbstractOverride


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
    slug = models.SlugField(max_length=200, blank=True)
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

    def save(self, *args: object, **kwargs: object) -> None:
        """Auto-generate slug from name if not set."""
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


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
    slug = models.SlugField(max_length=200, blank=True)
    external_id = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="External identifier from the PSF sponsorship API.",
    )
    website_url = models.URLField(blank=True, default="")
    logo = models.ImageField(upload_to="sponsors/logos/", blank=True, default="")
    logo_url = models.URLField(
        blank=True,
        default="",
        help_text="Remote logo URL from the PSF sponsorship API.",
    )
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

    def save(self, *args: object, **kwargs: object) -> None:
        """Auto-generate slug from name if not set."""
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def clean(self) -> None:
        """Validate that the sponsor's level belongs to the same conference."""
        if self.level_id and self.conference_id and self.level.conference_id != self.conference_id:
            msg = "Sponsor level must belong to the same conference as the sponsor."
            raise ValidationError({"level": msg})

    @property
    def effective_name(self) -> str:
        """Return the overridden value if set, otherwise the synced value."""
        try:
            o = self.override
            if o.override_name:
                return o.override_name
        except SponsorOverride.DoesNotExist:
            pass
        return self.name

    @property
    def effective_description(self) -> str:
        """Return the overridden value if set, otherwise the synced value."""
        try:
            o = self.override
            if o.override_description:
                return o.override_description
        except SponsorOverride.DoesNotExist:
            pass
        return self.description

    @property
    def effective_website_url(self) -> str:
        """Return the overridden value if set, otherwise the synced value."""
        try:
            o = self.override
            if o.override_website_url:
                return o.override_website_url
        except SponsorOverride.DoesNotExist:
            pass
        return self.website_url

    @property
    def effective_logo_url(self) -> str:
        """Return the overridden value if set, otherwise the synced value."""
        try:
            o = self.override
            if o.override_logo_url:
                return o.override_logo_url
        except SponsorOverride.DoesNotExist:
            pass
        return self.logo_url

    @property
    def effective_contact_name(self) -> str:
        """Return the overridden value if set, otherwise the synced value."""
        try:
            o = self.override
            if o.override_contact_name:
                return o.override_contact_name
        except SponsorOverride.DoesNotExist:
            pass
        return self.contact_name

    @property
    def effective_contact_email(self) -> str:
        """Return the overridden value if set, otherwise the synced value."""
        try:
            o = self.override
            if o.override_contact_email:
                return o.override_contact_email
        except SponsorOverride.DoesNotExist:
            pass
        return self.contact_email

    @property
    def effective_is_active(self) -> bool:
        """Return the overridden value if set, otherwise the synced value."""
        try:
            o = self.override
            if o.override_is_active is not None:
                return o.override_is_active
        except SponsorOverride.DoesNotExist:
            pass
        return self.is_active

    @property
    def effective_level(self) -> SponsorLevel:
        """Return the overridden value if set, otherwise the synced value."""
        try:
            o = self.override
            if o.override_level_id:
                return o.override_level
        except SponsorOverride.DoesNotExist:
            pass
        return self.level


class SponsorOverride(AbstractOverride):
    """Local override applied on top of sponsor data.

    Allows conference organizers to patch individual fields of a sponsor
    without modifying the original record.  Inherits ``save()``/``clean()``
    conference auto-set and validation from ``AbstractOverride``.
    """

    _parent_field = "sponsor"

    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="sponsor_overrides",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_sponsor_overrides",
    )
    sponsor = models.OneToOneField(
        Sponsor,
        on_delete=models.CASCADE,
        related_name="override",
    )
    override_name = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Override the sponsor name.",
    )
    override_description = models.TextField(
        blank=True,
        default="",
        help_text="Override the sponsor description.",
    )
    override_website_url = models.URLField(
        blank=True,
        default="",
        help_text="Override the sponsor website URL.",
    )
    override_logo_url = models.URLField(
        blank=True,
        default="",
        help_text="Override the sponsor logo URL.",
    )
    override_contact_name = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Override the sponsor contact name.",
    )
    override_contact_email = models.EmailField(
        blank=True,
        default="",
        help_text="Override the sponsor contact email.",
    )
    override_is_active = models.BooleanField(
        null=True,
        blank=True,
        default=None,
        help_text="Override the sponsor active status. Leave blank for no override.",
    )
    override_level = models.ForeignKey(
        SponsorLevel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sponsor_overrides",
        help_text="Override the sponsor level.",
    )

    def __str__(self) -> str:
        return f"Override for {self.sponsor}"

    @property
    def is_empty(self) -> bool:
        """Return True when no override fields carry a value."""
        return (
            not self.override_name
            and not self.override_description
            and not self.override_website_url
            and not self.override_logo_url
            and not self.override_contact_name
            and not self.override_contact_email
            and self.override_is_active is None
            and not self.override_level_id
        )


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
