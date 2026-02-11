"""HTTP client for the Pretalx REST API.

Provides :class:`PretalxClient` for fetching speakers, talks, submissions, and
schedule data from a Pretalx event instance.  Handles pagination automatically
and supports both authenticated and unauthenticated (public) access.

API response data is returned as typed dataclasses (:class:`PretalxSpeaker`,
:class:`PretalxTalk`, :class:`PretalxSlot`) rather than raw dicts, following
the pytanis pattern with stdlib dataclasses instead of pydantic.
"""

import enum
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

        Args:
            data: A single speaker object from the Pretalx speakers endpoint.

        Returns:
            A populated ``PretalxSpeaker`` instance.
        """
        return cls(
            code=data.get("code", ""),
            name=data.get("name", ""),
            biography=data.get("biography") or "",
            avatar_url=data.get("avatar") or "",
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
    def from_api(cls, data: dict[str, Any]) -> PretalxTalk:
        """Construct a ``PretalxTalk`` from a raw Pretalx API dict.

        Handles multilingual fields for ``submission_type``, ``track``, and
        slot data which may be nested objects with language keys.

        Args:
            data: A single submission or talk object from the Pretalx API.

        Returns:
            A populated ``PretalxTalk`` instance.
        """
        speakers_raw = data.get("speakers") or []
        speaker_codes = [s["code"] if isinstance(s, dict) else str(s) for s in speakers_raw]

        slot = data.get("slot") or {}
        room = ""
        slot_start = ""
        slot_end = ""
        if slot and isinstance(slot, dict):
            room = _localized(slot.get("room"))
            slot_start = slot.get("start") or ""
            slot_end = slot.get("end") or ""

        return cls(
            code=data.get("code", ""),
            title=data.get("title", ""),
            abstract=data.get("abstract") or "",
            description=data.get("description") or "",
            submission_type=_localized(data.get("submission_type")),
            track=_localized(data.get("track")),
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
    def from_api(cls, data: dict[str, Any]) -> PretalxSlot:
        """Construct a ``PretalxSlot`` from a raw Pretalx schedule slot dict.

        Args:
            data: A single slot object from the Pretalx schedule endpoint.

        Returns:
            A populated ``PretalxSlot`` instance.
        """
        start_str = data.get("start") or ""
        end_str = data.get("end") or ""

        return cls(
            room=_localized(data.get("room")),
            start=start_str,
            end=end_str,
            code=data.get("code") or "",
            title=_localized(data.get("title")),
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

    def fetch_speakers(self) -> list[PretalxSpeaker]:
        """Fetch all speakers for the event.

        Returns:
            A list of :class:`PretalxSpeaker` instances.
        """
        url = f"{self.api_url}speakers/"
        return [PretalxSpeaker.from_api(item) for item in self._get_paginated(url)]

    def fetch_talks(self) -> list[PretalxTalk]:
        """Fetch all confirmed/accepted talks for the event.

        The talks endpoint returns only submissions that have been accepted
        into the schedule, unlike :meth:`fetch_submissions` which can return
        submissions in any state.

        Returns:
            A list of :class:`PretalxTalk` instances.
        """
        url = f"{self.api_url}talks/"
        return [PretalxTalk.from_api(item) for item in self._get_paginated(url)]

    def fetch_submissions(self, *, state: str = "") -> list[PretalxTalk]:
        """Fetch submissions for the event, optionally filtered by state.

        Args:
            state: Pretalx submission state to filter by (e.g.
                ``"confirmed"``). When empty, all submissions are returned.

        Returns:
            A list of :class:`PretalxTalk` instances.
        """
        url = f"{self.api_url}submissions/"
        if state:
            url = f"{url}?state={state}"
        return [PretalxTalk.from_api(item) for item in self._get_paginated(url)]

    def fetch_schedule(self) -> list[PretalxSlot]:
        """Fetch the latest schedule slots for the event.

        Unlike the other fetch methods, this endpoint is not paginated. It
        returns the full schedule in a single response.

        Returns:
            A list of :class:`PretalxSlot` instances.

        Raises:
            RuntimeError: If the API returns an HTTP error status.
        """
        url = f"{self.api_url}schedules/latest/"

        with httpx.Client(timeout=30, headers=self.headers) as client:
            logger.debug("Fetching schedule from %s", url)
            try:
                response = client.get(url)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                msg = f"Pretalx API request failed: {exc.response.status_code} for URL {exc.request.url}"
                raise RuntimeError(msg) from exc
            except httpx.RequestError as exc:
                msg = f"Pretalx API connection error for URL {url}: {exc}"
                raise RuntimeError(msg) from exc

        data = response.json()
        raw_slots: list[dict[str, Any]] = data.get("slots", [])
        logger.debug("Fetched %d schedule slots", len(raw_slots))
        return [PretalxSlot.from_api(slot) for slot in raw_slots]
