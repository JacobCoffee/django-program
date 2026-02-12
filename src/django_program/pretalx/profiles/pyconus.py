"""PyCon US profile for track/tag semantics."""

from typing import TYPE_CHECKING

from django_program.pretalx.profiles.base import PretalxConferenceProfile

if TYPE_CHECKING:
    from pretalx_client.models import PretalxTalk

_PYCONUS_THEME_TAGS = {"ai", "security"}


class PyConUSPretalxProfile(PretalxConferenceProfile):
    """PyCon US keeps delivery buckets in ``track`` and uses tags for themes."""

    name = "pyconus"

    def sync_tags(self, talk: PretalxTalk) -> list[str]:
        """Persist all Pretalx tags while normalizing whitespace."""
        tags = super().sync_tags(talk)
        # Keep all tags for future flexibility, while normalizing whitespace.
        return [tag.strip() for tag in tags if tag and tag.strip()]

    def theme_tags(self, talk: PretalxTalk) -> list[str]:
        """Return known theme tags (currently AI/Security) for the talk."""
        return [tag for tag in self.sync_tags(talk) if tag.casefold() in _PYCONUS_THEME_TAGS]
