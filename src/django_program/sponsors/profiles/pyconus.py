"""PyCon US sponsor profile: syncs from PSF sponsorship API."""

from django_program.settings import PSFSponsorConfig, get_config
from django_program.sponsors.profiles.base import SponsorSyncProfile


class PyConUSSponsorProfile(SponsorSyncProfile):
    """PyCon US profile that syncs sponsors from the PSF API."""

    name = "pyconus"
    has_api_sync = True

    def api_config(self) -> PSFSponsorConfig:
        """Return PSF sponsor API configuration from settings."""
        return get_config().psf_sponsors
