"""Base sponsor sync profile."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django_program.settings import PSFSponsorConfig


class SponsorSyncProfile:
    """Base profile for sponsor sync behavior."""

    name = "default"
    has_api_sync = False

    def api_config(self) -> PSFSponsorConfig:
        """Return PSF sponsor API configuration.

        Raises:
            NotImplementedError: If this profile does not support API sync.
        """
        msg = f"Profile '{self.name}' does not support API sync"
        raise NotImplementedError(msg)
