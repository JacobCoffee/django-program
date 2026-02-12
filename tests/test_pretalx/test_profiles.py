from django_program.pretalx.profiles import (
    DefaultPretalxProfile,
    PyConUSPretalxProfile,
    resolve_pretalx_profile,
)
from pretalx_client.models import PretalxTalk


def test_resolve_profile_for_pyconus_event_slug():
    profile = resolve_pretalx_profile(event_slug="pyconus2026", conference_slug="any")
    assert isinstance(profile, PyConUSPretalxProfile)


def test_resolve_profile_for_pyconus_conference_slug():
    profile = resolve_pretalx_profile(event_slug="conference-2026", conference_slug="pycon-us")
    assert isinstance(profile, PyConUSPretalxProfile)


def test_resolve_profile_default():
    profile = resolve_pretalx_profile(event_slug="djangocon-us-2026", conference_slug="djangocon")
    assert isinstance(profile, DefaultPretalxProfile)


# ---------------------------------------------------------------------------
# PyConUSPretalxProfile.sync_tags
# ---------------------------------------------------------------------------


def test_pyconus_sync_tags_normalizes_whitespace():
    profile = PyConUSPretalxProfile()
    talk = PretalxTalk(code="T1", title="Test", tags=["  AI ", " Security ", "Web"])
    result = profile.sync_tags(talk)
    assert result == ["AI", "Security", "Web"]


def test_pyconus_sync_tags_filters_empty_strings():
    profile = PyConUSPretalxProfile()
    talk = PretalxTalk(code="T1", title="Test", tags=["AI", "", "  ", "Security"])
    result = profile.sync_tags(talk)
    assert result == ["AI", "Security"]


def test_pyconus_sync_tags_empty_input():
    profile = PyConUSPretalxProfile()
    talk = PretalxTalk(code="T1", title="Test", tags=[])
    result = profile.sync_tags(talk)
    assert result == []


# ---------------------------------------------------------------------------
# PyConUSPretalxProfile.theme_tags
# ---------------------------------------------------------------------------


def test_pyconus_theme_tags_returns_known_themes():
    profile = PyConUSPretalxProfile()
    talk = PretalxTalk(code="T1", title="Test", tags=["AI", "Web", "Security"])
    result = profile.theme_tags(talk)
    assert set(result) == {"AI", "Security"}


def test_pyconus_theme_tags_case_insensitive():
    profile = PyConUSPretalxProfile()
    talk = PretalxTalk(code="T1", title="Test", tags=["ai", "SECURITY", "Ai"])
    result = profile.theme_tags(talk)
    assert len(result) == 3
    assert all(tag.casefold() in {"ai", "security"} for tag in result)


def test_pyconus_theme_tags_no_matches():
    profile = PyConUSPretalxProfile()
    talk = PretalxTalk(code="T1", title="Test", tags=["Web", "Data Science"])
    result = profile.theme_tags(talk)
    assert result == []


def test_pyconus_theme_tags_empty():
    profile = PyConUSPretalxProfile()
    talk = PretalxTalk(code="T1", title="Test", tags=[])
    result = profile.theme_tags(talk)
    assert result == []
