"""Tests for sponsors auto-voucher generation signal."""

from datetime import date
from decimal import Decimal

import pytest

from django_program.conference.models import Conference
from django_program.registration.models import Voucher
from django_program.sponsors.models import Sponsor, SponsorLevel


@pytest.fixture
def conference() -> Conference:
    return Conference.objects.create(
        name="SignalCon",
        slug="signalcon",
        start_date=date(2027, 7, 1),
        end_date=date(2027, 7, 3),
        timezone="UTC",
    )


@pytest.mark.django_db
def test_comp_vouchers_created_on_sponsor_create(conference: Conference):
    level = SponsorLevel.objects.create(
        conference=conference,
        name="Platinum",
        slug="platinum",
        cost=Decimal("10000.00"),
        comp_ticket_count=3,
    )

    Sponsor.objects.create(
        conference=conference,
        level=level,
        name="BigCo",
        slug="bigco",
    )

    vouchers = Voucher.objects.filter(conference=conference, code__startswith="SPONSOR-BIGCO-")
    assert vouchers.count() == 3
    for v in vouchers:
        assert v.voucher_type == Voucher.VoucherType.COMP
        assert v.max_uses == 1
        assert v.unlocks_hidden_tickets is True
        assert v.is_active is True


@pytest.mark.django_db
def test_no_vouchers_when_comp_count_zero(conference: Conference):
    level = SponsorLevel.objects.create(
        conference=conference,
        name="Bronze",
        slug="bronze",
        cost=Decimal("500.00"),
        comp_ticket_count=0,
    )

    Sponsor.objects.create(
        conference=conference,
        level=level,
        name="SmallCo",
        slug="smallco",
    )

    assert Voucher.objects.filter(conference=conference, code__startswith="SPONSOR-SMALLCO-").count() == 0


@pytest.mark.django_db
def test_no_vouchers_on_sponsor_update(conference: Conference):
    level = SponsorLevel.objects.create(
        conference=conference,
        name="Silver",
        slug="silver",
        cost=Decimal("2000.00"),
        comp_ticket_count=2,
    )

    sponsor = Sponsor.objects.create(
        conference=conference,
        level=level,
        name="MidCo",
        slug="midco",
    )
    assert Voucher.objects.filter(conference=conference, code__startswith="SPONSOR-MIDCO-").count() == 2

    sponsor.name = "MidCo Updated"
    sponsor.save()
    assert Voucher.objects.filter(conference=conference, code__startswith="SPONSOR-MIDCO-").count() == 2


@pytest.mark.django_db
def test_bulk_create_ignore_conflicts_is_idempotent(conference: Conference):
    level = SponsorLevel.objects.create(
        conference=conference,
        name="Gold",
        slug="gold",
        cost=Decimal("5000.00"),
        comp_ticket_count=2,
    )

    Voucher.objects.create(
        conference=conference,
        code="SPONSOR-PRECO-1",
        voucher_type=Voucher.VoucherType.COMP,
        max_uses=1,
    )

    Sponsor.objects.create(
        conference=conference,
        level=level,
        name="PreCo",
        slug="preco",
    )

    assert Voucher.objects.filter(conference=conference, code__startswith="SPONSOR-PRECO-").count() == 2
