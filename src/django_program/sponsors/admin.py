"""Django admin configuration for the sponsors app."""

from django.contrib import admin

from django_program.sponsors.models import Sponsor, SponsorBenefit, SponsorLevel, SponsorOverride


class SponsorBenefitInline(admin.TabularInline):
    """Inline editor for sponsor benefits within the sponsor admin."""

    model = SponsorBenefit
    extra = 1
    fields = ("name", "description", "is_complete", "notes")


@admin.register(SponsorLevel)
class SponsorLevelAdmin(admin.ModelAdmin):
    """Admin interface for managing sponsor levels."""

    list_display = ("name", "conference", "cost", "comp_ticket_count", "order")
    list_filter = ("conference",)
    search_fields = ("name", "slug")


@admin.register(Sponsor)
class SponsorAdmin(admin.ModelAdmin):
    """Admin interface for managing sponsors with inline benefits."""

    list_display = ("name", "conference", "level", "is_active")
    list_filter = ("conference", "level", "is_active")
    search_fields = ("name", "slug", "contact_name", "contact_email")
    inlines = (SponsorBenefitInline,)


@admin.register(SponsorOverride)
class SponsorOverrideAdmin(admin.ModelAdmin):
    """Admin interface for managing sponsor overrides."""

    list_display = ("sponsor", "conference", "override_name", "override_is_active", "updated_at")
    list_filter = ("conference",)
    search_fields = ("sponsor__name", "override_name", "note")
    raw_id_fields = ("sponsor", "override_level", "created_by")
    readonly_fields = ("created_at", "updated_at")
