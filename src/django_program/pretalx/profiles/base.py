"""Conference profile hooks for Pretalx sync semantics."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pretalx_client.models import PretalxTalk


class PretalxConferenceProfile:
    """Base profile for Pretalx event-specific behavior."""

    name = "default"

    def sync_track(self, talk: PretalxTalk) -> str:
        """Return the value to store in ``Talk.track``."""
        return talk.track

    def sync_tags(self, talk: PretalxTalk) -> list[str]:
        """Return the list of tags to store in ``Talk.tags``."""
        return list(talk.tags)
