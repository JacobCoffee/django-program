"""Tests for sponsor override models and effective properties."""

from datetime import date

import pytest
from django.core.exceptions import ValidationError

from django_program.conference.models import Conference
from django_program.sponsors.models import Sponsor, SponsorLevel, SponsorOverride

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_conference(slug="sponsor-conf", **overrides):
    """Create and return a Conference with sensible defaults."""
    defaults = {
        "name": "Sponsor Conf",
        "slug": slug,
        "start_date": date(2027, 5, 1),
        "end_date": date(2027, 5, 3),
        "timezone": "US/Eastern",
    }
    defaults.update(overrides)
    return Conference.objects.create(**defaults)


def _make_level(conference, name="Gold", **overrides):
    """Create and return a SponsorLevel."""
    defaults = {
        "name": name,
        "cost": 5000.00,
    }
    defaults.update(overrides)
    return SponsorLevel.objects.create(conference=conference, **defaults)


def _make_sponsor(conference, level, name="Acme Corp", **overrides):
    """Create and return a Sponsor."""
    defaults = {
        "name": name,
    }
    defaults.update(overrides)
    return Sponsor.objects.create(conference=conference, level=level, **defaults)


# ===========================================================================
# SponsorOverride.__str__
# ===========================================================================


@pytest.mark.django_db
class TestSponsorOverrideStr:
    def test_str(self):
        conf = _make_conference(slug="sponsor-str")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp")
        override = SponsorOverride.objects.create(sponsor=sponsor, conference=conf)
        assert str(override) == "Override for Acme Corp (Gold)"


# ===========================================================================
# SponsorOverride.save() auto-set conference
# ===========================================================================


@pytest.mark.django_db
class TestSponsorOverrideSave:
    def test_save_auto_sets_conference_from_sponsor(self):
        conf = _make_conference(slug="sponsor-save-auto")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp")
        override = SponsorOverride(sponsor=sponsor)
        override.save()
        assert override.conference_id == conf.pk

    def test_save_does_not_override_explicit_conference(self):
        conf_a = _make_conference(slug="sponsor-save-a")
        conf_b = _make_conference(slug="sponsor-save-b")
        level_a = _make_level(conf_a)
        sponsor = _make_sponsor(conf_a, level_a, "Acme Corp")
        override = SponsorOverride(sponsor=sponsor, conference=conf_b)
        override.save()
        assert override.conference_id == conf_b.pk


# ===========================================================================
# SponsorOverride.clean()
# ===========================================================================


@pytest.mark.django_db
class TestSponsorOverrideClean:
    def test_clean_valid_same_conference(self):
        conf = _make_conference(slug="sponsor-clean-ok")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp")
        override = SponsorOverride(sponsor=sponsor, conference=conf)
        override.clean()

    def test_clean_rejects_mismatched_conference(self):
        conf_a = _make_conference(slug="sponsor-clean-a")
        conf_b = _make_conference(slug="sponsor-clean-b")
        level_a = _make_level(conf_a)
        sponsor = _make_sponsor(conf_a, level_a, "Acme Corp")
        override = SponsorOverride(sponsor=sponsor, conference=conf_b)
        with pytest.raises(ValidationError, match="does not belong to this conference"):
            override.clean()

    def test_clean_skips_when_no_sponsor(self):
        conf = _make_conference(slug="sponsor-clean-nosponsor")
        override = SponsorOverride(conference=conf)
        override.clean()

    def test_clean_skips_when_no_conference(self):
        conf = _make_conference(slug="sponsor-clean-noconf")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp")
        override = SponsorOverride(sponsor=sponsor)
        override.clean()


# ===========================================================================
# SponsorOverride.is_empty
# ===========================================================================


@pytest.mark.django_db
class TestSponsorOverrideIsEmpty:
    def test_empty_override(self):
        conf = _make_conference(slug="sponsor-empty-ov")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp")
        override = SponsorOverride.objects.create(sponsor=sponsor, conference=conf)
        assert override.is_empty is True

    def test_non_empty_override_name(self):
        conf = _make_conference(slug="sponsor-notempty-name")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp")
        override = SponsorOverride.objects.create(sponsor=sponsor, conference=conf, override_name="New Name")
        assert override.is_empty is False

    def test_non_empty_override_description(self):
        conf = _make_conference(slug="sponsor-notempty-desc")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp")
        override = SponsorOverride.objects.create(
            sponsor=sponsor, conference=conf, override_description="New description"
        )
        assert override.is_empty is False

    def test_non_empty_override_website_url(self):
        conf = _make_conference(slug="sponsor-notempty-url")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp")
        override = SponsorOverride.objects.create(
            sponsor=sponsor, conference=conf, override_website_url="https://new.com"
        )
        assert override.is_empty is False

    def test_non_empty_override_logo_url(self):
        conf = _make_conference(slug="sponsor-notempty-logo")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp")
        override = SponsorOverride.objects.create(
            sponsor=sponsor, conference=conf, override_logo_url="https://new.com/logo.png"
        )
        assert override.is_empty is False

    def test_non_empty_override_contact_name(self):
        conf = _make_conference(slug="sponsor-notempty-contact")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp")
        override = SponsorOverride.objects.create(sponsor=sponsor, conference=conf, override_contact_name="Jane Doe")
        assert override.is_empty is False

    def test_non_empty_override_contact_email(self):
        conf = _make_conference(slug="sponsor-notempty-email")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp")
        override = SponsorOverride.objects.create(
            sponsor=sponsor, conference=conf, override_contact_email="jane@example.com"
        )
        assert override.is_empty is False

    def test_non_empty_override_is_active(self):
        conf = _make_conference(slug="sponsor-notempty-active")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp")
        override = SponsorOverride.objects.create(sponsor=sponsor, conference=conf, override_is_active=False)
        assert override.is_empty is False

    def test_non_empty_override_level(self):
        conf = _make_conference(slug="sponsor-notempty-level")
        level_a = _make_level(conf, name="Gold")
        level_b = _make_level(conf, name="Silver")
        sponsor = _make_sponsor(conf, level_a, "Acme Corp")
        override = SponsorOverride.objects.create(sponsor=sponsor, conference=conf, override_level=level_b)
        assert override.is_empty is False


# ===========================================================================
# Sponsor effective_* properties
# ===========================================================================


@pytest.mark.django_db
class TestSponsorEffectiveProperties:
    def test_effective_name_no_override(self):
        conf = _make_conference(slug="sponsor-eff-name-none")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp")
        assert sponsor.effective_name == "Acme Corp"

    def test_effective_name_with_override(self):
        conf = _make_conference(slug="sponsor-eff-name-ov")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp")
        SponsorOverride.objects.create(sponsor=sponsor, conference=conf, override_name="New Acme Corp")
        assert sponsor.effective_name == "New Acme Corp"

    def test_effective_description_no_override(self):
        conf = _make_conference(slug="sponsor-eff-desc-none")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp", description="Original description")
        assert sponsor.effective_description == "Original description"

    def test_effective_description_with_override(self):
        conf = _make_conference(slug="sponsor-eff-desc-ov")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp", description="Original description")
        SponsorOverride.objects.create(sponsor=sponsor, conference=conf, override_description="New description")
        assert sponsor.effective_description == "New description"

    def test_effective_website_url_no_override(self):
        conf = _make_conference(slug="sponsor-eff-url-none")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp", website_url="https://acme.com")
        assert sponsor.effective_website_url == "https://acme.com"

    def test_effective_website_url_with_override(self):
        conf = _make_conference(slug="sponsor-eff-url-ov")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp", website_url="https://acme.com")
        SponsorOverride.objects.create(sponsor=sponsor, conference=conf, override_website_url="https://newacme.com")
        assert sponsor.effective_website_url == "https://newacme.com"

    def test_effective_logo_url_no_override(self):
        conf = _make_conference(slug="sponsor-eff-logo-none")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp", logo_url="https://acme.com/logo.png")
        assert sponsor.effective_logo_url == "https://acme.com/logo.png"

    def test_effective_logo_url_with_override(self):
        conf = _make_conference(slug="sponsor-eff-logo-ov")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp", logo_url="https://acme.com/logo.png")
        SponsorOverride.objects.create(
            sponsor=sponsor, conference=conf, override_logo_url="https://newacme.com/logo.png"
        )
        assert sponsor.effective_logo_url == "https://newacme.com/logo.png"

    def test_effective_contact_name_no_override(self):
        conf = _make_conference(slug="sponsor-eff-contact-none")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp", contact_name="John Doe")
        assert sponsor.effective_contact_name == "John Doe"

    def test_effective_contact_name_with_override(self):
        conf = _make_conference(slug="sponsor-eff-contact-ov")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp", contact_name="John Doe")
        SponsorOverride.objects.create(sponsor=sponsor, conference=conf, override_contact_name="Jane Doe")
        assert sponsor.effective_contact_name == "Jane Doe"

    def test_effective_contact_email_no_override(self):
        conf = _make_conference(slug="sponsor-eff-email-none")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp", contact_email="john@acme.com")
        assert sponsor.effective_contact_email == "john@acme.com"

    def test_effective_contact_email_with_override(self):
        conf = _make_conference(slug="sponsor-eff-email-ov")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp", contact_email="john@acme.com")
        SponsorOverride.objects.create(sponsor=sponsor, conference=conf, override_contact_email="jane@acme.com")
        assert sponsor.effective_contact_email == "jane@acme.com"

    def test_effective_is_active_no_override(self):
        conf = _make_conference(slug="sponsor-eff-active-none")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp", is_active=True)
        assert sponsor.effective_is_active is True

    def test_effective_is_active_with_override_false(self):
        conf = _make_conference(slug="sponsor-eff-active-ov-false")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp", is_active=True)
        SponsorOverride.objects.create(sponsor=sponsor, conference=conf, override_is_active=False)
        assert sponsor.effective_is_active is False

    def test_effective_is_active_with_override_true(self):
        conf = _make_conference(slug="sponsor-eff-active-ov-true")
        level = _make_level(conf)
        sponsor = _make_sponsor(conf, level, "Acme Corp", is_active=False)
        SponsorOverride.objects.create(sponsor=sponsor, conference=conf, override_is_active=True)
        assert sponsor.effective_is_active is True

    def test_effective_level_no_override(self):
        conf = _make_conference(slug="sponsor-eff-level-none")
        level_a = _make_level(conf, name="Gold")
        sponsor = _make_sponsor(conf, level_a, "Acme Corp")
        assert sponsor.effective_level == level_a

    def test_effective_level_with_override(self):
        conf = _make_conference(slug="sponsor-eff-level-ov")
        level_a = _make_level(conf, name="Gold")
        level_b = _make_level(conf, name="Silver")
        sponsor = _make_sponsor(conf, level_a, "Acme Corp")
        SponsorOverride.objects.create(sponsor=sponsor, conference=conf, override_level=level_b)
        assert sponsor.effective_level == level_b
