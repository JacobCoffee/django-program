"""Tests for sponsors models."""

from datetime import date
from decimal import Decimal

import pytest

from django_program.conference.models import Conference
from django_program.sponsors.models import Sponsor, SponsorBenefit, SponsorLevel


@pytest.fixture
def conference() -> Conference:
    return Conference.objects.create(
        name="SponsorCon",
        slug="sponsorcon",
        start_date=date(2027, 6, 1),
        end_date=date(2027, 6, 3),
        timezone="UTC",
    )


@pytest.fixture
def level(conference: Conference) -> SponsorLevel:
    return SponsorLevel.objects.create(
        conference=conference,
        name="Gold",
        cost=Decimal("5000.00"),
    )


@pytest.fixture
def sponsor(conference: Conference, level: SponsorLevel) -> Sponsor:
    return Sponsor.objects.create(
        conference=conference,
        level=level,
        name="Acme Corp",
    )


@pytest.mark.django_db
def test_sponsor_level_str(level: SponsorLevel):
    assert str(level) == "Gold (sponsorcon)"


@pytest.mark.django_db
def test_sponsor_str(sponsor: Sponsor):
    assert str(sponsor) == "Acme Corp (Gold)"


@pytest.mark.django_db
def test_sponsor_benefit_str(sponsor: Sponsor):
    benefit = SponsorBenefit.objects.create(
        sponsor=sponsor,
        name="Logo on website",
    )
    assert str(benefit) == "Logo on website - Acme Corp"
