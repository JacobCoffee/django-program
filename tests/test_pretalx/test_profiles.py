from django_program.pretalx.profiles import (
    DefaultPretalxProfile,
    PyConUSPretalxProfile,
    resolve_pretalx_profile,
)


def test_resolve_profile_for_pyconus_event_slug():
    profile = resolve_pretalx_profile(event_slug="pyconus2026", conference_slug="any")
    assert isinstance(profile, PyConUSPretalxProfile)


def test_resolve_profile_for_pyconus_conference_slug():
    profile = resolve_pretalx_profile(event_slug="conference-2026", conference_slug="pycon-us")
    assert isinstance(profile, PyConUSPretalxProfile)


def test_resolve_profile_default():
    profile = resolve_pretalx_profile(event_slug="djangocon-us-2026", conference_slug="djangocon")
    assert isinstance(profile, DefaultPretalxProfile)
