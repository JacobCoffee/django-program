"""Tests for the sync_sponsors management command."""

from datetime import date
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from django_program.conference.models import Conference


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


@pytest.mark.django_db
@patch("django_program.sponsors.management.commands.sync_sponsors.SponsorSyncService")
def test_sync_sponsors_command_success(mock_service_cls, pyconus_conference):
    """Happy path: command syncs sponsors and reports count."""
    mock_service = mock_service_cls.return_value
    mock_service.sync_all.return_value = {"sponsors": 5}

    call_command("sync_sponsors", conference="pycon-us-2027")

    mock_service_cls.assert_called_once_with(pyconus_conference)
    mock_service.sync_all.assert_called_once()


@pytest.mark.django_db
def test_sync_sponsors_command_conference_not_found():
    """Command raises CommandError for nonexistent conference slug."""
    with pytest.raises(CommandError, match="not found"):
        call_command("sync_sponsors", conference="nonexistent-conf")


@pytest.mark.django_db
def test_sync_sponsors_command_non_pyconus_conference(non_pyconus_conference):
    """Command raises CommandError when SponsorSyncService raises ValueError."""
    with pytest.raises(CommandError, match="does not support PSF sponsor sync"):
        call_command("sync_sponsors", conference="djangocon-us-2027")


@pytest.mark.django_db
@patch("django_program.sponsors.management.commands.sync_sponsors.SponsorSyncService")
def test_sync_sponsors_command_runtime_error(mock_service_cls, pyconus_conference):
    """Command raises CommandError when sync_all raises RuntimeError."""
    mock_service = mock_service_cls.return_value
    mock_service.sync_all.side_effect = RuntimeError("API connection failed")

    with pytest.raises(CommandError, match="API connection failed"):
        call_command("sync_sponsors", conference="pycon-us-2027")
