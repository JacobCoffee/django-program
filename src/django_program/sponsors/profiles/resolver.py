"""Resolver for selecting conference-specific sponsor profiles."""

from typing import TYPE_CHECKING

from django_program.sponsors.profiles.default import DefaultSponsorProfile
from django_program.sponsors.profiles.pyconus import PyConUSSponsorProfile

if TYPE_CHECKING:
    from django_program.sponsors.profiles.base import SponsorSyncProfile


def resolve_sponsor_profile(*, event_slug: str = "", conference_slug: str = "") -> SponsorSyncProfile:
    """Resolve the sponsor sync profile for a conference.

    Args:
        event_slug: The Pretalx event slug for the conference.
        conference_slug: The conference slug.

    Returns:
        A sponsor sync profile instance.
    """
    event = (event_slug or "").casefold()
    conf = (conference_slug or "").casefold()
    if event.startswith(("pyconus", "pycon-us")):
        return PyConUSSponsorProfile()
    if conf.startswith(("pyconus", "pycon-us")):
        return PyConUSSponsorProfile()
    return DefaultSponsorProfile()
