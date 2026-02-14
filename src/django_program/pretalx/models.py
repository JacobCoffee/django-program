"""Speaker, Talk, Room, ScheduleSlot, and override models for Pretalx data."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
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

    @property
    def effective_name(self) -> str:
        """Return the overridden value if set, otherwise the synced value."""
        try:
            o = self.override
            if o.override_name:
                return o.override_name
        except RoomOverride.DoesNotExist:
            pass
        return self.name

    @property
    def effective_description(self) -> str:
        """Return the overridden value if set, otherwise the synced value."""
        try:
            o = self.override
            if o.override_description:
                return o.override_description
        except RoomOverride.DoesNotExist:
            pass
        return self.description

    @property
    def effective_capacity(self) -> int | None:
        """Return the overridden value if set, otherwise the synced value."""
        try:
            o = self.override
            if o.override_capacity is not None:
                return o.override_capacity
        except RoomOverride.DoesNotExist:
            pass
        return self.capacity


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

    @property
    def effective_name(self) -> str:
        """Return the overridden value if set, otherwise the synced value."""
        try:
            o = self.override
            if o.override_name:
                return o.override_name
        except SpeakerOverride.DoesNotExist:
            pass
        return self.name

    @property
    def effective_biography(self) -> str:
        """Return the overridden value if set, otherwise the synced value."""
        try:
            o = self.override
            if o.override_biography:
                return o.override_biography
        except SpeakerOverride.DoesNotExist:
            pass
        return self.biography

    @property
    def effective_avatar_url(self) -> str:
        """Return the overridden value if set, otherwise the synced value."""
        try:
            o = self.override
            if o.override_avatar_url:
                return o.override_avatar_url
        except SpeakerOverride.DoesNotExist:
            pass
        return self.avatar_url

    @property
    def effective_email(self) -> str:
        """Return the overridden value if set, otherwise the synced value."""
        try:
            o = self.override
            if o.override_email:
                return o.override_email
        except SpeakerOverride.DoesNotExist:
            pass
        return self.email


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

    @property
    def effective_title(self) -> str:
        """Return the overridden value if set, otherwise the synced value."""
        try:
            o = self.override
            if o.override_title:
                return o.override_title
        except TalkOverride.DoesNotExist:
            pass
        return self.title

    @property
    def effective_state(self) -> str:
        """Return the overridden value if set, otherwise the synced value."""
        try:
            o = self.override
            if o.is_cancelled:
                return "cancelled"
            if o.override_state:
                return o.override_state
        except TalkOverride.DoesNotExist:
            pass
        return self.state

    @property
    def effective_abstract(self) -> str:
        """Return the overridden value if set, otherwise the synced value."""
        try:
            o = self.override
            if o.override_abstract:
                return o.override_abstract
        except TalkOverride.DoesNotExist:
            pass
        return self.abstract

    @property
    def effective_room(self) -> Room | None:
        """Return the overridden value if set, otherwise the synced value."""
        try:
            o = self.override
            if o.override_room_id:
                return o.override_room
        except TalkOverride.DoesNotExist:
            pass
        return self.room

    @property
    def effective_slot_start(self) -> datetime | None:
        """Return the overridden value if set, otherwise the synced value."""
        try:
            o = self.override
            if o.override_slot_start is not None:
                return o.override_slot_start
        except TalkOverride.DoesNotExist:
            pass
        return self.slot_start

    @property
    def effective_slot_end(self) -> datetime | None:
        """Return the overridden value if set, otherwise the synced value."""
        try:
            o = self.override
            if o.override_slot_end is not None:
                return o.override_slot_end
        except TalkOverride.DoesNotExist:
            pass
        return self.slot_end


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


class AbstractOverride(models.Model):
    """Shared base for all override models.

    Provides common metadata fields (note, timestamps) and
    auto-set-from-parent logic.  Concrete subclasses define their own
    ``conference`` and ``created_by`` ForeignKeys with explicit related names.
    """

    note = models.TextField(
        blank=True,
        default="",
        help_text="Internal note explaining the reason for this override.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-updated_at"]

    # Subclasses must define ``_parent_field`` (e.g. "talk", "speaker").
    _parent_field: str = ""

    def save(self, *args: object, **kwargs: object) -> None:
        """Auto-set conference from the linked parent when not explicitly provided."""
        parent_id = getattr(self, f"{self._parent_field}_id", None)
        if parent_id and not self.conference_id:
            self.conference_id = self._get_parent_conference_id()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        """Validate that the linked parent belongs to the same conference."""
        super().clean()
        parent_id = getattr(self, f"{self._parent_field}_id", None)
        if parent_id and self.conference_id:
            parent_conf_id = self._get_parent_conference_id()
            if parent_conf_id is not None and parent_conf_id != self.conference_id:
                raise ValidationError(
                    {self._parent_field: f"The selected {self._parent_field} does not belong to this conference."},
                )

    def _get_parent_conference_id(self) -> int | None:
        """Look up the conference_id from the parent entity."""
        parent_id = getattr(self, f"{self._parent_field}_id", None)
        if parent_id is None:
            return None
        parent_model = type(self)._meta.get_field(self._parent_field).related_model  # noqa: SLF001
        return parent_model.objects.filter(pk=parent_id).values_list("conference_id", flat=True).first()


class TalkOverride(AbstractOverride):
    """Local override applied on top of synced Pretalx talk data.

    Allows conference organizers to patch individual fields of a synced talk
    without modifying the upstream Pretalx record.  Overrides are resolved
    at the view/template layer via ``effective_*`` properties on Talk.
    Fields left blank (or ``None``) are not applied, preserving the synced value.
    """

    _parent_field = "talk"

    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="talk_overrides",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_talk_overrides",
    )
    talk = models.OneToOneField(
        Talk,
        on_delete=models.CASCADE,
        related_name="override",
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

    def __str__(self) -> str:
        return f"Override for {self.talk}"

    @property
    def is_empty(self) -> bool:
        """Return True when no override fields carry a value.

        An override with only a note (but no actual field overrides) is
        considered empty and should be cleaned up.
        """
        return (
            not self.override_room_id
            and not self.override_title
            and not self.override_state
            and self.override_slot_start is None
            and self.override_slot_end is None
            and not self.override_abstract
            and not self.is_cancelled
        )


class SpeakerOverride(AbstractOverride):
    """Local override applied on top of synced Pretalx speaker data.

    Allows conference organizers to patch individual fields of a synced speaker
    without modifying the upstream Pretalx record.
    """

    _parent_field = "speaker"

    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="speaker_overrides",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_speaker_overrides",
    )
    speaker = models.OneToOneField(
        Speaker,
        on_delete=models.CASCADE,
        related_name="override",
    )
    override_name = models.CharField(
        max_length=300,
        blank=True,
        default="",
        help_text="Override the speaker's display name.",
    )
    override_biography = models.TextField(
        blank=True,
        default="",
        help_text="Override the speaker biography.",
    )
    override_avatar_url = models.URLField(
        blank=True,
        default="",
        help_text="Override the speaker avatar URL.",
    )
    override_email = models.EmailField(
        blank=True,
        default="",
        help_text="Override the speaker contact email.",
    )

    def __str__(self) -> str:
        return f"Override for {self.speaker}"

    @property
    def is_empty(self) -> bool:
        """Return True when no override fields carry a value."""
        return (
            not self.override_name
            and not self.override_biography
            and not self.override_avatar_url
            and not self.override_email
        )


class RoomOverride(AbstractOverride):
    """Local override applied on top of synced Pretalx room data.

    Allows conference organizers to patch individual fields of a synced room
    without modifying the upstream Pretalx record.
    """

    _parent_field = "room"

    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="room_overrides",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_room_overrides",
    )
    room = models.OneToOneField(
        Room,
        on_delete=models.CASCADE,
        related_name="override",
    )
    override_name = models.CharField(
        max_length=300,
        blank=True,
        default="",
        help_text="Override the room name.",
    )
    override_description = models.TextField(
        blank=True,
        default="",
        help_text="Override the room description.",
    )
    override_capacity = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Override the room capacity.",
    )

    def __str__(self) -> str:
        return f"Override for {self.room}"

    @property
    def is_empty(self) -> bool:
        """Return True when no override fields carry a value."""
        return not self.override_name and not self.override_description and self.override_capacity is None


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
