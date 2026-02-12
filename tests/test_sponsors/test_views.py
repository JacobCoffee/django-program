"""Tests for sponsors views."""

from datetime import date
from decimal import Decimal

import pytest
from django.test import Client

from django_program.conference.models import Conference
from django_program.sponsors.models import Sponsor, SponsorBenefit, SponsorLevel


@pytest.fixture
def conference() -> Conference:
    return Conference.objects.create(
        name="ViewCon",
        slug="viewcon",
        start_date=date(2027, 8, 1),
        end_date=date(2027, 8, 3),
        timezone="UTC",
    )


@pytest.fixture
def level(conference: Conference) -> SponsorLevel:
    return SponsorLevel.objects.create(
        conference=conference,
        name="Gold",
        cost=Decimal("5000.00"),
        comp_ticket_count=0,
    )


@pytest.fixture
def sponsor(conference: Conference, level: SponsorLevel) -> Sponsor:
    return Sponsor.objects.create(
        conference=conference,
        level=level,
        name="TestCo",
        is_active=True,
    )


@pytest.mark.django_db
def test_sponsor_list_view(client: Client, conference: Conference, sponsor: Sponsor):
    response = client.get(f"/{conference.slug}/sponsors/")
    assert response.status_code == 200
    assert sponsor in response.context["sponsors"]
    assert sponsor.level in response.context["levels"]


@pytest.mark.django_db
def test_sponsor_list_excludes_inactive(client: Client, conference: Conference, level: SponsorLevel):
    Sponsor.objects.create(
        conference=conference,
        level=level,
        name="InactiveCo",
        is_active=False,
    )
    response = client.get(f"/{conference.slug}/sponsors/")
    assert response.status_code == 200
    assert list(response.context["sponsors"]) == []


@pytest.mark.django_db
def test_sponsor_detail_view(client: Client, conference: Conference, sponsor: Sponsor):
    benefit = SponsorBenefit.objects.create(sponsor=sponsor, name="Logo placement")
    response = client.get(f"/{conference.slug}/sponsors/{sponsor.slug}/")
    assert response.status_code == 200
    assert response.context["sponsor"] == sponsor
    assert benefit in response.context["benefits"]


@pytest.mark.django_db
def test_sponsor_detail_404_for_inactive(client: Client, conference: Conference, level: SponsorLevel):
    inactive = Sponsor.objects.create(
        conference=conference,
        level=level,
        name="GoneCo",
        is_active=False,
    )
    response = client.get(f"/{conference.slug}/sponsors/{inactive.slug}/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_sponsor_detail_404_for_wrong_conference(client: Client, conference: Conference, sponsor: Sponsor):
    other = Conference.objects.create(
        name="OtherCon",
        slug="othercon",
        start_date=date(2027, 9, 1),
        end_date=date(2027, 9, 3),
    )
    response = client.get(f"/{other.slug}/sponsors/{sponsor.slug}/")
    assert response.status_code == 404
