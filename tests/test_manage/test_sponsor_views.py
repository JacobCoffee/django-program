"""Tests for sponsor management views in the manage app."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

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
        cost=Decimal("5000.00"),
        comp_ticket_count=0,
    )


@pytest.fixture
def sponsor(conference, level):
    return Sponsor.objects.create(
        conference=conference,
        level=level,
        name="TestCorp",
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
    assert response.context["is_synced"] is False


@pytest.mark.django_db
def test_sponsor_edit_synced_fields_locked(authed_client: Client, conference, level):
    synced_sponsor = Sponsor.objects.create(conference=conference, level=level, name="PSF Corp", external_id="psf-42")
    url = reverse("manage:sponsor-edit", kwargs={"conference_slug": conference.slug, "pk": synced_sponsor.pk})
    response = authed_client.get(url)
    assert response.status_code == 200
    assert response.context["is_synced"] is True
    form = response.context["form"]
    assert form.fields["name"].disabled is True
    assert form.fields["level"].disabled is True
    assert form.fields["website_url"].disabled is True
    assert form.fields["description"].disabled is True
    assert form.fields["contact_name"].disabled is False
    assert form.fields["contact_email"].disabled is False
    assert form.fields["is_active"].disabled is False


@pytest.mark.django_db
def test_sponsor_edit_unsynced_fields_editable(authed_client: Client, conference, sponsor):
    url = reverse("manage:sponsor-edit", kwargs={"conference_slug": conference.slug, "pk": sponsor.pk})
    response = authed_client.get(url)
    form = response.context["form"]
    assert form.fields["name"].disabled is False
    assert form.fields["level"].disabled is False


# ---- PSF Sponsor Sync views ----


@pytest.fixture
def pyconus_conference(db):
    return Conference.objects.create(
        name="PyCon US 2027",
        slug="pycon-us-2027",
        start_date=date(2027, 5, 14),
        end_date=date(2027, 5, 22),
        timezone="America/New_York",
        pretalx_event_slug="pyconus2027",
        is_active=True,
    )


@pytest.mark.django_db
def test_dashboard_shows_psf_sync_for_pyconus(authed_client: Client, pyconus_conference):
    url = reverse("manage:dashboard", kwargs={"conference_slug": pyconus_conference.slug})
    response = authed_client.get(url)
    assert response.status_code == 200
    assert response.context["has_psf_sponsor_sync"] is True


@pytest.mark.django_db
def test_dashboard_hides_psf_sync_for_non_pyconus(authed_client: Client, conference):
    url = reverse("manage:dashboard", kwargs={"conference_slug": conference.slug})
    response = authed_client.get(url)
    assert response.status_code == 200
    assert response.context["has_psf_sponsor_sync"] is False


@pytest.mark.django_db
@patch("django_program.manage.views.SponsorSyncService")
def test_sync_sponsors_view_success(mock_service_cls, authed_client: Client, pyconus_conference):
    mock_service = mock_service_cls.return_value
    mock_service.sync_all.return_value = {"sponsors": 5}

    url = reverse("manage:sync-sponsors", kwargs={"conference_slug": pyconus_conference.slug})
    response = authed_client.post(url)

    assert response.status_code == 302
    mock_service.sync_all.assert_called_once()


@pytest.mark.django_db
@patch("django_program.manage.views.SponsorSyncService")
def test_sync_sponsors_view_value_error(mock_service_cls, authed_client: Client, conference):
    mock_service_cls.side_effect = ValueError("Not supported")

    url = reverse("manage:sync-sponsors", kwargs={"conference_slug": conference.slug})
    response = authed_client.post(url)

    assert response.status_code == 302


@pytest.mark.django_db
@patch("django_program.manage.views.SponsorSyncService")
def test_sync_sponsors_view_runtime_error(mock_service_cls, authed_client: Client, pyconus_conference):
    mock_service = mock_service_cls.return_value
    mock_service.sync_all.side_effect = RuntimeError("API failed")

    url = reverse("manage:sync-sponsors", kwargs={"conference_slug": pyconus_conference.slug})
    response = authed_client.post(url)

    assert response.status_code == 302
