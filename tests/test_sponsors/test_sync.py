"""Tests for sponsor sync service."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest

from django_program.conference.models import Conference
from django_program.sponsors.models import Sponsor, SponsorLevel
from django_program.sponsors.sync import SponsorSyncService


@pytest.fixture
def pyconus_conference(db):
    return Conference.objects.create(
        name="PyCon US 2027",
        slug="pycon-us-2027",
        start_date=date(2027, 5, 14),
        end_date=date(2027, 5, 22),
        timezone="America/New_York",
        pretalx_event_slug="pyconus2027",
    )


@pytest.fixture
def non_pyconus_conference(db):
    return Conference.objects.create(
        name="DjangoCon US 2027",
        slug="djangocon-us-2027",
        start_date=date(2027, 10, 1),
        end_date=date(2027, 10, 5),
        timezone="America/Chicago",
    )


SAMPLE_PLACEMENTS = [
    {
        "sponsor_id": 101,
        "sponsor": "Acme Corp",
        "sponsor_slug": "acme-corp",
        "level_name": "Diamond",
        "level_order": 0,
        "sponsor_url": "https://acme.example.com",
        "logo": "https://cdn.example.com/acme.png",
        "description": "Leading software company",
        "start_date": "2027-01-01",
        "end_date": "2027-12-31",
    },
    {
        "sponsor_id": 102,
        "sponsor": "Beta Inc",
        "sponsor_slug": "beta-inc",
        "level_name": "Gold",
        "level_order": 1,
        "sponsor_url": "https://beta.example.com",
        "logo": "https://cdn.example.com/beta.png",
        "description": "",
        "start_date": "2027-01-01",
        "end_date": "2027-12-31",
    },
]


@pytest.mark.django_db
def test_sync_service_rejects_non_pyconus(non_pyconus_conference):
    with pytest.raises(ValueError, match="does not support PSF sponsor sync"):
        SponsorSyncService(non_pyconus_conference)


@pytest.mark.django_db
@patch("django_program.sponsors.sync.httpx.get")
def test_sync_sponsors_creates_levels_and_sponsors(mock_get, pyconus_conference):
    mock_response = mock_get.return_value
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = SAMPLE_PLACEMENTS

    service = SponsorSyncService(pyconus_conference)
    count = service.sync_sponsors()

    assert count == 2
    assert SponsorLevel.objects.filter(conference=pyconus_conference).count() == 2
    assert Sponsor.objects.filter(conference=pyconus_conference).count() == 2

    acme = Sponsor.objects.get(conference=pyconus_conference, external_id="101")
    assert acme.name == "Acme Corp"
    assert acme.slug == "acme-corp"
    assert acme.website_url == "https://acme.example.com"
    assert acme.logo_url == "https://cdn.example.com/acme.png"
    assert acme.description == "Leading software company"
    assert acme.level.name == "Diamond"
    assert acme.level.order == 0

    beta = Sponsor.objects.get(conference=pyconus_conference, external_id="102")
    assert beta.slug == "beta-inc"
    assert beta.level.name == "Gold"
    assert beta.level.order == 1


@pytest.mark.django_db
@patch("django_program.sponsors.sync.httpx.get")
def test_sync_sponsors_updates_existing_by_external_id(mock_get, pyconus_conference):
    level = SponsorLevel.objects.create(conference=pyconus_conference, name="Old Level", cost=Decimal(1000))
    Sponsor.objects.create(
        conference=pyconus_conference,
        level=level,
        name="Old Name",
        external_id="101",
    )

    mock_response = mock_get.return_value
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = [SAMPLE_PLACEMENTS[0]]

    service = SponsorSyncService(pyconus_conference)
    count = service.sync_sponsors()

    assert count == 1
    assert Sponsor.objects.filter(conference=pyconus_conference).count() == 1
    acme = Sponsor.objects.get(conference=pyconus_conference, external_id="101")
    assert acme.name == "Acme Corp"


@pytest.mark.django_db
@patch("django_program.sponsors.sync.httpx.get")
def test_sync_sponsors_updates_existing_by_name(mock_get, pyconus_conference):
    level = SponsorLevel.objects.create(conference=pyconus_conference, name="Old Level", cost=Decimal(1000))
    Sponsor.objects.create(
        conference=pyconus_conference,
        level=level,
        name="Acme Corp",
    )

    mock_response = mock_get.return_value
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = [SAMPLE_PLACEMENTS[0]]

    service = SponsorSyncService(pyconus_conference)
    count = service.sync_sponsors()

    assert count == 1
    assert Sponsor.objects.filter(conference=pyconus_conference).count() == 1
    acme = Sponsor.objects.get(conference=pyconus_conference, name="Acme Corp")
    assert acme.external_id == "101"


@pytest.mark.django_db
@patch("django_program.sponsors.sync.httpx.get")
def test_sync_sponsors_skips_empty_names(mock_get, pyconus_conference):
    mock_response = mock_get.return_value
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = [
        {"sponsor_id": 999, "sponsor": "", "level_name": "Gold"},
    ]

    service = SponsorSyncService(pyconus_conference)
    count = service.sync_sponsors()

    assert count == 0
    assert Sponsor.objects.filter(conference=pyconus_conference).count() == 0


@pytest.mark.django_db
@patch("django_program.sponsors.sync.httpx.get")
def test_sync_all_returns_dict(mock_get, pyconus_conference):
    mock_response = mock_get.return_value
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = SAMPLE_PLACEMENTS

    service = SponsorSyncService(pyconus_conference)
    results = service.sync_all()

    assert results == {"sponsors": 2}


@pytest.mark.django_db
@patch("django_program.sponsors.sync.httpx.get")
def test_sync_sponsors_handles_paginated_response(mock_get, pyconus_conference):
    mock_response = mock_get.return_value
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"results": SAMPLE_PLACEMENTS, "count": 2}

    service = SponsorSyncService(pyconus_conference)
    count = service.sync_sponsors()

    assert count == 2


@pytest.mark.django_db
@patch("django_program.sponsors.sync.httpx.get")
def test_sync_sponsors_api_error_raises_runtime(mock_get, pyconus_conference):
    mock_get.side_effect = httpx.HTTPError("Connection failed")

    service = SponsorSyncService(pyconus_conference)
    with pytest.raises(RuntimeError, match="Failed to fetch sponsors from PSF API"):
        service.sync_sponsors()


@pytest.mark.django_db
@patch("django_program.sponsors.sync.httpx.get")
def test_sync_sponsors_default_level_name(mock_get, pyconus_conference):
    mock_response = mock_get.return_value
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = [
        {"sponsor_id": 200, "sponsor": "NoLevel Co", "level_name": ""},
    ]

    service = SponsorSyncService(pyconus_conference)
    count = service.sync_sponsors()

    assert count == 1
    sponsor = Sponsor.objects.get(conference=pyconus_conference, external_id="200")
    assert sponsor.level.name == "Sponsor"


@pytest.mark.django_db
@patch("django_program.sponsors.sync.httpx.get")
def test_sync_sponsors_updates_level_order(mock_get, pyconus_conference):
    SponsorLevel.objects.create(conference=pyconus_conference, name="Diamond", cost=Decimal(0), order=99)

    mock_response = mock_get.return_value
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = [SAMPLE_PLACEMENTS[0]]

    service = SponsorSyncService(pyconus_conference)
    service.sync_sponsors()

    level = SponsorLevel.objects.get(conference=pyconus_conference, name="Diamond")
    assert level.order == 0
