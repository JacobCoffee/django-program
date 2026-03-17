"""Badge models for generating attendee badges with QR codes.

Provides a configurable badge template system and a model for tracking
generated badge files (PDF or PNG) per attendee.
"""

from django.db import models


class BadgeTemplate(models.Model):
    """Configurable badge layout template for a conference.

    Defines dimensions, visible fields, color scheme, and optional logo
    for generating attendee badges. Each conference can have multiple
    templates but only one may be marked as the default.
    """

    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="badge_templates",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    is_default = models.BooleanField(default=False)

    # Layout config
    width_mm = models.PositiveIntegerField(
        default=86,
        help_text="Badge width in millimeters.",
    )
    height_mm = models.PositiveIntegerField(
        default=54,
        help_text="Badge height in millimeters.",
    )

    # What to show
    show_name = models.BooleanField(default=True)
    show_email = models.BooleanField(default=False)
    show_company = models.BooleanField(default=False)
    show_ticket_type = models.BooleanField(default=True)
    show_qr_code = models.BooleanField(default=True)
    show_conference_name = models.BooleanField(default=True)

    # Styling
    background_color = models.CharField(max_length=7, default="#FFFFFF")
    text_color = models.CharField(max_length=7, default="#000000")
    accent_color = models.CharField(max_length=7, default="#4338CA")

    # Logo
    logo = models.ImageField(upload_to="badges/logos/", blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("conference", "slug")]
        constraints = [
            models.UniqueConstraint(
                fields=["conference"],
                condition=models.Q(is_default=True),
                name="registration_badgetemplate_one_default_per_conference",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.conference.slug})"


class Badge(models.Model):
    """A generated badge for a specific attendee.

    Tracks the generated file, format, and timestamp so badges can be
    cached and regenerated on demand.
    """

    class Format(models.TextChoices):
        """Supported badge output formats."""

        PDF = "pdf", "PDF"
        PNG = "png", "PNG"

    attendee = models.ForeignKey(
        "program_registration.Attendee",
        on_delete=models.CASCADE,
        related_name="badges",
    )
    template = models.ForeignKey(
        BadgeTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="badges",
    )
    format = models.CharField(
        max_length=10,
        choices=Format.choices,
        default=Format.PDF,
    )
    file = models.FileField(upload_to="badges/generated/", blank=True, default="")
    generated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Badge for {self.attendee} ({self.format})"
