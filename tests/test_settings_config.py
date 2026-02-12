import pytest
from django.test import override_settings

from django_program.settings import get_config


def test_get_config_rejects_non_mapping_root() -> None:
    with override_settings(DJANGO_PROGRAM=["bad"]):
        with pytest.raises(TypeError, match="must be a mapping"):
            get_config()


def test_get_config_rejects_non_mapping_nested_sections() -> None:
    with override_settings(DJANGO_PROGRAM={"stripe": ["bad"]}):
        with pytest.raises(TypeError, match=r"DJANGO_PROGRAM\['stripe'\] must be a mapping"):
            get_config()

    with override_settings(DJANGO_PROGRAM={"pretalx": ["bad"]}):
        with pytest.raises(TypeError, match=r"DJANGO_PROGRAM\['pretalx'\] must be a mapping"):
            get_config()


def test_get_config_validates_primitive_values() -> None:
    with override_settings(DJANGO_PROGRAM={"cart_expiry_minutes": 0}):
        with pytest.raises(ValueError, match="positive integer"):
            get_config()

    with override_settings(DJANGO_PROGRAM={"pending_order_expiry_minutes": 0}):
        with pytest.raises(ValueError, match="positive integer"):
            get_config()

    with override_settings(DJANGO_PROGRAM={"currency": ""}):
        with pytest.raises(ValueError, match="currency"):
            get_config()

    with override_settings(DJANGO_PROGRAM={"currency_symbol": ""}):
        with pytest.raises(ValueError, match="currency_symbol"):
            get_config()

    with override_settings(DJANGO_PROGRAM={"pretalx": {"schedule_delete_guard_min_existing_slots": -1}}):
        with pytest.raises(ValueError, match="schedule_delete_guard_min_existing_slots"):
            get_config()

    with override_settings(DJANGO_PROGRAM={"pretalx": {"schedule_delete_guard_max_fraction_removed": 1.5}}):
        with pytest.raises(ValueError, match="schedule_delete_guard_max_fraction_removed"):
            get_config()


def test_get_config_cache_clears_on_setting_changed() -> None:
    with override_settings(DJANGO_PROGRAM={"currency": "USD"}):
        assert get_config().currency == "USD"

    with override_settings(DJANGO_PROGRAM={"currency": "EUR"}):
        assert get_config().currency == "EUR"


def test_get_config_rejects_non_mapping_psf_sponsors() -> None:
    """Lines 97-98: psf_sponsors that is not a mapping raises TypeError."""
    with override_settings(DJANGO_PROGRAM={"psf_sponsors": ["bad"]}):
        with pytest.raises(TypeError, match=r"DJANGO_PROGRAM\['psf_sponsors'\] must be a mapping"):
            get_config()


def test_get_config_rejects_non_bool_schedule_delete_guard_enabled() -> None:
    """Lines 125-126: schedule_delete_guard_enabled that is not bool raises TypeError."""
    with override_settings(DJANGO_PROGRAM={"pretalx": {"schedule_delete_guard_enabled": "yes"}}):
        with pytest.raises(TypeError, match="schedule_delete_guard_enabled"):
            get_config()
