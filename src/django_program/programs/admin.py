"""Django admin configuration for the programs app."""

from django.contrib import admin

from django_program.programs.models import Activity, ActivitySignup, TravelGrant


class ActivitySignupInline(admin.TabularInline):
    """Inline editor for activity signups within the activity admin."""

    model = ActivitySignup
    extra = 0
    fields = ("user", "note", "created_at")
    readonly_fields = ("created_at",)


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    """Admin interface for managing activities."""

    list_display = ("name", "conference", "activity_type", "start_time", "max_participants", "is_active")
    list_filter = ("conference", "activity_type", "is_active")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    inlines = (ActivitySignupInline,)


@admin.register(TravelGrant)
class TravelGrantAdmin(admin.ModelAdmin):
    """Admin interface for managing travel grant applications."""

    list_display = ("user", "conference", "status", "requested_amount", "approved_amount", "travel_from")
    list_filter = ("conference", "status")
    search_fields = ("user__username", "user__email", "travel_from")
    list_editable = ("status",)
    readonly_fields = ("created_at", "updated_at")
