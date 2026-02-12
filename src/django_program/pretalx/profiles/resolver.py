"""Resolver for selecting conference-specific Pretalx profiles."""

from typing import TYPE_CHECKING

from django_program.pretalx.profiles.default import DefaultPretalxProfile
from django_program.pretalx.profiles.pyconus import PyConUSPretalxProfile

if TYPE_CHECKING:
    from django_program.pretalx.profiles.base import PretalxConferenceProfile


def resolve_pretalx_profile(*, event_slug: str, conference_slug: str = "") -> PretalxConferenceProfile:
    """Resolve the profile used to interpret Pretalx fields for a conference."""
    event = (event_slug or "").casefold()
    conf = (conference_slug or "").casefold()
    if event.startswith(("pyconus", "pycon-us")):
        return PyConUSPretalxProfile()
    if conf.startswith(("pyconus", "pycon-us")):
        return PyConUSPretalxProfile()
    return DefaultPretalxProfile()
