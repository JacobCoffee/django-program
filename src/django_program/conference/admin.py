"""Django admin configuration for the conference app."""

from django import forms
from django.contrib import admin

from django_program.conference.models import Conference, FeatureFlags, Section

SECRET_PLACEHOLDER = "\u2022" * 12


class SecretInput(forms.PasswordInput):
    """Password widget that shows a placeholder instead of the real value.

    When a value already exists in the database the widget renders
    ``SECRET_PLACEHOLDER`` as the visible value so admins know a key is
    set, but the actual secret never appears in the HTML source. Submitting
    the placeholder (or an empty string) signals "keep existing value".
    """

    def format_value(self, value: str | None) -> str:
        """Return a dot placeholder when a value exists, empty string otherwise."""
        if value:
            return SECRET_PLACEHOLDER
        return ""


class SecretField(forms.CharField):
    """Char field that preserves the stored value when left unchanged.

    Works with ``SecretInput``: if the submitted value is empty or equals
    the placeholder, the field returns the original database value so
    secrets are never accidentally blanked.
    """

    widget = SecretInput

    def __init__(self, **kwargs: object) -> None:
        """Set sensible defaults for secret fields."""
        kwargs.setdefault("required", False)
        super().__init__(**kwargs)
        self.widget.attrs.setdefault("autocomplete", "off")

    def has_changed(self, initial: str | None, data: str | None) -> bool:
        """Treat placeholder or blank submissions as unchanged."""
        if not data or data == SECRET_PLACEHOLDER:
            return False
        return super().has_changed(initial, data)

    def clean(self, value: str | None) -> str | None:
        """Return the stored value when the field is left blank or unchanged."""
        if not value or value == SECRET_PLACEHOLDER:
            return self.initial
        return super().clean(value)


_STRIPE_FIELDS = ("stripe_secret_key", "stripe_publishable_key", "stripe_webhook_secret")


class ConferenceForm(forms.ModelForm):
    """Custom form that masks Stripe secret fields in the admin.

    Uses ``SecretField`` / ``SecretInput`` so decrypted values are never
    present in the rendered HTML. Admins see a dot placeholder when a
    value is set; leaving the field unchanged preserves the stored secret.
    """

    stripe_secret_key = SecretField()
    stripe_publishable_key = SecretField()
    stripe_webhook_secret = SecretField()

    class Meta:
        model = Conference
        exclude: list[str] = []


class SectionInline(admin.TabularInline):
    """Inline editor for conference sections.

    Allows adding and editing sections directly from the conference
    admin change form.
    """

    model = Section
    extra = 1
    prepopulated_fields = {"slug": ("name",)}
    fields = ("name", "slug", "start_date", "end_date", "order")


@admin.register(Conference)
class ConferenceAdmin(admin.ModelAdmin):
    """Admin interface for managing conferences.

    Groups fields into logical fieldsets: basic information, dates,
    third-party integrations (Pretalx and Stripe), and status metadata.
    Sections are editable inline via ``SectionInline``.
    """

    form = ConferenceForm
    list_display = ("name", "slug", "start_date", "end_date", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    inlines = (SectionInline,)

    fieldsets = (
        (
            None,
            {
                "fields": ("name", "slug", "venue", "address", "website_url"),
            },
        ),
        (
            "Dates",
            {
                "fields": ("start_date", "end_date", "timezone"),
            },
        ),
        (
            "Integrations",
            {
                "fields": (
                    "pretalx_event_slug",
                    "stripe_secret_key",
                    "stripe_publishable_key",
                    "stripe_webhook_secret",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Status",
            {
                "fields": ("is_active",),
            },
        ),
    )


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    """Admin interface for managing conference sections.

    Provides filtering by conference and search by name or slug.
    The slug field is auto-populated from the section name.
    """

    list_display = ("name", "conference", "start_date", "end_date", "order")
    list_filter = ("conference",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(FeatureFlags)
class FeatureFlagsAdmin(admin.ModelAdmin):
    """Admin interface for per-conference feature flag overrides.

    Allows toggling individual features on or off per conference.
    Leaving a field blank (``None``) uses the default from
    ``DJANGO_PROGRAM["features"]`` in settings.
    """

    list_display = (
        "conference",
        "registration_enabled",
        "sponsors_enabled",
        "travel_grants_enabled",
        "programs_enabled",
        "public_ui_enabled",
        "updated_at",
    )
    list_filter = ("conference",)
    fieldsets = (
        ("Conference", {"fields": ("conference",)}),
        (
            "Module Toggles",
            {
                "fields": (
                    "registration_enabled",
                    "sponsors_enabled",
                    "travel_grants_enabled",
                    "programs_enabled",
                    "pretalx_sync_enabled",
                ),
            },
        ),
        (
            "UI Toggles",
            {
                "fields": (
                    "public_ui_enabled",
                    "manage_ui_enabled",
                    "all_ui_enabled",
                ),
            },
        ),
    )
