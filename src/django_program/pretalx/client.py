"""HTTP client for the Pretalx REST API.

Provides :class:`PretalxClient` for fetching speakers, talks, submissions, and
schedule data from a Pretalx event instance.  Handles pagination automatically
and supports both authenticated and unauthenticated (public) access.

API response data is returned as typed dataclasses (:class:`PretalxSpeaker`,
:class:`PretalxTalk`, :class:`PretalxSlot`) rather than raw dicts, following
the pytanis pattern with stdlib dataclasses instead of pydantic.
"""

import enum
import http
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)


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


class PretalxClient:
    """HTTP client for the Pretalx REST API.

    Provides methods to fetch speakers, talks, and schedule data from a
    Pretalx event. Handles pagination automatically and supports both
    authenticated and public access. Returns typed dataclasses rather
    than raw dicts.

    Args:
        event_slug: The Pretalx event slug (e.g. ``"pycon-us-2026"``).
        base_url: Root URL of the Pretalx instance. Defaults to
            ``"https://pretalx.com"``.
        api_token: Optional API token for authenticated access. When empty,
            only publicly available data will be returned.

    Example::

        client = PretalxClient("pycon-us-2026", api_token="abc123")
        speakers = client.fetch_speakers()
        talks = client.fetch_talks()
        schedule = client.fetch_schedule()
    """

    def __init__(
        self,
        event_slug: str,
        *,
        base_url: str = "https://pretalx.com",
        api_token: str = "",
    ) -> None:
        """Initialize the client for a specific Pretalx event.

        Args:
            event_slug: The Pretalx event slug (e.g. ``"pycon-us-2026"``).
            base_url: Root URL of the Pretalx instance.
            api_token: Optional API token for authenticated access.
        """
        self.event_slug = event_slug
        normalized_base_url = base_url.rstrip("/")
        normalized_base_url = normalized_base_url.removesuffix("/api")
        self.base_url = normalized_base_url
        self.api_token = api_token
        self.api_url = f"{self.base_url}/api/events/{self.event_slug}/"

        self.headers: dict[str, str] = {"Accept": "application/json"}
        if self.api_token:
            self.headers["Authorization"] = f"Token {self.api_token}"

    def _get_paginated(self, url: str) -> list[dict[str, Any]]:
        """Fetch all pages from a paginated Pretalx API endpoint.

        Follows the ``next`` link in each response until all pages have been
        collected.

        Args:
            url: The initial URL to fetch.

        Returns:
            A flat list of result dicts collected across all pages.

        Raises:
            RuntimeError: If the API returns an HTTP error status.
        """
        results: list[dict[str, Any]] = []
        current_url: str | None = url

        with httpx.Client(timeout=30, headers=self.headers) as client:
            while current_url is not None:
                logger.debug("Fetching %s", current_url)
                try:
                    response = client.get(current_url)
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    msg = f"Pretalx API request failed: {exc.response.status_code} for URL {exc.request.url}"
                    raise RuntimeError(msg) from exc
                except httpx.RequestError as exc:
                    msg = f"Pretalx API connection error for URL {current_url}: {exc}"
                    raise RuntimeError(msg) from exc

                data = response.json()
                results.extend(data.get("results", []))
                current_url = data.get("next")

        logger.debug("Collected %d results from paginated endpoint", len(results))
        return results

    def _get_paginated_or_none(self, url: str) -> list[dict[str, Any]] | None:
        """Fetch a paginated endpoint, returning ``None`` on HTTP 404.

        Behaves like :meth:`_get_paginated` but treats a 404 response as a
        signal that the endpoint does not exist for this event, returning
        ``None`` instead of raising.

        Args:
            url: The initial URL to fetch.

        Returns:
            A flat list of result dicts, or ``None`` if the endpoint returned
            404.

        Raises:
            RuntimeError: If the API returns a non-404 HTTP error status.
        """
        results: list[dict[str, Any]] = []
        current_url: str | None = url

        with httpx.Client(timeout=30, headers=self.headers) as client:
            while current_url is not None:
                logger.debug("Fetching %s", current_url)
                try:
                    response = client.get(current_url)
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == http.HTTPStatus.NOT_FOUND:
                        logger.debug("Got 404 for %s, endpoint unavailable", url)
                        return None
                    msg = f"Pretalx API request failed: {exc.response.status_code} for URL {exc.request.url}"
                    raise RuntimeError(msg) from exc
                except httpx.RequestError as exc:
                    msg = f"Pretalx API connection error for URL {current_url}: {exc}"
                    raise RuntimeError(msg) from exc

                data = response.json()
                results.extend(data.get("results", []))
                current_url = data.get("next")

        logger.debug("Collected %d results from paginated endpoint", len(results))
        return results

    def _fetch_id_name_mapping(self, endpoint: str) -> dict[int, str]:
        """Fetch a lookup table from a Pretalx endpoint that returns ID+name objects.

        Works for ``/rooms/``, ``/submission-types/``, and ``/tracks/``
        endpoints where each object has an integer ``id`` and a localized
        ``name`` field.

        Args:
            endpoint: The endpoint path relative to the event API URL
                (e.g. ``"rooms/"``).

        Returns:
            A dict mapping integer IDs to resolved display name strings.
        """
        url = f"{self.api_url}{endpoint}"
        items = self._get_paginated(url)
        mapping: dict[int, str] = {}
        for item in items:
            item_id = item.get("id")
            if item_id is not None:
                mapping[int(item_id)] = _localized(item.get("name"))
        return mapping

    def fetch_rooms(self) -> dict[int, str]:
        """Fetch room ID-to-name mappings for the event.

        Returns:
            A dict mapping room IDs to display names.
        """
        return self._fetch_id_name_mapping("rooms/")

    def fetch_rooms_full(self) -> list[dict[str, Any]]:
        """Fetch full room data for the event.

        Returns all fields from the Pretalx ``/rooms/`` endpoint including
        ``id``, ``name``, ``description``, ``capacity``, and ``position``.

        Returns:
            A list of raw room dicts from the Pretalx API.
        """
        url = f"{self.api_url}rooms/"
        return self._get_paginated(url)

    def fetch_submission_types(self) -> dict[int, str]:
        """Fetch submission type ID-to-name mappings for the event.

        Returns:
            A dict mapping submission type IDs to display names.
        """
        return self._fetch_id_name_mapping("submission-types/")

    def fetch_tracks(self) -> dict[int, str]:
        """Fetch track ID-to-name mappings for the event.

        Returns:
            A dict mapping track IDs to display names.
        """
        return self._fetch_id_name_mapping("tracks/")

    def fetch_speakers(self) -> list[PretalxSpeaker]:
        """Fetch all speakers for the event.

        Returns:
            A list of :class:`PretalxSpeaker` instances.
        """
        url = f"{self.api_url}speakers/"
        return [PretalxSpeaker.from_api(item) for item in self._get_paginated(url)]

    def fetch_talks(
        self,
        *,
        submission_types: dict[int, str] | None = None,
        tracks: dict[int, str] | None = None,
        rooms: dict[int, str] | None = None,
    ) -> list[PretalxTalk]:
        """Fetch all confirmed/accepted talks for the event.

        Tries the ``/talks/`` endpoint first. When that returns 404 (as it
        does for some Pretalx events like PyCon US), falls back to
        ``/submissions/`` with both ``confirmed`` and ``accepted`` states to
        capture all scheduled content including tutorials and sponsor talks.

        Args:
            submission_types: Optional ID-to-name mapping for submission types.
            tracks: Optional ID-to-name mapping for tracks.
            rooms: Optional ID-to-name mapping for rooms.

        Returns:
            A list of :class:`PretalxTalk` instances.
        """
        url = f"{self.api_url}talks/"
        raw = self._get_paginated_or_none(url)
        if raw is None:
            logger.info("talks/ endpoint returned 404, falling back to submissions/ with confirmed+accepted states")
            confirmed = self._get_paginated(f"{self.api_url}submissions/?state=confirmed")
            accepted = self._get_paginated(f"{self.api_url}submissions/?state=accepted")
            raw = confirmed + accepted
            logger.info("Fetched %d confirmed + %d accepted = %d submissions", len(confirmed), len(accepted), len(raw))
        return [
            PretalxTalk.from_api(
                item,
                submission_types=submission_types,
                tracks=tracks,
                rooms=rooms,
            )
            for item in raw
        ]

    def fetch_submissions(
        self,
        *,
        state: str = "",
        submission_types: dict[int, str] | None = None,
        tracks: dict[int, str] | None = None,
        rooms: dict[int, str] | None = None,
    ) -> list[PretalxTalk]:
        """Fetch submissions for the event, optionally filtered by state.

        Args:
            state: Pretalx submission state to filter by (e.g.
                ``"confirmed"``). When empty, all submissions are returned.
            submission_types: Optional ID-to-name mapping for submission types.
            tracks: Optional ID-to-name mapping for tracks.
            rooms: Optional ID-to-name mapping for rooms.

        Returns:
            A list of :class:`PretalxTalk` instances.
        """
        url = f"{self.api_url}submissions/"
        if state:
            url = f"{url}?state={state}"
        return [
            PretalxTalk.from_api(
                item,
                submission_types=submission_types,
                tracks=tracks,
                rooms=rooms,
            )
            for item in self._get_paginated(url)
        ]

    def fetch_schedule(
        self,
        *,
        rooms: dict[int, str] | None = None,
    ) -> list[PretalxSlot]:
        """Fetch schedule slots for the event from the paginated ``/slots/`` endpoint.

        Uses the ``/slots/`` endpoint which returns fully expanded slot objects
        with start/end times and room IDs, unlike ``/schedules/latest/`` which
        only returns slot ID integers.

        Args:
            rooms: Optional ID-to-name mapping for resolving integer room IDs.

        Returns:
            A list of :class:`PretalxSlot` instances.
        """
        url = f"{self.api_url}slots/"
        raw_slots = self._get_paginated(url)
        logger.debug("Fetched %d schedule slots", len(raw_slots))
        return [PretalxSlot.from_api(slot, rooms=rooms) for slot in raw_slots]
