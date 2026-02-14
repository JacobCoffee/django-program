"""Django admin configuration for the pretalx integration app."""

from django.contrib import admin

from django_program.pretalx.models import (
    Room,
    RoomOverride,
    ScheduleSlot,
    Speaker,
    SpeakerOverride,
    SubmissionTypeDefault,
    Talk,
    TalkOverride,
)


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    """Admin interface for managing rooms synced from Pretalx."""

    list_display = ("name", "conference", "capacity", "position", "pretalx_id", "synced_at")
    list_filter = ("conference",)
    search_fields = ("name",)
    readonly_fields = ("pretalx_id", "synced_at", "created_at", "updated_at")


@admin.register(Speaker)
class SpeakerAdmin(admin.ModelAdmin):
    """Admin interface for managing speakers synced from Pretalx."""

    list_display = ("name", "conference", "pretalx_code", "email", "user", "synced_at")
    list_filter = ("conference",)
    search_fields = ("name", "pretalx_code", "email")
    raw_id_fields = ("user",)
    readonly_fields = ("pretalx_code", "synced_at", "created_at", "updated_at")


@admin.register(Talk)
class TalkAdmin(admin.ModelAdmin):
    """Admin interface for managing talks synced from Pretalx."""

    list_display = ("title", "conference", "submission_type", "track", "state", "room", "slot_start")
    list_filter = ("conference", "submission_type", "track", "state")
    search_fields = ("title", "pretalx_code", "abstract")
    raw_id_fields = ("room",)
    filter_horizontal = ("speakers",)
    readonly_fields = ("pretalx_code", "synced_at", "created_at", "updated_at")


@admin.register(ScheduleSlot)
class ScheduleSlotAdmin(admin.ModelAdmin):
    """Admin interface for managing schedule slots."""

    list_display = ("display_title", "conference", "room", "start", "end", "slot_type")
    list_filter = ("conference", "slot_type")
    search_fields = ("title",)
    raw_id_fields = ("talk", "room")
    readonly_fields = ("synced_at", "created_at", "updated_at")

    @admin.display(description="Title")
    def display_title(self, obj: ScheduleSlot) -> str:
        """Return the talk title when linked, otherwise the slot title."""
        return obj.display_title


@admin.register(TalkOverride)
class TalkOverrideAdmin(admin.ModelAdmin):
    """Admin interface for managing talk overrides."""

    list_display = ("talk", "conference", "override_room", "override_state", "is_cancelled", "updated_at")
    list_filter = ("conference", "is_cancelled")
    search_fields = ("talk__title", "note")
    raw_id_fields = ("talk", "override_room", "created_by")
    readonly_fields = ("created_at", "updated_at")


@admin.register(SpeakerOverride)
class SpeakerOverrideAdmin(admin.ModelAdmin):
    """Admin interface for managing speaker overrides."""

    list_display = ("speaker", "conference", "override_name", "override_email", "updated_at")
    list_filter = ("conference",)
    search_fields = ("speaker__name", "override_name", "note")
    raw_id_fields = ("speaker", "created_by")
    readonly_fields = ("created_at", "updated_at")


@admin.register(RoomOverride)
class RoomOverrideAdmin(admin.ModelAdmin):
    """Admin interface for managing room overrides."""

    list_display = ("room", "conference", "override_name", "override_capacity", "updated_at")
    list_filter = ("conference",)
    search_fields = ("room__name", "override_name", "note")
    raw_id_fields = ("room", "created_by")
    readonly_fields = ("created_at", "updated_at")


@admin.register(SubmissionTypeDefault)
class SubmissionTypeDefaultAdmin(admin.ModelAdmin):
    """Admin interface for submission type defaults."""

    list_display = (
        "submission_type",
        "conference",
        "default_room",
        "default_date",
        "default_start_time",
        "default_end_time",
    )
    list_filter = ("conference",)
    search_fields = ("submission_type",)
    raw_id_fields = ("default_room",)
