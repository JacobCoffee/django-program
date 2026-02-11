"""Synchronization service for importing Pretalx data into Django models.

Provides :class:`PretalxSyncService` which orchestrates the import of speakers,
talks, and schedule slots from a Pretalx event into the corresponding Django
models.  Each sync method is idempotent and uses ``update_or_create`` so it can
be run repeatedly without producing duplicates.
"""

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.utils import timezone

from django_program.pretalx.client import PretalxClient, _localized
from django_program.pretalx.models import Room, ScheduleSlot, Speaker, Talk
from django_program.settings import get_config

if TYPE_CHECKING:
    from django_program.conference.models import Conference

logger = logging.getLogger(__name__)

User = get_user_model()


class PretalxSyncService:
    """Synchronizes speaker, talk, and schedule data from Pretalx to Django models.

    Builds a :class:`~django_program.pretalx.client.PretalxClient` from the
    conference's ``pretalx_event_slug`` and the global Pretalx configuration,
    then provides methods to sync each entity type individually or all at once.

    Args:
        conference: The conference whose Pretalx data should be synced.

    Raises:
        ValueError: If the conference has no ``pretalx_event_slug`` configured.
    """

    def __init__(self, conference: Conference) -> None:
        """Initialize the sync service for the given conference.

        Args:
            conference: The conference whose Pretalx data should be synced.

        Raises:
            ValueError: If the conference has no ``pretalx_event_slug`` configured.
        """
        if not conference.pretalx_event_slug:
            msg = f"Conference '{conference.slug}' has no pretalx_event_slug configured"
            raise ValueError(msg)

        self.conference = conference
        config = get_config()
        base_url = config.pretalx.base_url
        api_token = config.pretalx.token or ""
        self.client = PretalxClient(
            conference.pretalx_event_slug,
            base_url=base_url,
            api_token=api_token,
        )

        self._rooms: dict[int, Room] | None = None
        self._room_names: dict[int, str] | None = None
        self._submission_types: dict[int, str] | None = None
        self._tracks: dict[int, str] | None = None

    def _ensure_mappings(self) -> None:
        """Pre-fetch room, submission type, and track ID-to-name mappings.

        Fetches each mapping once and caches it on the instance so that
        subsequent sync methods can resolve integer IDs from the real Pretalx
        API into human-readable names.  Safe to call multiple times; only
        fetches on the first call.
        """
        if self._rooms is None:
            logger.debug("Fetching room mappings for %s", self.conference.slug)
            self._rooms = {room.pretalx_id: room for room in Room.objects.filter(conference=self.conference)}
            self._room_names = {pid: room.name for pid, room in self._rooms.items()}
        if self._submission_types is None:
            logger.debug("Fetching submission type mappings for %s", self.conference.slug)
            self._submission_types = self.client.fetch_submission_types()
        if self._tracks is None:
            logger.debug("Fetching track mappings for %s", self.conference.slug)
            self._tracks = self.client.fetch_tracks()

    def sync_rooms(self) -> int:
        """Fetch rooms from Pretalx and upsert into the database.

        Populates the :class:`~django_program.pretalx.models.Room` table with
        full room metadata including name, description, capacity, and position.
        After syncing, refreshes the in-memory room cache so that subsequent
        talk and schedule syncs can resolve room FKs.

        Returns:
            The number of rooms synced.
        """
        api_rooms = self.client.fetch_rooms_full()
        now = timezone.now()
        count = 0

        for raw_room in api_rooms:
            room_id = raw_room.get("id")
            if room_id is None:
                continue

            name = _localized(raw_room.get("name"))
            description = _localized(raw_room.get("description"))
            capacity = raw_room.get("capacity")
            position = raw_room.get("position")

            Room.objects.update_or_create(
                conference=self.conference,
                pretalx_id=int(room_id),
                defaults={
                    "name": name,
                    "description": description,
                    "capacity": capacity,
                    "position": position,
                    "synced_at": now,
                },
            )
            count += 1

        logger.info("Synced %d rooms for %s", count, self.conference.slug)

        self._rooms = None
        self._room_names = None
        self._ensure_mappings()

        return count

    def sync_speakers(self) -> int:
        """Fetch speakers from Pretalx and upsert into the database.

        For each speaker, attempts to link the ``user`` field to a Django user
        by case-insensitive email match.  The user link is only set when a match
        is found and the field is currently ``None``.

        Returns:
            The number of speakers synced.
        """
        api_speakers = self.client.fetch_speakers()
        now = timezone.now()
        count = 0

        for api_speaker in api_speakers:
            speaker, created = Speaker.objects.update_or_create(
                conference=self.conference,
                pretalx_code=api_speaker.code,
                defaults={
                    "name": api_speaker.name,
                    "biography": api_speaker.biography,
                    "avatar_url": api_speaker.avatar_url,
                    "email": api_speaker.email,
                    "synced_at": now,
                },
            )

            if api_speaker.email and speaker.user is None:
                try:
                    matched_user = User.objects.get(email__iexact=api_speaker.email)
                    speaker.user = matched_user
                    speaker.save(update_fields=["user"])
                except User.DoesNotExist:
                    pass

            action = "Created" if created else "Updated"
            logger.debug("%s speaker %s (%s)", action, speaker.name, speaker.pretalx_code)
            count += 1

        logger.info("Synced %d speakers for %s", count, self.conference.slug)
        return count

    def sync_talks(self) -> int:
        """Fetch talks from Pretalx and upsert into the database.

        Pre-fetches ID-to-name mappings for submission types, tracks, and
        rooms so that integer IDs from the real API are resolved to display
        names.  After upserting each talk, sets its speakers M2M from the
        Pretalx speaker codes.  ISO 8601 datetime strings for slot start/end
        are parsed with ``datetime.fromisoformat``.

        Returns:
            The number of talks synced.
        """
        self._ensure_mappings()
        api_talks = self.client.fetch_talks(
            submission_types=self._submission_types,
            tracks=self._tracks,
            rooms=self._room_names,
        )
        now = timezone.now()
        count = 0

        for api_talk in api_talks:
            room = self._resolve_room(api_talk.room)

            talk, created = Talk.objects.update_or_create(
                conference=self.conference,
                pretalx_code=api_talk.code,
                defaults={
                    "title": api_talk.title,
                    "abstract": api_talk.abstract,
                    "description": api_talk.description,
                    "submission_type": api_talk.submission_type,
                    "track": api_talk.track,
                    "duration": api_talk.duration,
                    "state": api_talk.state,
                    "room": room,
                    "slot_start": _parse_iso_datetime(api_talk.slot_start),
                    "slot_end": _parse_iso_datetime(api_talk.slot_end),
                    "synced_at": now,
                },
            )

            speakers = (
                Speaker.objects.filter(
                    conference=self.conference,
                    pretalx_code__in=api_talk.speaker_codes,
                )
                if api_talk.speaker_codes
                else Speaker.objects.none()
            )
            talk.speakers.set(speakers)

            action = "Created" if created else "Updated"
            logger.debug("%s talk %s (%s)", action, talk.title, talk.pretalx_code)
            count += 1

        logger.info("Synced %d talks for %s", count, self.conference.slug)
        return count

    def sync_schedule(self) -> int:
        """Fetch schedule slots from Pretalx and upsert into the database.

        Pre-fetches room mappings so that integer room IDs from the real API
        are resolved to display names.  Talk-linked slots use the talk's title
        and ``SlotType.TALK``.  Non-talk slots are classified by title
        heuristics: titles containing "break" or "lunch" become ``BREAK``,
        "social" or "party" become ``SOCIAL``, and everything else becomes
        ``OTHER``.

        Slots that no longer appear in the Pretalx schedule (e.g. because a
        slot was rescheduled to a different time or room) are deleted after the
        sync completes.

        Returns:
            The number of schedule slots synced.
        """
        self._ensure_mappings()
        api_slots = self.client.fetch_schedule(rooms=self._room_names)
        now = timezone.now()
        count = 0

        for api_slot in api_slots:
            talk = None
            slot_type = _classify_slot(api_slot.title, api_slot.code)
            title = api_slot.title

            if api_slot.code:
                try:
                    talk = Talk.objects.get(
                        conference=self.conference,
                        pretalx_code=api_slot.code,
                    )
                    title = title or talk.title
                except Talk.DoesNotExist:
                    pass

            start_dt = api_slot.start_dt or _parse_iso_datetime(api_slot.start)
            end_dt = api_slot.end_dt or _parse_iso_datetime(api_slot.end)

            if start_dt is None or end_dt is None:
                logger.warning("Skipping slot with unparsable times: %s", api_slot)
                continue

            room = self._resolve_room(api_slot.room)

            ScheduleSlot.objects.update_or_create(
                conference=self.conference,
                start=start_dt,
                room=room,
                defaults={
                    "talk": talk,
                    "title": title,
                    "end": end_dt,
                    "slot_type": slot_type,
                    "synced_at": now,
                },
            )

            logger.debug("Synced slot %s at %s in %s", title, start_dt, api_slot.room)
            count += 1

        stale_count, _ = (
            ScheduleSlot.objects.filter(
                conference=self.conference,
            )
            .exclude(synced_at=now)
            .delete()
        )
        if stale_count:
            logger.info("Removed %d stale schedule slots for %s", stale_count, self.conference.slug)

        logger.info("Synced %d schedule slots for %s", count, self.conference.slug)
        return count

    def _resolve_room(self, room_name: str) -> Room | None:
        """Look up a Room instance by its display name.

        Args:
            room_name: The room display name as resolved from the Pretalx API.

        Returns:
            The matching ``Room`` instance, or ``None`` if the name is empty
            or no match is found.
        """
        if not room_name or self._rooms is None:
            return None
        for room in self._rooms.values():
            if room.name == room_name:
                return room
        return None

    def sync_all(self) -> dict[str, int]:
        """Run all sync operations in dependency order.

        Syncs rooms first (talks and slots reference them), then speakers
        (talks reference them), then talks (schedule slots reference them),
        then schedule slots.

        Returns:
            A mapping of entity type to the number synced.
        """
        return {
            "rooms": self.sync_rooms(),
            "speakers": self.sync_speakers(),
            "talks": self.sync_talks(),
            "schedule_slots": self.sync_schedule(),
        }


def _parse_iso_datetime(value: str) -> datetime | None:
    """Parse an ISO 8601 string into a datetime, returning ``None`` on failure.

    Args:
        value: An ISO 8601 formatted datetime string.

    Returns:
        A ``datetime`` instance, or ``None`` if the string is empty or invalid.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):  # fmt: skip
        return None


def _classify_slot(title: str, code: str) -> str:
    """Determine the slot type from a Pretalx slot's title and code.

    Args:
        title: The display title of the slot.
        code: The submission code, non-empty when the slot holds a talk.

    Returns:
        A :class:`~django_program.pretalx.models.ScheduleSlot.SlotType` value.
    """
    if code:
        return ScheduleSlot.SlotType.TALK

    lower_title = title.lower()
    if "break" in lower_title or "lunch" in lower_title:
        return ScheduleSlot.SlotType.BREAK
    if "social" in lower_title or "party" in lower_title:
        return ScheduleSlot.SlotType.SOCIAL
    return ScheduleSlot.SlotType.OTHER
