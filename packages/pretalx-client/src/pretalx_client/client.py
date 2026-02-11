"""HTTP client for the Pretalx REST API.

Provides :class:`PretalxClient` for fetching speakers, talks, submissions, and
schedule data from a Pretalx event instance.  Handles pagination automatically
and supports both authenticated and unauthenticated (public) access.

API response data is returned as typed dataclasses (:class:`PretalxSpeaker`,
:class:`PretalxTalk`, :class:`PretalxSlot`) rather than raw dicts, following
the pytanis pattern with stdlib dataclasses instead of pydantic.
"""

import http
import logging
from typing import Any

import httpx

from pretalx_client.models import (
    PretalxSlot,
    PretalxSpeaker,
    PretalxTalk,
    _localized,
)

logger = logging.getLogger(__name__)


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
