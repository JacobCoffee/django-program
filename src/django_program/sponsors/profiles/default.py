"""Default sponsor profile: no API sync."""

from django_program.sponsors.profiles.base import SponsorSyncProfile


class DefaultSponsorProfile(SponsorSyncProfile):
    """Default profile with no external sponsor sync."""

    name = "default"
    has_api_sync = False
