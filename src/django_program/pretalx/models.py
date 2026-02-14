"""Speaker, Talk, Room, ScheduleSlot, and override models for Pretalx data."""

from django.conf import settings
from django.db import models


class Room(models.Model):
    """A room or venue space, either synced from Pretalx or created manually.

    Rooms synced from Pretalx are uniquely identified per conference by their
    Pretalx integer ID.  Manually created rooms have ``pretalx_id=None``.
    """

    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="rooms",
    )
    pretalx_id = models.PositiveIntegerField(null=True, blank=True)
    name = models.CharField(max_length=300)
    description = models.TextField(blank=True, default="")
    capacity = models.PositiveIntegerField(null=True, blank=True)
    position = models.PositiveIntegerField(null=True, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["conference", "pretalx_id"],
                condition=~models.Q(pretalx_id=None),
                name="unique_room_pretalx_id_per_conference",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Speaker(models.Model):
    """A speaker profile synced from the Pretalx API.

    Each speaker is uniquely identified per conference by their Pretalx speaker
    code. The optional ``user`` link allows associating a speaker record with a
    registered Django user for profile and permissions purposes.
    """

    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="speakers",
    )
    pretalx_code = models.CharField(max_length=100)
    name = models.CharField(max_length=300)
    biography = models.TextField(blank=True, default="")
    avatar_url = models.URLField(blank=True, default="")
    email = models.EmailField(blank=True, default="")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="speaker_profiles",
    )
    synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("conference", "pretalx_code")]

    def __str__(self) -> str:
        return self.name


class Talk(models.Model):
    """A talk submission synced from the Pretalx API.

    Represents a conference submission (talk, tutorial, workshop, etc.) with its
    scheduling details. Speakers are linked via a many-to-many relationship since
    a talk can have multiple presenters.
    """

    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="talks",
    )
    pretalx_code = models.CharField(max_length=100)
    title = models.CharField(max_length=500)
    abstract = models.TextField(blank=True, default="")
    description = models.TextField(blank=True, default="")
    submission_type = models.CharField(max_length=200, blank=True, default="")
    track = models.CharField(max_length=200, blank=True, default="")
    tags = models.JSONField(blank=True, default=list)
    duration = models.PositiveIntegerField(null=True, blank=True)
    state = models.CharField(max_length=50, blank=True, default="")
    speakers = models.ManyToManyField(
        Speaker,
        related_name="talks",
        blank=True,
    )
    room = models.ForeignKey(
        Room,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="talks",
    )
    slot_start = models.DateTimeField(null=True, blank=True)
    slot_end = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["slot_start", "title"]
        unique_together = [("conference", "pretalx_code")]

    def __str__(self) -> str:
        return self.title


class ScheduleSlot(models.Model):
    """A time slot in the conference schedule.

    Represents both talk slots and non-talk blocks (breaks, lunch, social
    events). When linked to a ``Talk``, the slot inherits the talk's title
    for display; otherwise the slot's own ``title`` field is used.
    """

    class SlotType(models.TextChoices):
        """The kind of activity occupying a schedule slot."""

        TALK = "talk", "Talk"
        BREAK = "break", "Break"
        SOCIAL = "social", "Social"
        OTHER = "other", "Other"

    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="schedule_slots",
    )
    talk = models.ForeignKey(
        Talk,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="schedule_slots",
    )
    title = models.CharField(max_length=500, blank=True, default="")
    room = models.ForeignKey(
        Room,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="schedule_slots",
    )
    start = models.DateTimeField()
    end = models.DateTimeField()
    slot_type = models.CharField(
        max_length=50,
        choices=SlotType.choices,
    )
    synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start", "room"]
        constraints = [
            models.UniqueConstraint(
                fields=["conference", "start", "room"],
                name="uniq_schedule_slot_conference_start_room",
            ),
        ]

    def __str__(self) -> str:
        return self.display_title

    @property
    def display_title(self) -> str:
        """Return the talk title when linked to a talk, otherwise the slot title."""
        if self.talk:
            return self.talk.title
        return self.title


class TalkOverride(models.Model):
    """Local override applied on top of synced Pretalx talk data.

    Allows conference organizers to patch individual fields of a synced talk
    without modifying the upstream Pretalx record.  Overrides are applied
    after each sync to ensure local corrections persist.  Fields left blank
    (or ``None``) are not applied, preserving the synced value.
    """

    talk = models.OneToOneField(
        Talk,
        on_delete=models.CASCADE,
        related_name="override",
    )
    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="talk_overrides",
    )
    override_room = models.ForeignKey(
        Room,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="talk_overrides",
        help_text="Override the room assignment for this talk.",
    )
    override_title = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Override the talk title.",
    )
    override_state = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Override the talk state (e.g. confirmed, withdrawn).",
    )
    override_slot_start = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Override the scheduled start time.",
    )
    override_slot_end = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Override the scheduled end time.",
    )
    override_abstract = models.TextField(
        blank=True,
        default="",
        help_text="Override the talk abstract.",
    )
    is_cancelled = models.BooleanField(
        default=False,
        help_text="Mark this talk as cancelled. Overrides the state to 'cancelled'.",
    )
    note = models.TextField(
        blank=True,
        default="",
        help_text="Internal note explaining the reason for this override.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_talk_overrides",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"Override for {self.talk}"

    def apply(self) -> list[str]:
        """Apply non-empty override fields onto the linked talk.

        Returns:
            A list of field names that were changed on the talk.
        """
        talk: Talk = self.talk  # type: ignore[assignment]
        changed: list[str] = []

        if self.is_cancelled:
            if talk.state != "cancelled":
                talk.state = "cancelled"  # type: ignore[assignment]
                changed.append("state")
        elif self.override_state and talk.state != self.override_state:
            talk.state = self.override_state  # type: ignore[assignment]
            changed.append("state")

        if self.override_title and talk.title != self.override_title:
            talk.title = self.override_title  # type: ignore[assignment]
            changed.append("title")

        if self.override_abstract and talk.abstract != self.override_abstract:
            talk.abstract = self.override_abstract  # type: ignore[assignment]
            changed.append("abstract")

        if self.override_room is not None and talk.room_id != self.override_room_id:
            talk.room = self.override_room  # type: ignore[assignment]
            changed.append("room")

        if self.override_slot_start is not None and talk.slot_start != self.override_slot_start:
            talk.slot_start = self.override_slot_start  # type: ignore[assignment]
            changed.append("slot_start")

        if self.override_slot_end is not None and talk.slot_end != self.override_slot_end:
            talk.slot_end = self.override_slot_end  # type: ignore[assignment]
            changed.append("slot_end")

        return changed


class SubmissionTypeDefault(models.Model):
    """Default room and time-slot assignment for a Pretalx submission type.

    When talks of a given ``submission_type`` (e.g. "Poster") have no room or
    schedule assigned by Pretalx, these defaults are applied automatically
    after each sync.
    """

    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="submission_type_defaults",
    )
    submission_type = models.CharField(
        max_length=200,
        help_text="The Pretalx submission type name to match (e.g. 'Poster', 'Tutorial').",
    )
    default_room = models.ForeignKey(
        Room,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submission_type_defaults",
        help_text="Default room for talks of this type.",
    )
    default_date = models.DateField(
        null=True,
        blank=True,
        help_text="Default date for talks of this type.",
    )
    default_start_time = models.TimeField(
        null=True,
        blank=True,
        help_text="Default start time for talks of this type.",
    )
    default_end_time = models.TimeField(
        null=True,
        blank=True,
        help_text="Default end time for talks of this type.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["submission_type"]
        unique_together = [("conference", "submission_type")]

    def __str__(self) -> str:
        return f"Defaults for '{self.submission_type}'"
