"""Typed dataclasses for Pretalx API response data.

Provides :class:`PretalxSpeaker`, :class:`PretalxTalk`, and :class:`PretalxSlot`
as frozen dataclasses that parse raw API dicts into well-typed Python objects.
Each ``from_api()`` classmethod validates the raw dict through the corresponding
OpenAPI-generated dataclass before adapting it into the consumer-friendly shape.

The normalization helpers live in :mod:`pretalx_client.adapters.normalization`
and the datetime/slot helpers in :mod:`pretalx_client.adapters.schedule`.  This
module re-exports the underscore-prefixed aliases for backward compatibility.
"""

import dataclasses as _dc
import enum
import logging
from dataclasses import dataclass, field
from datetime import datetime  # noqa: TC003 -- used at runtime by dataclass fields
from typing import Any

from pretalx_client.adapters.normalization import (
    localized,
    resolve_id_or_localized,
)
from pretalx_client.adapters.schedule import normalize_slot, parse_datetime
from pretalx_client.generated import (
    GeneratedSpeaker,
    GeneratedSpeakerOrga,
    GeneratedSubmission,
    GeneratedTalkSlot,
    StateEnum,
)

logger = logging.getLogger(__name__)

# Backward-compatible aliases -- existing consumers import these underscore
# names from ``pretalx_client.models``.  Keep them available here.
_localized = localized
_resolve_id_or_localized = resolve_id_or_localized
_parse_datetime = parse_datetime


def _parse_generated[T](cls: type[T], data: dict[str, Any]) -> T | None:
    """Construct a generated dataclass from a raw API dict.

    Filters the input dict to only fields declared by the target dataclass,
    then attempts construction.  Returns ``None`` on failure so callers can
    fall back to manual dict parsing for API shape variations not captured
    by the OpenAPI schema.

    Args:
        cls: The generated dataclass type to construct.
        data: Raw API response dict.

    Returns:
        An instance of *cls*, or ``None`` if construction fails.
    """
    try:
        field_names = {f.name for f in _dc.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in field_names}
        return cls(**filtered)
    except TypeError, ValueError, KeyError:
        logger.debug("Failed to parse %s from API dict, using fallback", cls.__name__)
        return None


class SubmissionState(enum.StrEnum):
    """Pretalx submission lifecycle states.

    Values are sourced from the OpenAPI-generated :class:`StateEnum` where
    available, with ``DELETED`` added for states observed in practice but
    absent from the published schema.
    """

    SUBMITTED = StateEnum.submitted
    ACCEPTED = StateEnum.accepted
    REJECTED = StateEnum.rejected
    CONFIRMED = StateEnum.confirmed
    WITHDRAWN = StateEnum.withdrawn
    CANCELED = StateEnum.canceled
    DRAFT = StateEnum.draft
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class PretalxSpeaker:
    """A speaker record from the Pretalx API.

    Attributes:
        code: Unique alphanumeric speaker identifier in Pretalx.
        name: Speaker's display name.
        biography: Markdown-formatted biography text.
        avatar_url: URL to the speaker's avatar image.
        email: Speaker's email (only available with authenticated API access).
        submissions: List of submission codes this speaker is associated with.
    """

    code: str
    name: str
    biography: str = ""
    avatar_url: str = ""
    email: str = ""
    submissions: list[str] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> PretalxSpeaker:
        """Construct a ``PretalxSpeaker`` from a raw Pretalx API dict.

        Parses through the generated ``Speaker`` or ``SpeakerOrga`` model
        for field validation, then adapts into the consumer-friendly shape.
        Falls back to direct dict extraction when the generated model
        cannot handle the API response (e.g. ``avatar`` vs ``avatar_url``).

        Args:
            data: A single speaker object from the Pretalx speakers endpoint.

        Returns:
            A populated ``PretalxSpeaker`` instance.
        """
        # Avatar key varies across Pretalx instances; generated model only
        # knows about avatar_url, so we resolve this before parsing.
        avatar = data.get("avatar_url") or data.get("avatar") or ""

        if "email" in data and data.get("email") is not None:
            raw = _parse_generated(GeneratedSpeakerOrga, data)
            if raw is not None:
                return cls(
                    code=raw.code,
                    name=raw.name,
                    biography=raw.biography or "",
                    avatar_url=avatar,
                    email=raw.email,
                    submissions=list(raw.submissions),
                )
        else:
            raw = _parse_generated(GeneratedSpeaker, data)
            if raw is not None:
                return cls(
                    code=raw.code,
                    name=raw.name,
                    biography=raw.biography or "",
                    avatar_url=avatar,
                    email="",
                    submissions=list(raw.submissions),
                )

        return cls(
            code=data.get("code", ""),
            name=data.get("name", ""),
            biography=data.get("biography") or "",
            avatar_url=avatar,
            email=data.get("email") or "",
            submissions=data.get("submissions") or [],
        )


@dataclass(frozen=True, slots=True)
class PretalxTalk:
    """A talk or submission record from the Pretalx API.

    Attributes:
        code: Unique alphanumeric submission identifier.
        title: Talk title.
        abstract: Short summary.
        description: Full description.
        submission_type: Resolved display name of the submission type.
        track: Resolved display name of the track.
        duration: Duration in minutes.
        state: Submission lifecycle state.
        speaker_codes: List of speaker codes linked to this talk.
        room: Resolved display name of the scheduled room.
        slot_start: Scheduled start time (ISO 8601).
        slot_end: Scheduled end time (ISO 8601).
    """

    code: str
    title: str
    abstract: str = ""
    description: str = ""
    submission_type: str = ""
    track: str = ""
    duration: int | None = None
    state: str = ""
    speaker_codes: list[str] = field(default_factory=list)
    room: str = ""
    slot_start: str = ""
    slot_end: str = ""

    @classmethod
    def from_api(
        cls,
        data: dict[str, Any],
        *,
        submission_types: dict[int, str] | None = None,
        tracks: dict[int, str] | None = None,
        rooms: dict[int, str] | None = None,
    ) -> PretalxTalk:
        """Construct a ``PretalxTalk`` from a raw Pretalx API dict.

        Parses through the generated ``Submission`` model for field
        validation, then resolves integer IDs to display names via the
        adapter layer.  Falls back to direct dict extraction when the
        generated model cannot handle the API response shape.

        Args:
            data: A single submission or talk object from the Pretalx API.
            submission_types: Optional ``{id: name}`` mapping for resolving
                integer submission type IDs.
            tracks: Optional ``{id: name}`` mapping for resolving integer
                track IDs.
            rooms: Optional ``{id: name}`` mapping for resolving integer
                room IDs.

        Returns:
            A populated ``PretalxTalk`` instance.
        """
        # Slot data lives outside the generated Submission model — it comes
        # from a nested "slot" dict in the /talks/ endpoint response.
        slot = data.get("slot") or {}
        room = ""
        slot_start = ""
        slot_end = ""
        if slot and isinstance(slot, dict):
            room_raw = slot.get("room")
            room = resolve_id_or_localized(room_raw, rooms)
            slot_start = slot.get("start") or ""
            slot_end = slot.get("end") or ""

        raw = _parse_generated(GeneratedSubmission, data)
        if raw is not None:
            return cls(
                code=raw.code,
                title=raw.title,
                abstract=raw.abstract or "",
                description=raw.description or "",
                submission_type=resolve_id_or_localized(raw.submission_type, submission_types),
                track=resolve_id_or_localized(raw.track, tracks),
                duration=raw.duration,
                state=raw.state.value if raw.state else "",
                speaker_codes=list(raw.speakers),
                room=room,
                slot_start=slot_start,
                slot_end=slot_end,
            )

        # Fallback: dict-based extraction for API shapes the generated
        # model can't handle (e.g. speakers as dicts instead of strings).
        speakers_raw = data.get("speakers") or []
        speaker_codes = [s["code"] if isinstance(s, dict) else str(s) for s in speakers_raw]

        sub_type_raw = data.get("submission_type")
        submission_type = resolve_id_or_localized(sub_type_raw, submission_types)

        track_raw = data.get("track")
        track = resolve_id_or_localized(track_raw, tracks)

        return cls(
            code=data.get("code", ""),
            title=data.get("title", ""),
            abstract=data.get("abstract") or "",
            description=data.get("description") or "",
            submission_type=submission_type,
            track=track,
            duration=data.get("duration"),
            state=data.get("state") or "",
            speaker_codes=speaker_codes,
            room=room,
            slot_start=slot_start,
            slot_end=slot_end,
        )


@dataclass(frozen=True, slots=True)
class PretalxSlot:
    """A schedule slot from the Pretalx schedule API.

    Attributes:
        room: Resolved display name of the room.
        start: Slot start time as an ISO 8601 string.
        end: Slot end time as an ISO 8601 string.
        code: Submission code if this slot holds a talk, empty otherwise.
        title: Resolved display title for the slot.
        start_dt: Parsed start datetime, or ``None`` if unparsable.
        end_dt: Parsed end datetime, or ``None`` if unparsable.
    """

    room: str
    start: str
    end: str
    code: str = ""
    title: str = ""
    start_dt: datetime | None = field(default=None, repr=False)
    end_dt: datetime | None = field(default=None, repr=False)

    @classmethod
    def from_api(
        cls,
        data: dict[str, Any],
        *,
        rooms: dict[int, str] | None = None,
    ) -> PretalxSlot:
        """Construct a ``PretalxSlot`` from a raw Pretalx schedule slot dict.

        Validates the raw dict through the generated ``TalkSlot`` model,
        then delegates to :func:`~pretalx_client.adapters.schedule.normalize_slot`
        for field extraction and normalization.

        Handles both the legacy format (string ``room``, ``code``, ``title``
        keys) and the real paginated ``/slots/`` format (integer ``room`` ID,
        ``submission`` key instead of ``code``, no ``title``).

        Args:
            data: A single slot object from the Pretalx schedule endpoint.
            rooms: Optional ``{id: name}`` mapping for resolving integer
                room IDs.

        Returns:
            A populated ``PretalxSlot`` instance.
        """
        # Validate through generated model (logs on failure but doesn't block)
        _parse_generated(GeneratedTalkSlot, data)

        normalized = normalize_slot(data, rooms=rooms)
        return cls(
            room=normalized["room"],
            start=normalized["start"],
            end=normalized["end"],
            code=normalized["code"],
            title=normalized["title"],
            start_dt=normalized["start_dt"],
            end_dt=normalized["end_dt"],
        )
