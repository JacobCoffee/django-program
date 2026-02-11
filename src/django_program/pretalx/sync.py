"""Synchronization service for importing Pretalx data into Django models.

Provides :class:`PretalxSyncService` which orchestrates the import of speakers,
talks, and schedule slots from a Pretalx event into the corresponding Django
models.  Each sync method is idempotent and uses bulk operations for
performance.
"""

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.db.models.functions import Lower
from django.utils import timezone

from django_program.pretalx.models import Room, ScheduleSlot, Speaker, Talk
from django_program.settings import get_config
from pretalx_client.adapters.normalization import localized as _localized
from pretalx_client.client import PretalxClient

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django.contrib.auth.models import AbstractBaseUser

    from django_program.conference.models import Conference

logger = logging.getLogger(__name__)

_PROGRESS_CHUNK = 50


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
            self._room_names = {pid: str(room.name) for pid, room in self._rooms.items()}
        if self._submission_types is None:
            logger.debug("Fetching submission type mappings for %s", self.conference.slug)
            self._submission_types = self.client.fetch_submission_types()
        if self._tracks is None:
            logger.debug("Fetching track mappings for %s", self.conference.slug)
            self._tracks = self.client.fetch_tracks()

    def sync_rooms(self) -> int:
        """Fetch rooms from Pretalx and upsert into the database.

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

        Uses bulk operations for performance and delegates to
        :meth:`sync_speakers_iter` which yields progress dicts.

        Returns:
            The number of speakers synced.
        """
        count = 0
        for progress in self.sync_speakers_iter():
            if "count" in progress:
                count = progress["count"]
        return count

    def sync_speakers_iter(self) -> Iterator[dict[str, int | str]]:
        """Bulk sync speakers from Pretalx, yielding progress updates.

        Yields:
            A ``{"phase": "fetching"}`` dict before the API call,
            dicts with ``current``/``total`` keys during processing,
            and a final dict with ``count`` when complete.
        """
        yield {"phase": "fetching"}
        api_speakers = self.client.fetch_speakers()
        total = len(api_speakers)
        if total == 0:
            yield {"count": 0}
            return

        now = timezone.now()
        yield {"current": 0, "total": total}

        existing = {s.pretalx_code: s for s in Speaker.objects.filter(conference=self.conference)}

        emails = {s.email.lower() for s in api_speakers if s.email}
        user_model: type[AbstractBaseUser] = get_user_model()  # type: ignore[assignment]
        users_by_email: dict[str, object] = {}
        if emails:
            for u in user_model.objects.annotate(
                email_lower=Lower("email"),
            ).filter(email_lower__in=emails):
                users_by_email[u.email_lower] = u

        to_create: list[Speaker] = []
        to_update: list[Speaker] = []

        for i, api_speaker in enumerate(api_speakers):
            target = to_update if api_speaker.code in existing else to_create
            target.append(
                _build_speaker(api_speaker, self.conference, existing, users_by_email, now),
            )
            if (i + 1) % _PROGRESS_CHUNK == 0 or (i + 1) == total:
                yield {"current": i + 1, "total": total}

        if to_create:
            Speaker.objects.bulk_create(to_create, batch_size=500)
        if to_update:
            Speaker.objects.bulk_update(
                to_update,
                fields=["name", "biography", "avatar_url", "email", "synced_at", "user"],
                batch_size=500,
            )

        count = len(to_create) + len(to_update)
        logger.info(
            "Synced %d speakers (%d new, %d updated) for %s",
            count,
            len(to_create),
            len(to_update),
            self.conference.slug,
        )
        yield {"count": count}

    def sync_talks(self) -> int:
        """Fetch talks from Pretalx and upsert into the database.

        Uses bulk operations for performance and delegates to
        :meth:`sync_talks_iter` which yields progress dicts.

        Returns:
            The number of talks synced.
        """
        count = 0
        for progress in self.sync_talks_iter():
            if "count" in progress:
                count = progress["count"]
        return count

    def _bulk_set_talk_speakers(self, m2m_map: dict[str, list[int]]) -> None:
        """Replace M2M speaker relationships for synced talks in bulk.

        Clears all existing speaker associations for the synced talks, then
        re-creates only the relationships present in *m2m_map*.  Talks with
        empty speaker lists will have their associations cleared.

        Args:
            m2m_map: Mapping of talk pretalx_code to lists of speaker PKs.
        """
        synced_codes = set(m2m_map.keys())
        synced_talk_pks = dict(
            Talk.objects.filter(
                conference=self.conference,
                pretalx_code__in=synced_codes,
            ).values_list("pretalx_code", "pk")
        )
        TalkSpeaker = Talk.speakers.through  # noqa: N806
        TalkSpeaker.objects.filter(
            talk_id__in=synced_talk_pks.values(),
        ).delete()
        through_entries = []
        for talk_code, spk_pks in m2m_map.items():
            talk_pk = synced_talk_pks.get(talk_code)
            if talk_pk:
                through_entries.extend(TalkSpeaker(talk_id=talk_pk, speaker_id=spk_pk) for spk_pk in spk_pks)
        if through_entries:
            TalkSpeaker.objects.bulk_create(
                through_entries,
                ignore_conflicts=True,
                batch_size=500,
            )

    def sync_talks_iter(self) -> Iterator[dict[str, int | str]]:
        """Bulk sync talks from Pretalx, yielding progress updates.

        Yields:
            A ``{"phase": "fetching"}`` dict before the API call,
            dicts with ``current``/``total`` keys during processing,
            and a final dict with ``count`` when complete.
        """
        self._ensure_mappings()
        yield {"phase": "fetching"}
        api_talks = self.client.fetch_talks(
            submission_types=self._submission_types,
            tracks=self._tracks,
            rooms=self._room_names,
        )
        total = len(api_talks)
        if total == 0:
            yield {"count": 0}
            return

        now = timezone.now()
        yield {"current": 0, "total": total}

        existing = {t.pretalx_code: t for t in Talk.objects.filter(conference=self.conference)}
        speaker_pk_map = {s.pretalx_code: s.pk for s in Speaker.objects.filter(conference=self.conference)}

        to_create: list[Talk] = []
        to_update: list[Talk] = []
        m2m_map: dict[str, list[int]] = {}

        for i, api_talk in enumerate(api_talks):
            room = self._resolve_room(api_talk.room)
            fields = {
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
            }

            if api_talk.code in existing:
                talk = existing[api_talk.code]
                for k, v in fields.items():
                    setattr(talk, k, v)
                to_update.append(talk)
            else:
                to_create.append(
                    Talk(
                        conference=self.conference,
                        pretalx_code=api_talk.code,
                        **fields,
                    )
                )

            m2m_map[api_talk.code] = [speaker_pk_map[code] for code in api_talk.speaker_codes if code in speaker_pk_map]

            if (i + 1) % _PROGRESS_CHUNK == 0 or (i + 1) == total:
                yield {"current": i + 1, "total": total}

        if to_create:
            Talk.objects.bulk_create(to_create, batch_size=500)
        if to_update:
            Talk.objects.bulk_update(
                to_update,
                fields=[
                    "title",
                    "abstract",
                    "description",
                    "submission_type",
                    "track",
                    "duration",
                    "state",
                    "room",
                    "slot_start",
                    "slot_end",
                    "synced_at",
                ],
                batch_size=500,
            )

        self._bulk_set_talk_speakers(m2m_map)

        count = len(to_create) + len(to_update)
        logger.info(
            "Synced %d talks (%d new, %d updated) for %s",
            count,
            len(to_create),
            len(to_update),
            self.conference.slug,
        )
        yield {"count": count}

    def sync_schedule(self) -> int:
        """Fetch schedule slots from Pretalx and upsert into the database.

        Slots that no longer appear in the Pretalx schedule are deleted
        after the sync completes.

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

        self._backfill_talks_from_schedule()

        return count

    def _backfill_talks_from_schedule(self) -> None:
        """Populate talk room/slot fields from linked schedule slots.

        When talks are synced from the ``/submissions/`` fallback endpoint,
        room and slot times are absent.  This method fills them from the
        schedule slots that reference each talk.
        """
        slots = ScheduleSlot.objects.filter(conference=self.conference, talk__isnull=False).select_related(
            "talk", "room"
        )
        to_update: list[Talk] = []
        for slot in slots:
            talk = slot.talk
            changed = False
            if talk.room_id != slot.room_id:
                talk.room = slot.room
                changed = True
            if talk.slot_start != slot.start:
                talk.slot_start = slot.start
                changed = True
            if talk.slot_end != slot.end:
                talk.slot_end = slot.end
                changed = True
            if changed:
                to_update.append(talk)
        if to_update:
            Talk.objects.bulk_update(to_update, fields=["room", "slot_start", "slot_end"], batch_size=500)
            logger.info("Back-filled room/slot data for %d talks from schedule", len(to_update))

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

        Returns:
            A mapping of entity type to the number synced.
        """
        return {
            "rooms": self.sync_rooms(),
            "speakers": self.sync_speakers(),
            "talks": self.sync_talks(),
            "schedule_slots": self.sync_schedule(),
        }


def _build_speaker(
    api_speaker: object,
    conference: Conference,
    existing: dict[str, Speaker],
    users_by_email: dict[str, object],
    now: datetime,
) -> Speaker:
    """Build or update a Speaker instance from an API speaker DTO."""
    if api_speaker.code in existing:
        speaker = existing[api_speaker.code]
        speaker.name = api_speaker.name
        speaker.biography = api_speaker.biography
        speaker.avatar_url = api_speaker.avatar_url
        speaker.email = api_speaker.email
        speaker.synced_at = now
        if api_speaker.email and speaker.user is None:
            matched = users_by_email.get(api_speaker.email.lower())
            if matched:
                speaker.user = matched
        return speaker

    user = users_by_email.get(api_speaker.email.lower()) if api_speaker.email else None
    return Speaker(
        conference=conference,
        pretalx_code=api_speaker.code,
        name=api_speaker.name,
        biography=api_speaker.biography,
        avatar_url=api_speaker.avatar_url,
        email=api_speaker.email,
        synced_at=now,
        user=user,
    )


def _parse_iso_datetime(value: str) -> datetime | None:
    """Parse an ISO 8601 string into a datetime, returning ``None`` on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):  # fmt: skip
        return None


def _classify_slot(title: str, code: str) -> str:
    """Determine the slot type from a Pretalx slot's title and code."""
    if code:
        return ScheduleSlot.SlotType.TALK

    lower_title = title.lower()
    if "break" in lower_title or "lunch" in lower_title:
        return ScheduleSlot.SlotType.BREAK
    if "social" in lower_title or "party" in lower_title:
        return ScheduleSlot.SlotType.SOCIAL
    return ScheduleSlot.SlotType.OTHER
