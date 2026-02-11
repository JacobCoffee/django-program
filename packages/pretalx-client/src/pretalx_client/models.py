"""Typed dataclasses for Pretalx API response data.

Provides :class:`PretalxSpeaker`, :class:`PretalxTalk`, and :class:`PretalxSlot`
as frozen dataclasses that parse raw API dicts into well-typed Python objects.
Also includes :class:`SubmissionState` for the submission lifecycle and helper
functions for resolving Pretalx multilingual fields.
"""

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def _localized(value: str | dict[str, object] | None) -> str:
    """Extract a display string from a Pretalx multilingual field.

    Pretalx returns localized fields as either a plain string or a dict
    keyed by language code (e.g. ``{"en": "Talk", "de": "Vortrag"}``).
    This helper returns the ``en`` value when available, falling back to
    the first available language, or an empty string for ``None``.

    Args:
        value: A string, a multilingual dict, an object with a ``name``
            dict, or ``None``.

    Returns:
        The resolved display string.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return str(value)

    if "en" in value:
        return str(value["en"])
    if "name" in value:
        return _localized(value["name"])  # type: ignore[arg-type]
    return next((v for v in value.values() if isinstance(v, str)), "")


def _resolve_id_or_localized(
    value: int | str | dict[str, object] | None,
    mapping: dict[int, str] | None = None,
) -> str:
    """Resolve a Pretalx field that may be an integer ID or a localized value.

    When the real API returns an integer ID (e.g. for ``submission_type``,
    ``track``, or ``room``), the optional mapping dict is used to look up the
    human-readable name.  Falls back to :func:`_localized` for string/dict
    values, or ``str(value)`` for unmapped integers.

    Args:
        value: An integer ID, a string, a multilingual dict, or ``None``.
        mapping: Optional ``{id: name}`` dict for resolving integer IDs.

    Returns:
        The resolved display string, or empty string for ``None``.
    """
    if value is None:
        return ""
    if isinstance(value, int):
        if mapping and value in mapping:
            return mapping[value]
        return str(value)
    return _localized(value)


def _parse_datetime(value: str) -> datetime | None:
    """Parse an ISO 8601 datetime string, returning ``None`` on failure.

    Args:
        value: An ISO 8601 formatted datetime string.

    Returns:
        A ``datetime`` instance, or ``None`` if the string is empty or
        cannot be parsed.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):  # fmt: skip
        return None


class SubmissionState(enum.StrEnum):
    """Pretalx submission lifecycle states."""

    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CONFIRMED = "confirmed"
    WITHDRAWN = "withdrawn"
    CANCELED = "canceled"
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

        Checks both ``avatar_url`` and ``avatar`` keys since different Pretalx
        instances use different field names.

        Args:
            data: A single speaker object from the Pretalx speakers endpoint.

        Returns:
            A populated ``PretalxSpeaker`` instance.
        """
        avatar = data.get("avatar_url") or data.get("avatar") or ""
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

        Handles multilingual fields for ``submission_type``, ``track``, and
        slot data which may be nested objects with language keys.  When the
        real API returns integer IDs instead of objects, the optional mapping
        dicts are used to resolve human-readable names.

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
        speakers_raw = data.get("speakers") or []
        speaker_codes = [s["code"] if isinstance(s, dict) else str(s) for s in speakers_raw]

        sub_type_raw = data.get("submission_type")
        submission_type = _resolve_id_or_localized(sub_type_raw, submission_types)

        track_raw = data.get("track")
        track = _resolve_id_or_localized(track_raw, tracks)

        slot = data.get("slot") or {}
        room = ""
        slot_start = ""
        slot_end = ""
        if slot and isinstance(slot, dict):
            room_raw = slot.get("room")
            room = _resolve_id_or_localized(room_raw, rooms)
            slot_start = slot.get("start") or ""
            slot_end = slot.get("end") or ""

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
        start_str = data.get("start") or ""
        end_str = data.get("end") or ""

        room_raw = data.get("room")
        room = _resolve_id_or_localized(room_raw, rooms)

        code = data.get("submission") or data.get("code") or ""
        title = _localized(data.get("title")) if "title" in data else ""

        return cls(
            room=room,
            start=start_str,
            end=end_str,
            code=code,
            title=title,
            start_dt=_parse_datetime(start_str),
            end_dt=_parse_datetime(end_str),
        )
