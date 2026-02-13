"""Speaker, Talk, Room, and ScheduleSlot models synced from Pretalx."""

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
