"""Tests for sponsor management views in the manage app."""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from django_program.conference.models import Conference
from django_program.sponsors.models import Sponsor, SponsorBenefit, SponsorLevel


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(username="admin", password="password", email="admin@test.com")


@pytest.fixture
def conference(db):
    return Conference.objects.create(
        name="SponsorMgmt Conf",
        slug="sponsor-mgmt",
        start_date=date(2027, 6, 1),
        end_date=date(2027, 6, 3),
        timezone="UTC",
        is_active=True,
    )


@pytest.fixture
def level(conference):
    return SponsorLevel.objects.create(
        conference=conference,
        name="Gold",
        slug="gold",
        cost=Decimal("5000.00"),
        comp_ticket_count=0,
    )


@pytest.fixture
def sponsor(conference, level):
    return Sponsor.objects.create(
        conference=conference,
        level=level,
        name="TestCorp",
        slug="testcorp",
        is_active=True,
    )


@pytest.fixture
def authed_client(client: Client, superuser):
    client.force_login(superuser)
    return client


# ---- Dashboard includes sponsors stat ----


@pytest.mark.django_db
def test_dashboard_includes_sponsor_stats(authed_client: Client, conference, sponsor):
    url = reverse("manage:dashboard", kwargs={"conference_slug": conference.slug})
    response = authed_client.get(url)
    assert response.status_code == 200
    assert response.context["stats"]["sponsors"] == 1


# ---- SponsorLevel views ----


@pytest.mark.django_db
def test_sponsor_level_list(authed_client: Client, conference, level):
    url = reverse("manage:sponsor-level-list", kwargs={"conference_slug": conference.slug})
    response = authed_client.get(url)
    assert response.status_code == 200
    assert level in response.context["levels"]


@pytest.mark.django_db
def test_sponsor_level_create(authed_client: Client, conference):
    url = reverse("manage:sponsor-level-add", kwargs={"conference_slug": conference.slug})
    response = authed_client.post(
        url,
        {
            "name": "Silver",
            "slug": "silver",
            "cost": "2000.00",
            "comp_ticket_count": "2",
            "order": "1",
        },
    )
    assert response.status_code == 302
    assert SponsorLevel.objects.filter(conference=conference, slug="silver").exists()


@pytest.mark.django_db
def test_sponsor_level_create_get(authed_client: Client, conference):
    url = reverse("manage:sponsor-level-add", kwargs={"conference_slug": conference.slug})
    response = authed_client.get(url)
    assert response.status_code == 200
    assert response.context["is_create"] is True


@pytest.mark.django_db
def test_sponsor_level_edit(authed_client: Client, conference, level):
    url = reverse("manage:sponsor-level-edit", kwargs={"conference_slug": conference.slug, "pk": level.pk})
    response = authed_client.post(
        url,
        {
            "name": "Platinum",
            "slug": "gold",
            "cost": "10000.00",
            "comp_ticket_count": "5",
            "order": "0",
        },
    )
    assert response.status_code == 302
    level.refresh_from_db()
    assert level.name == "Platinum"


@pytest.mark.django_db
def test_sponsor_level_edit_get(authed_client: Client, conference, level):
    url = reverse("manage:sponsor-level-edit", kwargs={"conference_slug": conference.slug, "pk": level.pk})
    response = authed_client.get(url)
    assert response.status_code == 200
    assert response.context["level"] == level


# ---- Sponsor views ----


@pytest.mark.django_db
def test_sponsor_manage_list(authed_client: Client, conference, sponsor):
    url = reverse("manage:sponsor-manage-list", kwargs={"conference_slug": conference.slug})
    response = authed_client.get(url)
    assert response.status_code == 200
    assert sponsor in response.context["sponsors"]


@pytest.mark.django_db
def test_sponsor_create(authed_client: Client, conference, level):
    url = reverse("manage:sponsor-add", kwargs={"conference_slug": conference.slug})
    response = authed_client.post(
        url,
        {
            "name": "NewCorp",
            "slug": "newcorp",
            "level": level.pk,
            "is_active": "on",
        },
    )
    assert response.status_code == 302
    assert Sponsor.objects.filter(conference=conference, slug="newcorp").exists()


@pytest.mark.django_db
def test_sponsor_create_get(authed_client: Client, conference, level):
    url = reverse("manage:sponsor-add", kwargs={"conference_slug": conference.slug})
    response = authed_client.get(url)
    assert response.status_code == 200
    assert response.context["is_create"] is True


@pytest.mark.django_db
def test_sponsor_edit(authed_client: Client, conference, sponsor, level):
    url = reverse("manage:sponsor-edit", kwargs={"conference_slug": conference.slug, "pk": sponsor.pk})
    response = authed_client.post(
        url,
        {
            "name": "UpdatedCorp",
            "slug": "testcorp",
            "level": level.pk,
            "is_active": "on",
        },
    )
    assert response.status_code == 302
    sponsor.refresh_from_db()
    assert sponsor.name == "UpdatedCorp"


@pytest.mark.django_db
def test_sponsor_edit_get_with_benefits(authed_client: Client, conference, sponsor):
    benefit = SponsorBenefit.objects.create(sponsor=sponsor, name="Logo on site")
    url = reverse("manage:sponsor-edit", kwargs={"conference_slug": conference.slug, "pk": sponsor.pk})
    response = authed_client.get(url)
    assert response.status_code == 200
    assert response.context["sponsor"] == sponsor
    assert benefit in response.context["benefits"]
