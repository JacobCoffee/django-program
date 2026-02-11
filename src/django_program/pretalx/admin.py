"""Django admin configuration for the pretalx integration app."""

from django.contrib import admin

from django_program.pretalx.models import Room, ScheduleSlot, Speaker, Talk


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    """Admin interface for managing rooms synced from Pretalx."""

    list_display = ("name", "conference", "capacity", "position", "pretalx_id", "synced_at")
    list_filter = ("conference",)
    search_fields = ("name",)
    readonly_fields = ("pretalx_id", "synced_at", "created_at", "updated_at")


@admin.register(Speaker)
class SpeakerAdmin(admin.ModelAdmin):
    """Admin interface for managing speakers synced from Pretalx.

    Speaker records are primarily created and updated by the Pretalx sync
    process. The ``pretalx_code`` and sync timestamps are read-only to
    prevent accidental edits that would break the sync link.
    """

    list_display = ("name", "conference", "pretalx_code", "email", "user", "synced_at")
    list_filter = ("conference",)
    search_fields = ("name", "pretalx_code", "email")
    raw_id_fields = ("user",)
    readonly_fields = ("pretalx_code", "synced_at", "created_at", "updated_at")


@admin.register(Talk)
class TalkAdmin(admin.ModelAdmin):
    """Admin interface for managing talks synced from Pretalx.

    Talks are synced from the Pretalx submissions API. Filtering by submission
    type, track, and state allows quick navigation of large schedules.
    """

    list_display = ("title", "conference", "submission_type", "track", "state", "room", "slot_start")
    list_filter = ("conference", "submission_type", "track", "state")
    search_fields = ("title", "pretalx_code", "abstract")
    raw_id_fields = ("room",)
    filter_horizontal = ("speakers",)
    readonly_fields = ("pretalx_code", "synced_at", "created_at", "updated_at")


@admin.register(ScheduleSlot)
class ScheduleSlotAdmin(admin.ModelAdmin):
    """Admin interface for managing schedule slots.

    Slots represent the full conference timetable including talks, breaks,
    and social events. The ``display_title`` column shows the linked talk
    title when available, falling back to the slot's own title.
    """

    list_display = ("display_title", "conference", "room", "start", "end", "slot_type")
    list_filter = ("conference", "slot_type")
    search_fields = ("title",)
    raw_id_fields = ("talk", "room")
    readonly_fields = ("synced_at", "created_at", "updated_at")

    @admin.display(description="Title")
    def display_title(self, obj: ScheduleSlot) -> str:
        """Return the talk title when linked, otherwise the slot title."""
        return obj.display_title
