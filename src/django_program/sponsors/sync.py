"""Sponsor sync service for pulling sponsors from the PSF API."""

import logging
from typing import TYPE_CHECKING

import httpx

from django_program.sponsors.models import Sponsor, SponsorLevel
from django_program.sponsors.profiles.resolver import resolve_sponsor_profile

if TYPE_CHECKING:
    from django_program.conference.models import Conference

logger = logging.getLogger(__name__)

_HTTP_UNAUTHORIZED = 401


class SponsorSyncService:
    """Sync sponsors from the PSF sponsorship API.

    Args:
        conference: The conference to sync sponsors for.

    Raises:
        ValueError: If the conference does not support PSF sponsor sync.
    """

    def __init__(self, conference: Conference) -> None:
        """Initialize the sync service for a conference.

        Args:
            conference: The conference to sync sponsors for.

        Raises:
            ValueError: If the conference does not support PSF sponsor sync.
        """
        self.conference = conference
        self.profile = resolve_sponsor_profile(
            event_slug=conference.pretalx_event_slug or "",
            conference_slug=str(conference.slug),
        )
        if not self.profile.has_api_sync:
            msg = (
                f"Conference '{conference.slug}' does not support PSF sponsor sync. "
                "Only PyCon US conferences are supported."
            )
            raise ValueError(msg)
        self._config = self.profile.api_config()

    def sync_sponsors(self) -> int:
        """Fetch sponsors from the PSF API and create/update local records.

        Returns:
            The number of sponsors synced.
        """
        placements = self._fetch_placements()
        count = 0
        for placement in placements:
            sponsor_id = str(placement.get("sponsor_id", ""))
            sponsor_name = placement.get("sponsor", "")
            sponsor_slug = placement.get("sponsor_slug", "")
            level_name = placement.get("level_name", "")
            level_order = int(placement.get("level_order", 0) or 0)
            website_url = placement.get("sponsor_url", "")
            logo_url = placement.get("logo", "")
            description = placement.get("description", "")

            if not sponsor_name:
                continue

            level, created = SponsorLevel.objects.get_or_create(
                conference=self.conference,
                name=level_name or "Sponsor",
                defaults={"cost": 0, "order": level_order},
            )
            if not created and level.order != level_order:
                level.order = level_order
                level.save(update_fields=["order"])

            sponsor = self._find_sponsor(sponsor_id, sponsor_name)
            if sponsor is not None:
                sponsor.name = sponsor_name
                sponsor.slug = sponsor_slug or sponsor.slug
                sponsor.level = level
                sponsor.external_id = sponsor_id
                sponsor.website_url = website_url or sponsor.website_url
                sponsor.logo_url = logo_url or sponsor.logo_url
                sponsor.description = description or sponsor.description
                sponsor.save()
            else:
                Sponsor.objects.create(
                    conference=self.conference,
                    level=level,
                    name=sponsor_name,
                    slug=sponsor_slug,
                    external_id=sponsor_id,
                    website_url=website_url,
                    logo_url=logo_url,
                    description=description,
                )
            count += 1

        logger.info("Synced %d sponsors for conference '%s'", count, self.conference.slug)
        return count

    def sync_all(self) -> dict[str, int]:
        """Run all sync operations and return result counts.

        Returns:
            A dict mapping entity names to sync counts.
        """
        return {"sponsors": self.sync_sponsors()}

    def _fetch_placements(self) -> list[dict[str, object]]:
        """Fetch logo placements from the PSF sponsorship API.

        Returns:
            A list of placement dicts from the API response.

        Raises:
            RuntimeError: If the API request fails.
        """
        url = f"{self._config.api_url}/sponsors/logo-placement/"
        params: dict[str, str] = {
            "publisher": self._config.publisher,
            "flight": self._config.flight,
        }

        last_exc: httpx.HTTPError | None = None
        for authorization in self._authorization_candidates():
            headers: dict[str, str] = {}
            if authorization:
                headers["Authorization"] = authorization
            try:
                response = httpx.get(url, params=params, headers=headers, timeout=30)
                response.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                # Retry alternate auth schemes only for Unauthorized responses.
                if exc.response.status_code == _HTTP_UNAUTHORIZED and authorization:
                    last_exc = exc
                    continue
                msg = f"Failed to fetch sponsors from PSF API: {exc}"
                raise RuntimeError(msg) from exc
            except httpx.HTTPError as exc:
                msg = f"Failed to fetch sponsors from PSF API: {exc}"
                raise RuntimeError(msg) from exc
        else:
            if isinstance(last_exc, httpx.HTTPStatusError) and last_exc.response.status_code == _HTTP_UNAUTHORIZED:
                msg = (
                    f"Failed to fetch sponsors from PSF API: {_HTTP_UNAUTHORIZED} Unauthorized. "
                    "Check DJANGO_PROGRAM['psf_sponsors']['token'] and "
                    "DJANGO_PROGRAM['psf_sponsors']['auth_scheme']."
                )
                raise RuntimeError(msg) from last_exc
            msg = f"Failed to fetch sponsors from PSF API: {last_exc}"
            raise RuntimeError(msg) from last_exc

        data = response.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "results" in data:
            return data["results"]
        return []

    def _authorization_candidates(self) -> list[str | None]:
        """Return authorization header values to try, in priority order."""
        token = (self._config.token or "").strip()
        if not token:
            return [None]

        # If token already includes a scheme (e.g. "Bearer abc"), use as-is.
        if " " in token:
            return [token]

        configured = (self._config.auth_scheme or "Token").strip() or "Token"
        candidates = [f"{configured} {token}"]
        lower = configured.casefold()
        if lower == "token":
            candidates.append(f"Bearer {token}")
        elif lower == "bearer":
            candidates.append(f"Token {token}")
        return candidates

    def _find_sponsor(self, external_id: str, name: str) -> Sponsor | None:
        """Find an existing sponsor by external_id, falling back to name.

        Args:
            external_id: The PSF sponsor ID.
            name: The sponsor name.

        Returns:
            An existing Sponsor instance, or None.
        """
        if external_id:
            try:
                return Sponsor.objects.get(
                    conference=self.conference,
                    external_id=external_id,
                )
            except Sponsor.DoesNotExist:
                pass
        try:
            return Sponsor.objects.get(
                conference=self.conference,
                name=name,
            )
        except Sponsor.DoesNotExist:
            return None
