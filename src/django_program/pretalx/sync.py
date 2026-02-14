"""Synchronization service for importing Pretalx data into Django models.

Provides :class:`PretalxSyncService` which orchestrates the import of speakers,
talks, and schedule slots from a Pretalx event into the corresponding Django
models.  Each sync method is idempotent and uses bulk operations for
performance.
"""

import logging
import zoneinfo
from datetime import datetime
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Max, Min
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.text import slugify

from django_program.pretalx.models import Room, ScheduleSlot, Speaker, SubmissionTypeDefault, Talk
from django_program.pretalx.profiles import resolve_pretalx_profile
from django_program.programs.models import Activity
from django_program.settings import get_config
from pretalx_client.adapters.normalization import localized as _localized
from pretalx_client.client import PretalxClient

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django.contrib.auth.models import AbstractBaseUser
    from django.db.models import QuerySet

    from django_program.conference.models import Conference

logger = logging.getLogger(__name__)

_PROGRESS_CHUNK = 10

# Maps Pretalx submission_type names (case-insensitive) to ActivityType values.
_SUBMISSION_TYPE_TO_ACTIVITY: dict[str, str] = {
    "tutorial": Activity.ActivityType.TUTORIAL,
    "workshop": Activity.ActivityType.WORKSHOP,
    "lightning talk": Activity.ActivityType.LIGHTNING_TALK,
    "sprint": Activity.ActivityType.SPRINT,
    "summit": Activity.ActivityType.SUMMIT,
    "open space": Activity.ActivityType.OPEN_SPACE,
}


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
        self._schedule_delete_guard_enabled = config.pretalx.schedule_delete_guard_enabled
        self._schedule_delete_guard_min_existing_slots = config.pretalx.schedule_delete_guard_min_existing_slots
        self._schedule_delete_guard_max_fraction_removed = float(
            config.pretalx.schedule_delete_guard_max_fraction_removed
        )

        self._rooms: dict[int, Room] | None = None
        self._room_names: dict[int, str] | None = None
        self._submission_types: dict[int, str] | None = None
        self._tracks: dict[int, str] | None = None
        self._tags: dict[int, str] | None = None
        self.profile = resolve_pretalx_profile(
            event_slug=conference.pretalx_event_slug,
            conference_slug=conference.slug,
        )

    def _ensure_mappings(self) -> None:
        """Pre-fetch room, submission type, and track ID-to-name mappings.

        Fetches each mapping once and caches it on the instance so that
        subsequent sync methods can resolve integer IDs from the real Pretalx
        API into human-readable names.  Safe to call multiple times; only
        fetches on the first call.
        """
        if self._rooms is None:
            logger.debug("Fetching room mappings for %s", self.conference.slug)
            self._rooms = {
                room.pretalx_id: room
                for room in Room.objects.filter(conference=self.conference)
                if room.pretalx_id is not None
            }
            self._room_names = {pid: str(room.name) for pid, room in self._rooms.items()}
        if self._submission_types is None:
            logger.debug("Fetching submission type mappings for %s", self.conference.slug)
            self._submission_types = self.client.fetch_submission_types()
        if self._tracks is None:
            logger.debug("Fetching track mappings for %s", self.conference.slug)
            self._tracks = self.client.fetch_tracks()
        if self._tags is None:
            logger.debug("Fetching tag mappings for %s", self.conference.slug)
            try:
                self._tags = self.client.fetch_tags()
            except RuntimeError:
                logger.warning(
                    "Could not fetch tag mappings for %s; continuing without tags",
                    self.conference.slug,
                )
                self._tags = {}

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
            tags=self._tags,
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
                "track": self.profile.sync_track(api_talk),
                "tags": self.profile.sync_tags(api_talk),
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
                    "tags",
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

        self._sync_activities_from_talks(now)

        yield {"count": count}

    def _sync_activities_from_talks(self, now: datetime) -> None:
        """Auto-create or update Activities for Pretalx submission types.

        For each unique ``submission_type`` on synced talks that maps to a
        known :class:`~django_program.programs.models.Activity.ActivityType`,
        creates or updates an Activity linked to that submission type.  Also
        populates the ``talks`` M2M with matching talks and enriches the
        activity with scheduling data derived from those talks.
        """
        sub_types = (
            Talk.objects.filter(conference=self.conference)
            .exclude(submission_type="")
            .values_list("submission_type", flat=True)
            .distinct()
        )

        for sub_type in sub_types:
            activity_type = _SUBMISSION_TYPE_TO_ACTIVITY.get(sub_type.lower())
            if activity_type is None:
                continue

            base_slug = slugify(sub_type) or "activity"

            matching_talks = Talk.objects.filter(
                conference=self.conference,
                submission_type=sub_type,
            )

            enrichment = self._build_activity_enrichment(matching_talks)

            activity, created = Activity.objects.update_or_create(
                conference=self.conference,
                pretalx_submission_type=sub_type,
                defaults={
                    "name": f"{sub_type}s",
                    "activity_type": activity_type,
                    "synced_at": now,
                    **enrichment,
                },
            )
            if created:
                activity.slug = self._unique_activity_slug(base_slug)
                activity.save(update_fields=["slug"])

            activity.talks.set(matching_talks)

            verb = "Created" if created else "Updated"
            logger.info(
                "%s activity '%s' for submission type '%s' (%d talks)",
                verb,
                activity.name,
                sub_type,
                matching_talks.count(),
            )

    def _build_activity_enrichment(self, talks: QuerySet[Talk]) -> dict[str, object]:
        """Derive activity metadata from a set of linked talks.

        Computes a description summary, earliest/latest times, and a
        shared room (if all talks are in the same room).

        Args:
            talks: QuerySet of Talk instances linked to this activity.

        Returns:
            A dict of field names to values suitable for Activity defaults.
        """
        enrichment: dict[str, object] = {}

        talk_count = talks.count()
        if talk_count == 0:
            return enrichment

        rooms = talks.exclude(room__isnull=True).order_by().values_list("room__name", flat=True).distinct()
        room_names = list(rooms)
        room_count = len(room_names)

        if room_count == 1:
            enrichment["description"] = f"{talk_count} talk{'s' if talk_count != 1 else ''} in {room_names[0]}"
        elif room_count > 1:
            enrichment["description"] = f"{talk_count} talk{'s' if talk_count != 1 else ''} across {room_count} rooms"
        else:
            enrichment["description"] = f"{talk_count} talk{'s' if talk_count != 1 else ''}"

        agg = talks.exclude(slot_start__isnull=True).aggregate(
            earliest=Min("slot_start"),
            latest=Max("slot_end"),
        )
        if agg["earliest"]:
            enrichment["start_time"] = agg["earliest"]
        if agg["latest"]:
            enrichment["end_time"] = agg["latest"]

        if room_count == 1:
            shared_room = talks.exclude(room__isnull=True).first()
            if shared_room:
                enrichment["room"] = shared_room.room

        return enrichment

    def _unique_activity_slug(self, base: str) -> str:
        """Generate a unique Activity slug within this conference."""
        candidate = base
        counter = 1
        while Activity.objects.filter(conference=self.conference, slug=candidate).exists():
            counter += 1
            candidate = f"{base}-{counter}"
        return candidate

    def _check_schedule_deletion_safety(
        self,
        *,
        existing_count: int,
        stale_count: int,
        allow_large_deletions: bool,
    ) -> None:
        """Raise when schedule deletion volume looks anomalous.

        The guard is intended to prevent accidental local schedule wipes when
        Pretalx returns an unexpectedly small/empty payload.
        """
        if allow_large_deletions or not self._schedule_delete_guard_enabled:
            return
        if existing_count < self._schedule_delete_guard_min_existing_slots:
            return
        if existing_count <= 0 or stale_count <= 0:
            return

        removed_fraction = stale_count / existing_count
        if removed_fraction < self._schedule_delete_guard_max_fraction_removed:
            return

        msg = (
            "Aborting schedule sync: would remove "
            f"{stale_count}/{existing_count} existing slots ({removed_fraction:.1%}), "
            "which exceeds the configured safety threshold. "
            "Retry with allow_large_deletions=True only if this is intentional."
        )
        raise RuntimeError(msg)

    def sync_schedule(self, *, allow_large_deletions: bool = False) -> tuple[int, int]:
        """Fetch schedule slots from Pretalx and upsert into the database.

        Slots that no longer appear in the Pretalx schedule are deleted
        after the sync completes.

        Args:
            allow_large_deletions: When ``True``, bypasses the schedule-drop
                safety guard and permits large stale-slot deletions.

        Returns:
            A tuple of ``(synced_count, unscheduled_count)`` where
            *unscheduled_count* is the number of talks that still have
            no scheduled slot after the sync.
        """
        with transaction.atomic():
            self._ensure_mappings()
            api_slots = self.client.fetch_schedule(rooms=self._room_names)
            existing_count = ScheduleSlot.objects.filter(conference=self.conference).count()
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
                        # Some schedule slots legitimately have no local Talk
                        # record (for example external events).
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

            stale_qs = ScheduleSlot.objects.filter(
                conference=self.conference,
            ).exclude(synced_at=now)
            stale_count = stale_qs.count()
            self._check_schedule_deletion_safety(
                existing_count=existing_count,
                stale_count=stale_count,
                allow_large_deletions=allow_large_deletions,
            )
            stale_count, _ = stale_qs.delete()
            if stale_count:
                logger.info("Removed %d stale schedule slots for %s", stale_count, self.conference.slug)

            logger.info("Synced %d schedule slots for %s", count, self.conference.slug)

            self._backfill_talks_from_schedule()

            unscheduled = Talk.objects.filter(
                conference=self.conference,
                slot_start__isnull=True,
            ).count()
            if unscheduled:
                logger.info("%d talks remain unscheduled for %s", unscheduled, self.conference.slug)

            return count, unscheduled

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

    def apply_type_defaults(self) -> int:
        """Apply SubmissionTypeDefault records to unscheduled talks.

        For each configured submission type default, finds talks of that type
        that have no room assigned and applies the default room and time slot.

        Returns:
            The number of talks that were modified by type defaults.
        """
        defaults = SubmissionTypeDefault.objects.filter(conference=self.conference).select_related("default_room")
        if not defaults.exists():
            return 0

        conf_tz = zoneinfo.ZoneInfo(str(self.conference.timezone))
        to_update: list[Talk] = []
        update_fields: set[str] = set()

        for type_default in defaults:
            talks = Talk.objects.filter(
                conference=self.conference,
                submission_type=type_default.submission_type,
                room__isnull=True,
            )

            for talk in talks:
                changed = False

                if type_default.default_room is not None:
                    talk.room = type_default.default_room
                    update_fields.add("room")
                    changed = True

                if type_default.default_date and type_default.default_start_time and talk.slot_start is None:
                    talk.slot_start = datetime.combine(
                        type_default.default_date,
                        type_default.default_start_time,
                        tzinfo=conf_tz,
                    )
                    update_fields.add("slot_start")
                    changed = True

                if type_default.default_date and type_default.default_end_time and talk.slot_end is None:
                    talk.slot_end = datetime.combine(
                        type_default.default_date,
                        type_default.default_end_time,
                        tzinfo=conf_tz,
                    )
                    update_fields.add("slot_end")
                    changed = True

                if changed:
                    to_update.append(talk)

        if to_update and update_fields:
            Talk.objects.bulk_update(to_update, fields=list(update_fields), batch_size=500)
            logger.info(
                "Applied type defaults to %d talks for %s",
                len(to_update),
                self.conference.slug,
            )
        return len(to_update)

    def sync_all(self, *, allow_large_deletions: bool = False) -> dict[str, int]:
        """Run all sync operations in dependency order.

        Returns:
            A mapping of entity type to the number synced.  The
            ``schedule_slots`` key contains only the synced count;
            ``unscheduled_talks`` is added when any talks lack a slot.
            ``type_defaults_applied`` is added when type defaults modify
            any talks.
        """
        schedule_count, unscheduled = self.sync_schedule(allow_large_deletions=allow_large_deletions)
        result: dict[str, int] = {
            "rooms": self.sync_rooms(),
            "speakers": self.sync_speakers(),
            "talks": self.sync_talks(),
            "schedule_slots": schedule_count,
        }
        if unscheduled:
            result["unscheduled_talks"] = unscheduled

        type_defaults_applied = self.apply_type_defaults()
        if type_defaults_applied:
            result["type_defaults_applied"] = type_defaults_applied

        return result


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
