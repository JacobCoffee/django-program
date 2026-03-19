"""Tests for sponsors models."""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from django_program.conference.models import Conference
from django_program.registration.models import AddOn, TicketType
from django_program.sponsors.models import BulkPurchase, Sponsor, SponsorBenefit, SponsorLevel


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


@pytest.mark.django_db
def test_sponsor_external_id_field(conference: Conference, level: SponsorLevel):
    sponsor = Sponsor.objects.create(
        conference=conference,
        level=level,
        name="ExtID Corp",
        external_id="psf-123",
    )
    sponsor.refresh_from_db()
    assert sponsor.external_id == "psf-123"


@pytest.mark.django_db
def test_sponsor_external_id_default(sponsor: Sponsor):
    assert sponsor.external_id == ""


@pytest.mark.django_db
def test_sponsor_logo_url_field(conference: Conference, level: SponsorLevel):
    sponsor = Sponsor.objects.create(
        conference=conference,
        level=level,
        name="LogoURL Corp",
        logo_url="https://example.com/logo.png",
    )
    sponsor.refresh_from_db()
    assert sponsor.logo_url == "https://example.com/logo.png"


@pytest.mark.django_db
def test_sponsor_logo_url_default(sponsor: Sponsor):
    assert sponsor.logo_url == ""


@pytest.mark.django_db
def test_sponsor_clean_cross_conference_level_raises(conference: Conference, level: SponsorLevel):
    """Lines 108-109: clean() rejects a sponsor whose level belongs to a different conference."""
    other_conference = Conference.objects.create(
        name="OtherCon",
        slug="othercon",
        start_date=date(2027, 9, 1),
        end_date=date(2027, 9, 3),
        timezone="UTC",
    )
    sponsor = Sponsor(
        conference=other_conference,
        level=level,
        name="Cross Conference Corp",
    )
    with pytest.raises(ValidationError, match="same conference"):
        sponsor.clean()


# ---------------------------------------------------------------------------
# BulkPurchase validation
# ---------------------------------------------------------------------------


@pytest.fixture
def ticket_type(conference: Conference) -> TicketType:
    return TicketType.objects.create(
        conference=conference,
        name="Regular",
        slug="regular",
        price=Decimal("349.00"),
        bulk_enabled=True,
    )


@pytest.fixture
def addon(conference: Conference) -> AddOn:
    return AddOn.objects.create(
        conference=conference,
        name="T-Shirt",
        slug="tshirt",
        price=Decimal("35.00"),
        bulk_enabled=True,
    )


@pytest.mark.django_db
def test_bulk_purchase_clean_cross_conference_sponsor(conference: Conference, level: SponsorLevel):
    """Rejects a bulk purchase whose sponsor belongs to a different conference."""
    other = Conference.objects.create(
        name="OtherCon", slug="othercon", start_date=date(2027, 9, 1), end_date=date(2027, 9, 3), timezone="UTC"
    )
    sponsor = Sponsor.objects.create(
        conference=other, level=SponsorLevel.objects.create(conference=other, name="Gold", cost=0), name="Other Corp"
    )
    bp = BulkPurchase(
        conference=conference, sponsor=sponsor, quantity=5, unit_price=Decimal(100), total_amount=Decimal(500)
    )
    with pytest.raises(ValidationError, match="same conference"):
        bp.clean()


@pytest.mark.django_db
def test_bulk_purchase_clean_cross_conference_ticket_type(conference: Conference, sponsor: Sponsor):
    """Rejects a bulk purchase whose ticket type belongs to a different conference."""
    other = Conference.objects.create(
        name="OtherCon", slug="othercon", start_date=date(2027, 9, 1), end_date=date(2027, 9, 3), timezone="UTC"
    )
    other_tt = TicketType.objects.create(
        conference=other, name="Other", slug="other", price=Decimal(99), bulk_enabled=True
    )
    bp = BulkPurchase(
        conference=conference,
        sponsor=sponsor,
        ticket_type=other_tt,
        quantity=5,
        unit_price=Decimal(100),
        total_amount=Decimal(500),
    )
    with pytest.raises(ValidationError, match="same conference"):
        bp.clean()


@pytest.mark.django_db
def test_bulk_purchase_clean_cross_conference_addon(conference: Conference, sponsor: Sponsor):
    """Rejects a bulk purchase whose addon belongs to a different conference."""
    other = Conference.objects.create(
        name="OtherCon", slug="othercon", start_date=date(2027, 9, 1), end_date=date(2027, 9, 3), timezone="UTC"
    )
    other_addon = AddOn.objects.create(
        conference=other, name="Other", slug="other", price=Decimal(10), bulk_enabled=True
    )
    bp = BulkPurchase(
        conference=conference,
        sponsor=sponsor,
        addon=other_addon,
        quantity=5,
        unit_price=Decimal(100),
        total_amount=Decimal(500),
    )
    with pytest.raises(ValidationError, match="same conference"):
        bp.clean()


@pytest.mark.django_db
def test_bulk_purchase_clean_rejects_non_bulk_ticket(conference: Conference, sponsor: Sponsor):
    """Rejects a ticket type that doesn't have bulk_enabled."""
    tt = TicketType.objects.create(
        conference=conference, name="NoBulk", slug="nobulk", price=Decimal(99), bulk_enabled=False
    )
    bp = BulkPurchase(
        conference=conference,
        sponsor=sponsor,
        ticket_type=tt,
        quantity=5,
        unit_price=Decimal(100),
        total_amount=Decimal(500),
    )
    with pytest.raises(ValidationError, match="bulk purchasing enabled"):
        bp.clean()


@pytest.mark.django_db
def test_bulk_purchase_clean_rejects_non_bulk_addon(conference: Conference, sponsor: Sponsor):
    """Rejects an addon that doesn't have bulk_enabled."""
    ao = AddOn.objects.create(
        conference=conference, name="NoBulk", slug="nobulk", price=Decimal(10), bulk_enabled=False
    )
    bp = BulkPurchase(
        conference=conference, sponsor=sponsor, addon=ao, quantity=5, unit_price=Decimal(100), total_amount=Decimal(500)
    )
    with pytest.raises(ValidationError, match="bulk purchasing enabled"):
        bp.clean()


@pytest.mark.django_db
def test_bulk_purchase_clean_valid(conference: Conference, sponsor: Sponsor, ticket_type: TicketType):
    """Valid bulk purchase passes clean()."""
    bp = BulkPurchase(
        conference=conference,
        sponsor=sponsor,
        ticket_type=ticket_type,
        quantity=5,
        unit_price=Decimal(100),
        total_amount=Decimal(500),
    )
    bp.clean()


@pytest.mark.django_db
def test_bulk_purchase_str(conference: Conference, sponsor: Sponsor):
    bp = BulkPurchase.objects.create(
        conference=conference, sponsor=sponsor, quantity=10, unit_price=Decimal(50), total_amount=Decimal(500)
    )
    assert "x10" in str(bp)
