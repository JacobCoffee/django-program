"""Tests for sponsor sync profiles and resolver."""

import pytest

from django_program.sponsors.profiles import (
    DefaultSponsorProfile,
    PyConUSSponsorProfile,
    SponsorSyncProfile,
    resolve_sponsor_profile,
)


def test_resolve_profile_for_pyconus_event_slug():
    profile = resolve_sponsor_profile(event_slug="pyconus2027", conference_slug="any")
    assert isinstance(profile, PyConUSSponsorProfile)


def test_resolve_profile_for_pycon_us_event_slug():
    profile = resolve_sponsor_profile(event_slug="pycon-us-2027")
    assert isinstance(profile, PyConUSSponsorProfile)


def test_resolve_profile_for_pyconus_conference_slug():
    profile = resolve_sponsor_profile(event_slug="other", conference_slug="pycon-us-2027")
    assert isinstance(profile, PyConUSSponsorProfile)


def test_resolve_profile_default():
    profile = resolve_sponsor_profile(event_slug="djangocon", conference_slug="djangocon-us")
    assert isinstance(profile, DefaultSponsorProfile)


def test_resolve_profile_empty_slugs():
    profile = resolve_sponsor_profile()
    assert isinstance(profile, DefaultSponsorProfile)


def test_default_profile_has_no_api_sync():
    profile = DefaultSponsorProfile()
    assert profile.has_api_sync is False
    assert profile.name == "default"


def test_pyconus_profile_has_api_sync():
    profile = PyConUSSponsorProfile()
    assert profile.has_api_sync is True
    assert profile.name == "pyconus"


def test_base_profile_api_config_raises():
    profile = SponsorSyncProfile()
    with pytest.raises(NotImplementedError, match="does not support API sync"):
        profile.api_config()


def test_default_profile_api_config_raises():
    profile = DefaultSponsorProfile()
    with pytest.raises(NotImplementedError, match="does not support API sync"):
        profile.api_config()


@pytest.mark.django_db
def test_pyconus_profile_api_config():
    profile = PyConUSSponsorProfile()
    config = profile.api_config()
    assert config.publisher == "pycon"
    assert config.flight == "sponsors"
    assert "python.org" in config.api_url
