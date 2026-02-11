"""Django admin configuration for the conference app."""

from django import forms
from django.contrib import admin

from django_program.conference.models import Conference, Section


class ConferenceForm(forms.ModelForm):
    """Custom form that masks Stripe secret fields in the admin.

    Uses ``PasswordInput`` widgets so values are never displayed in the
    browser. Setting ``render_value=True`` lets admins see that a value
    is present (as dots) without exposing the plaintext.
    """

    class Meta:
        model = Conference
        exclude: list[str] = []
        widgets = {
            "stripe_secret_key": forms.PasswordInput(attrs={"autocomplete": "off"}, render_value=True),
            "stripe_publishable_key": forms.PasswordInput(attrs={"autocomplete": "off"}, render_value=True),
            "stripe_webhook_secret": forms.PasswordInput(attrs={"autocomplete": "off"}, render_value=True),
        }


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
                "fields": ("name", "slug", "venue", "website_url"),
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
