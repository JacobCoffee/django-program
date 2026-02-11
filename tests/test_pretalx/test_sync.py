from datetime import date
from unittest.mock import patch

import pytest

from django_program.conference.models import Conference
from django_program.pretalx.client import PretalxTalk
from django_program.pretalx.models import Speaker, Talk
from django_program.pretalx.sync import PretalxSyncService


@pytest.mark.django_db
def test_sync_service_uses_django_program_pretalx_config(settings):
    settings.DJANGO_PROGRAM = {
        "pretalx": {
            "base_url": "https://pretalx.example.com/api",
            "token": "pretalx-token-123",
        }
    }
    conference = Conference.objects.create(
        name="PyCon Test",
        slug="pycon-test",
        start_date=date(2027, 5, 1),
        end_date=date(2027, 5, 3),
        timezone="UTC",
        pretalx_event_slug="pycon-test-2027",
    )

    with patch("django_program.pretalx.sync.PretalxClient") as mock_client_cls:
        PretalxSyncService(conference)

    mock_client_cls.assert_called_once_with(
        "pycon-test-2027",
        base_url="https://pretalx.example.com/api",
        api_token="pretalx-token-123",
    )


@pytest.mark.django_db
def test_sync_talks_clears_speakers_when_api_returns_none(settings):
    settings.DJANGO_PROGRAM = {"pretalx": {"base_url": "https://pretalx.example.com", "token": None}}
    conference = Conference.objects.create(
        name="PyCon Test",
        slug="pycon-sync-talks",
        start_date=date(2027, 5, 1),
        end_date=date(2027, 5, 3),
        timezone="UTC",
        pretalx_event_slug="pycon-sync-2027",
    )
    speaker = Speaker.objects.create(
        conference=conference,
        pretalx_code="SPK1",
        name="Speaker One",
    )
    talk = Talk.objects.create(
        conference=conference,
        pretalx_code="TALK1",
        title="Initial Title",
    )
    talk.speakers.add(speaker)

    service = PretalxSyncService(conference)
    service.client.fetch_talks = lambda: [
        PretalxTalk(
            code="TALK1",
            title="Updated Title",
            speaker_codes=[],
            state="confirmed",
        )
    ]

    count = service.sync_talks()

    talk.refresh_from_db()
    assert count == 1
    assert talk.title == "Updated Title"
    assert talk.speakers.count() == 0
