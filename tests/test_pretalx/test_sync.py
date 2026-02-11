from datetime import date
from unittest.mock import patch

import pytest

from django_program.conference.models import Conference
from django_program.pretalx.models import Room, Speaker, Talk
from django_program.pretalx.sync import PretalxSyncService
from pretalx_client.models import PretalxTalk


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
def test_sync_talks_clears_speakers_when_api_returns_empty_list(settings):
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
    service._rooms = {}
    service._room_names = {}
    service._submission_types = {}
    service._tracks = {}
    service.client.fetch_talks = lambda **kwargs: [
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


@pytest.mark.django_db
def test_sync_rooms_creates_room_objects(settings):
    settings.DJANGO_PROGRAM = {"pretalx": {"base_url": "https://pretalx.example.com", "token": None}}
    conference = Conference.objects.create(
        name="PyCon Test",
        slug="pycon-rooms",
        start_date=date(2027, 5, 1),
        end_date=date(2027, 5, 3),
        timezone="UTC",
        pretalx_event_slug="pycon-rooms-2027",
    )

    service = PretalxSyncService(conference)
    service._submission_types = {}
    service._tracks = {}
    service.client.fetch_rooms_full = lambda: [
        {"id": 1, "name": {"en": "Hall A"}, "description": {"en": "Main hall"}, "capacity": 500, "position": 0},
        {"id": 2, "name": {"en": "Room 101"}, "description": None, "capacity": 50, "position": 1},
    ]

    count = service.sync_rooms()

    assert count == 2
    assert Room.objects.filter(conference=conference).count() == 2
    hall_a = Room.objects.get(conference=conference, pretalx_id=1)
    assert hall_a.name == "Hall A"
    assert hall_a.description == "Main hall"
    assert hall_a.capacity == 500
    assert hall_a.position == 0


@pytest.mark.django_db
def test_sync_talks_links_room_fk(settings):
    settings.DJANGO_PROGRAM = {"pretalx": {"base_url": "https://pretalx.example.com", "token": None}}
    conference = Conference.objects.create(
        name="PyCon Test",
        slug="pycon-room-fk",
        start_date=date(2027, 5, 1),
        end_date=date(2027, 5, 3),
        timezone="UTC",
        pretalx_event_slug="pycon-room-fk-2027",
    )
    room = Room.objects.create(
        conference=conference,
        pretalx_id=1,
        name="Hall A",
    )

    service = PretalxSyncService(conference)
    service._rooms = {1: room}
    service._room_names = {1: "Hall A"}
    service._submission_types = {}
    service._tracks = {}
    service.client.fetch_talks = lambda **kwargs: [
        PretalxTalk(
            code="TALK1",
            title="My Talk",
            room="Hall A",
            state="confirmed",
        )
    ]

    count = service.sync_talks()

    assert count == 1
    talk = Talk.objects.get(conference=conference, pretalx_code="TALK1")
    assert talk.room == room
