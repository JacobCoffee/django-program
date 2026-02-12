"""Tests for the sync_pretalx management command."""

from datetime import date
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from django_program.conference.models import Conference

_PRETALX_SETTINGS = {
    "pretalx": {"base_url": "https://pretalx.example.com", "token": "tok"},
}


def _make_conference(slug="cmd-conf", pretalx_slug="cmd-event", **overrides):
    defaults = {
        "name": "Command Test Conf",
        "slug": slug,
        "start_date": date(2027, 5, 1),
        "end_date": date(2027, 5, 3),
        "timezone": "UTC",
        "pretalx_event_slug": pretalx_slug,
    }
    defaults.update(overrides)
    return Conference.objects.create(**defaults)


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_command_raises_when_conference_not_found(settings):
    settings.DJANGO_PROGRAM = _PRETALX_SETTINGS
    with pytest.raises(CommandError, match="not found"):
        call_command("sync_pretalx", conference="nonexistent")


@pytest.mark.django_db
def test_command_raises_when_no_pretalx_slug(settings):
    settings.DJANGO_PROGRAM = _PRETALX_SETTINGS
    _make_conference(slug="no-pretalx", pretalx_slug="")

    with pytest.raises(CommandError, match="has no pretalx_event_slug"):
        call_command("sync_pretalx", conference="no-pretalx")


# ---------------------------------------------------------------------------
# Default (sync_all) when no specific flags
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@patch("django_program.pretalx.management.commands.sync_pretalx.PretalxSyncService")
def test_command_default_runs_sync_all(mock_service_cls, settings):
    settings.DJANGO_PROGRAM = _PRETALX_SETTINGS
    conference = _make_conference(slug="cmd-all")

    mock_service = MagicMock()
    mock_service.sync_all.return_value = {
        "rooms": 3,
        "speakers": 10,
        "talks": 8,
        "schedule_slots": 5,
    }
    mock_service_cls.return_value = mock_service

    out = StringIO()
    call_command("sync_pretalx", conference="cmd-all", stdout=out)

    mock_service.sync_all.assert_called_once()
    output = out.getvalue()
    assert "3 rooms" in output
    assert "10 speakers" in output
    assert "8 talks" in output
    assert "5 schedule slots" in output


# ---------------------------------------------------------------------------
# --all flag
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@patch("django_program.pretalx.management.commands.sync_pretalx.PretalxSyncService")
def test_command_all_flag_runs_sync_all(mock_service_cls, settings):
    settings.DJANGO_PROGRAM = _PRETALX_SETTINGS
    _make_conference(slug="cmd-allflag")

    mock_service = MagicMock()
    mock_service.sync_all.return_value = {
        "rooms": 1,
        "speakers": 2,
        "talks": 3,
        "schedule_slots": 4,
    }
    mock_service_cls.return_value = mock_service

    out = StringIO()
    call_command("sync_pretalx", conference="cmd-allflag", sync_all=True, stdout=out)

    mock_service.sync_all.assert_called_once()


# ---------------------------------------------------------------------------
# Individual flags
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@patch("django_program.pretalx.management.commands.sync_pretalx.PretalxSyncService")
def test_command_rooms_only(mock_service_cls, settings):
    settings.DJANGO_PROGRAM = _PRETALX_SETTINGS
    _make_conference(slug="cmd-rooms")

    mock_service = MagicMock()
    mock_service.sync_rooms.return_value = 5
    mock_service_cls.return_value = mock_service

    out = StringIO()
    call_command("sync_pretalx", conference="cmd-rooms", rooms=True, stdout=out)

    mock_service.sync_rooms.assert_called_once()
    mock_service.sync_speakers.assert_not_called()
    mock_service.sync_talks.assert_not_called()
    mock_service.sync_schedule.assert_not_called()
    mock_service.sync_all.assert_not_called()
    assert "5 rooms" in out.getvalue()


@pytest.mark.django_db
@patch("django_program.pretalx.management.commands.sync_pretalx.PretalxSyncService")
def test_command_speakers_only(mock_service_cls, settings):
    settings.DJANGO_PROGRAM = _PRETALX_SETTINGS
    _make_conference(slug="cmd-speakers")

    mock_service = MagicMock()
    mock_service.sync_speakers.return_value = 7
    mock_service_cls.return_value = mock_service

    out = StringIO()
    call_command("sync_pretalx", conference="cmd-speakers", speakers=True, stdout=out)

    mock_service.sync_speakers.assert_called_once()
    mock_service.sync_rooms.assert_not_called()
    mock_service.sync_talks.assert_not_called()
    mock_service.sync_schedule.assert_not_called()
    assert "7 speakers" in out.getvalue()


@pytest.mark.django_db
@patch("django_program.pretalx.management.commands.sync_pretalx.PretalxSyncService")
def test_command_talks_only(mock_service_cls, settings):
    settings.DJANGO_PROGRAM = _PRETALX_SETTINGS
    _make_conference(slug="cmd-talks")

    mock_service = MagicMock()
    mock_service.sync_talks.return_value = 12
    mock_service_cls.return_value = mock_service

    out = StringIO()
    call_command("sync_pretalx", conference="cmd-talks", talks=True, stdout=out)

    mock_service.sync_talks.assert_called_once()
    mock_service.sync_rooms.assert_not_called()
    mock_service.sync_speakers.assert_not_called()
    mock_service.sync_schedule.assert_not_called()
    assert "12 talks" in out.getvalue()


@pytest.mark.django_db
@patch("django_program.pretalx.management.commands.sync_pretalx.PretalxSyncService")
def test_command_schedule_only(mock_service_cls, settings):
    settings.DJANGO_PROGRAM = _PRETALX_SETTINGS
    _make_conference(slug="cmd-schedule")

    mock_service = MagicMock()
    mock_service.sync_schedule.return_value = (9, 2)
    mock_service_cls.return_value = mock_service

    out = StringIO()
    call_command("sync_pretalx", conference="cmd-schedule", schedule=True, stdout=out)

    mock_service.sync_schedule.assert_called_once()
    mock_service.sync_rooms.assert_not_called()
    mock_service.sync_speakers.assert_not_called()
    mock_service.sync_talks.assert_not_called()
    assert "schedule slots" in out.getvalue()


# ---------------------------------------------------------------------------
# Multiple flags
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@patch("django_program.pretalx.management.commands.sync_pretalx.PretalxSyncService")
def test_command_multiple_flags(mock_service_cls, settings):
    settings.DJANGO_PROGRAM = _PRETALX_SETTINGS
    _make_conference(slug="cmd-multi")

    mock_service = MagicMock()
    mock_service.sync_rooms.return_value = 2
    mock_service.sync_talks.return_value = 4
    mock_service_cls.return_value = mock_service

    out = StringIO()
    call_command("sync_pretalx", conference="cmd-multi", rooms=True, talks=True, stdout=out)

    mock_service.sync_rooms.assert_called_once()
    mock_service.sync_talks.assert_called_once()
    mock_service.sync_speakers.assert_not_called()
    mock_service.sync_schedule.assert_not_called()
    mock_service.sync_all.assert_not_called()
    output = out.getvalue()
    assert "2 rooms" in output
    assert "4 talks" in output
