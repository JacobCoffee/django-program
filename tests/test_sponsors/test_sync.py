"""Tests for sponsor sync service."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

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


# ---- _fetch_placements auth retry and error paths ----


@pytest.mark.django_db
@patch("django_program.sponsors.sync.httpx.get")
def test_fetch_placements_retries_on_401_then_succeeds(mock_get, pyconus_conference):
    """Lines 134, 141-143: first auth candidate gets 401, second succeeds."""
    response_401 = httpx.Response(401, request=httpx.Request("GET", "http://test"))
    response_ok = MagicMock()
    response_ok.raise_for_status.return_value = None
    response_ok.json.return_value = SAMPLE_PLACEMENTS

    def side_effect(*args, **kwargs):
        auth = kwargs.get("headers", {}).get("Authorization", "")
        if "Token" in auth:
            raise httpx.HTTPStatusError("401", request=httpx.Request("GET", "http://test"), response=response_401)
        return response_ok

    mock_get.side_effect = side_effect

    service = SponsorSyncService(pyconus_conference)
    service._config = service._config.__class__(
        api_url=service._config.api_url,
        token="mytoken",
        auth_scheme="Token",
        publisher=service._config.publisher,
        flight=service._config.flight,
    )
    count = service.sync_sponsors()
    assert count == 2


@pytest.mark.django_db
@patch("django_program.sponsors.sync.httpx.get")
def test_fetch_placements_all_401_raises_runtime_error(mock_get, pyconus_conference):
    """Lines 150-158: all auth candidates return 401, raises RuntimeError."""
    response_401 = httpx.Response(401, request=httpx.Request("GET", "http://test"))

    mock_get.side_effect = httpx.HTTPStatusError(
        "401", request=httpx.Request("GET", "http://test"), response=response_401
    )

    service = SponsorSyncService(pyconus_conference)
    service._config = service._config.__class__(
        api_url=service._config.api_url,
        token="mytoken",
        auth_scheme="Token",
        publisher=service._config.publisher,
        flight=service._config.flight,
    )
    with pytest.raises(RuntimeError, match="Unauthorized"):
        service.sync_sponsors()


@pytest.mark.django_db
@patch("django_program.sponsors.sync.httpx.get")
def test_fetch_placements_non_401_http_error_raises_immediately(mock_get, pyconus_conference):
    """Lines 144-145: non-401 HTTPStatusError raises RuntimeError immediately."""
    response_403 = httpx.Response(403, request=httpx.Request("GET", "http://test"))

    mock_get.side_effect = httpx.HTTPStatusError(
        "403", request=httpx.Request("GET", "http://test"), response=response_403
    )

    service = SponsorSyncService(pyconus_conference)
    service._config = service._config.__class__(
        api_url=service._config.api_url,
        token="mytoken",
        auth_scheme="Token",
        publisher=service._config.publisher,
        flight=service._config.flight,
    )
    with pytest.raises(RuntimeError, match="Failed to fetch sponsors from PSF API"):
        service.sync_sponsors()


@pytest.mark.django_db
@patch("django_program.sponsors.sync.httpx.get")
def test_fetch_placements_returns_empty_for_unexpected_response(mock_get, pyconus_conference):
    """Line 165: response data that is neither list nor dict with 'results' returns []."""
    mock_response = mock_get.return_value
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"status": "ok"}

    service = SponsorSyncService(pyconus_conference)
    count = service.sync_sponsors()
    assert count == 0


@pytest.mark.django_db
@patch("django_program.sponsors.sync.httpx.get")
def test_fetch_placements_empty_candidates_raises(mock_get, pyconus_conference):
    """Lines 157-158: for-else with no auth candidates raises RuntimeError."""
    service = SponsorSyncService(pyconus_conference)
    with patch.object(service, "_authorization_candidates", return_value=[]):
        with pytest.raises(RuntimeError, match="Failed to fetch sponsors from PSF API"):
            service.sync_sponsors()


# ---- _authorization_candidates coverage (lines 174-184) ----


@pytest.mark.django_db
def test_authorization_candidates_no_token(pyconus_conference):
    """Line 171: empty token returns [None]."""
    service = SponsorSyncService(pyconus_conference)
    service._config = service._config.__class__(
        api_url=service._config.api_url,
        token="",
        auth_scheme="Token",
        publisher=service._config.publisher,
        flight=service._config.flight,
    )
    assert service._authorization_candidates() == [None]


@pytest.mark.django_db
def test_authorization_candidates_token_with_space(pyconus_conference):
    """Line 175: token containing a space is used as-is."""
    service = SponsorSyncService(pyconus_conference)
    service._config = service._config.__class__(
        api_url=service._config.api_url,
        token="Bearer alreadyformatted",
        auth_scheme="Token",
        publisher=service._config.publisher,
        flight=service._config.flight,
    )
    assert service._authorization_candidates() == ["Bearer alreadyformatted"]


@pytest.mark.django_db
def test_authorization_candidates_token_scheme(pyconus_conference):
    """Lines 178-181: Token scheme adds Bearer fallback."""
    service = SponsorSyncService(pyconus_conference)
    service._config = service._config.__class__(
        api_url=service._config.api_url,
        token="abc123",
        auth_scheme="Token",
        publisher=service._config.publisher,
        flight=service._config.flight,
    )
    candidates = service._authorization_candidates()
    assert candidates == ["Token abc123", "Bearer abc123"]


@pytest.mark.django_db
def test_authorization_candidates_bearer_scheme(pyconus_conference):
    """Lines 182-183: Bearer scheme adds Token fallback."""
    service = SponsorSyncService(pyconus_conference)
    service._config = service._config.__class__(
        api_url=service._config.api_url,
        token="abc123",
        auth_scheme="Bearer",
        publisher=service._config.publisher,
        flight=service._config.flight,
    )
    candidates = service._authorization_candidates()
    assert candidates == ["Bearer abc123", "Token abc123"]


@pytest.mark.django_db
def test_authorization_candidates_custom_scheme(pyconus_conference):
    """Custom scheme (not Token or Bearer) does not add fallback."""
    service = SponsorSyncService(pyconus_conference)
    service._config = service._config.__class__(
        api_url=service._config.api_url,
        token="abc123",
        auth_scheme="ApiKey",
        publisher=service._config.publisher,
        flight=service._config.flight,
    )
    candidates = service._authorization_candidates()
    assert candidates == ["ApiKey abc123"]
