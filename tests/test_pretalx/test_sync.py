from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model

from django_program.conference.models import Conference
from django_program.pretalx.models import Room, ScheduleSlot, Speaker, Talk
from django_program.pretalx.sync import (
    PretalxSyncService,
    _build_speaker,
    _classify_slot,
    _parse_iso_datetime,
)
from django_program.programs.models import Activity
from pretalx_client.models import PretalxSlot, PretalxSpeaker, PretalxTalk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PRETALX_SETTINGS = {
    "pretalx": {"base_url": "https://pretalx.example.com", "token": "tok"},
}


def _make_conference(slug="test-conf", pretalx_slug="test-event", **overrides):
    """Create and return a Conference with sensible defaults."""
    defaults = {
        "name": "Test Conf",
        "slug": slug,
        "start_date": date(2027, 5, 1),
        "end_date": date(2027, 5, 3),
        "timezone": "UTC",
        "pretalx_event_slug": pretalx_slug,
    }
    defaults.update(overrides)
    return Conference.objects.create(**defaults)


def _make_service(conference, settings):
    """Build a PretalxSyncService with a mocked PretalxClient."""
    settings.DJANGO_PROGRAM = _PRETALX_SETTINGS
    service = PretalxSyncService(conference)
    service._rooms = {}
    service._room_names = {}
    service._submission_types = {}
    service._tracks = {}
    service._tags = {}
    return service


# ===========================================================================
# PretalxSyncService.__init__
# ===========================================================================


@pytest.mark.django_db
def test_sync_service_uses_django_program_pretalx_config(settings):
    settings.DJANGO_PROGRAM = {
        "pretalx": {
            "base_url": "https://pretalx.example.com/api",
            "token": "pretalx-token-123",
        }
    }
    conference = _make_conference(slug="pycon-test", pretalx_slug="pycon-test-2027")

    with patch("django_program.pretalx.sync.PretalxClient") as mock_client_cls:
        PretalxSyncService(conference)

    mock_client_cls.assert_called_once_with(
        "pycon-test-2027",
        base_url="https://pretalx.example.com/api",
        api_token="pretalx-token-123",
    )


@pytest.mark.django_db
def test_init_raises_when_no_pretalx_event_slug(settings):
    settings.DJANGO_PROGRAM = _PRETALX_SETTINGS
    conference = _make_conference(slug="no-slug", pretalx_slug="")

    with pytest.raises(ValueError, match="has no pretalx_event_slug configured"):
        PretalxSyncService(conference)


# ===========================================================================
# _ensure_mappings
# ===========================================================================


@pytest.mark.django_db
def test_ensure_mappings_fetches_submission_types_tracks_and_tags(settings):
    settings.DJANGO_PROGRAM = _PRETALX_SETTINGS
    conference = _make_conference(slug="map-test")
    service = PretalxSyncService(conference)

    service.client.fetch_submission_types = MagicMock(return_value={1: "Talk"})
    service.client.fetch_tracks = MagicMock(return_value={2: "Python"})
    service.client.fetch_tags = MagicMock(return_value={3: "AI"})

    service._ensure_mappings()

    assert service._submission_types == {1: "Talk"}
    assert service._tracks == {2: "Python"}
    assert service._tags == {3: "AI"}
    service.client.fetch_submission_types.assert_called_once()
    service.client.fetch_tracks.assert_called_once()
    service.client.fetch_tags.assert_called_once()


@pytest.mark.django_db
def test_ensure_mappings_handles_tags_runtime_error(settings):
    settings.DJANGO_PROGRAM = _PRETALX_SETTINGS
    conference = _make_conference(slug="map-err")
    service = PretalxSyncService(conference)

    service.client.fetch_submission_types = MagicMock(return_value={})
    service.client.fetch_tracks = MagicMock(return_value={})
    service.client.fetch_tags = MagicMock(side_effect=RuntimeError("404"))

    service._ensure_mappings()

    assert service._tags == {}


@pytest.mark.django_db
def test_ensure_mappings_caches_room_names(settings):
    settings.DJANGO_PROGRAM = _PRETALX_SETTINGS
    conference = _make_conference(slug="map-rooms")
    room = Room.objects.create(conference=conference, pretalx_id=10, name="Hall A")

    service = PretalxSyncService(conference)
    service.client.fetch_submission_types = MagicMock(return_value={})
    service.client.fetch_tracks = MagicMock(return_value={})
    service.client.fetch_tags = MagicMock(return_value={})

    service._ensure_mappings()

    assert service._rooms == {10: room}
    assert service._room_names == {10: "Hall A"}


@pytest.mark.django_db
def test_ensure_mappings_only_fetches_once(settings):
    settings.DJANGO_PROGRAM = _PRETALX_SETTINGS
    conference = _make_conference(slug="map-once")
    service = PretalxSyncService(conference)

    service.client.fetch_submission_types = MagicMock(return_value={})
    service.client.fetch_tracks = MagicMock(return_value={})
    service.client.fetch_tags = MagicMock(return_value={})

    service._ensure_mappings()
    service._ensure_mappings()

    assert service.client.fetch_submission_types.call_count == 1
    assert service.client.fetch_tracks.call_count == 1
    assert service.client.fetch_tags.call_count == 1


# ===========================================================================
# sync_rooms
# ===========================================================================


@pytest.mark.django_db
def test_sync_rooms_creates_room_objects(settings):
    settings.DJANGO_PROGRAM = _PRETALX_SETTINGS
    conference = _make_conference(slug="pycon-rooms", pretalx_slug="pycon-rooms-2027")

    service = PretalxSyncService(conference)
    service._submission_types = {}
    service._tracks = {}
    service.client.fetch_rooms_full = lambda: [
        {"id": 1, "name": {"en": "Hall A"}, "description": {"en": "Main hall"}, "capacity": 500, "position": 0},
        {"id": 2, "name": {"en": "Room 101"}, "description": None, "capacity": 50, "position": 1},
    ]
    service.client.fetch_tags = MagicMock(return_value={})

    count = service.sync_rooms()

    assert count == 2
    assert Room.objects.filter(conference=conference).count() == 2
    hall_a = Room.objects.get(conference=conference, pretalx_id=1)
    assert hall_a.name == "Hall A"
    assert hall_a.description == "Main hall"
    assert hall_a.capacity == 500
    assert hall_a.position == 0


@pytest.mark.django_db
def test_sync_rooms_skips_entries_without_id(settings):
    conference = _make_conference(slug="rooms-noid")
    service = _make_service(conference, settings)
    service.client.fetch_rooms_full = lambda: [
        {"name": {"en": "No ID Room"}, "description": None, "capacity": 10, "position": 0},
    ]
    service.client.fetch_tags = MagicMock(return_value={})

    count = service.sync_rooms()

    assert count == 0
    assert Room.objects.filter(conference=conference).count() == 0


@pytest.mark.django_db
def test_sync_rooms_updates_existing_room(settings):
    conference = _make_conference(slug="rooms-update")
    Room.objects.create(conference=conference, pretalx_id=1, name="Old Name")

    service = _make_service(conference, settings)
    service.client.fetch_rooms_full = lambda: [
        {"id": 1, "name": {"en": "New Name"}, "description": None, "capacity": 100, "position": 2},
    ]
    service.client.fetch_tags = MagicMock(return_value={})

    count = service.sync_rooms()

    assert count == 1
    room = Room.objects.get(conference=conference, pretalx_id=1)
    assert room.name == "New Name"
    assert room.capacity == 100


# ===========================================================================
# sync_speakers / sync_speakers_iter
# ===========================================================================


@pytest.mark.django_db
def test_sync_speakers_creates_new_speakers(settings):
    conference = _make_conference(slug="spk-create")
    service = _make_service(conference, settings)
    service.client.fetch_speakers = MagicMock(
        return_value=[
            PretalxSpeaker(code="SPK1", name="Alice", biography="Bio A", email="alice@example.com"),
            PretalxSpeaker(code="SPK2", name="Bob", biography="Bio B"),
        ]
    )

    count = service.sync_speakers()

    assert count == 2
    assert Speaker.objects.filter(conference=conference).count() == 2
    alice = Speaker.objects.get(conference=conference, pretalx_code="SPK1")
    assert alice.name == "Alice"
    assert alice.biography == "Bio A"
    assert alice.email == "alice@example.com"


@pytest.mark.django_db
def test_sync_speakers_updates_existing_speakers(settings):
    conference = _make_conference(slug="spk-update")
    Speaker.objects.create(conference=conference, pretalx_code="SPK1", name="Old Alice")

    service = _make_service(conference, settings)
    service.client.fetch_speakers = MagicMock(
        return_value=[
            PretalxSpeaker(code="SPK1", name="New Alice", biography="Updated Bio"),
        ]
    )

    count = service.sync_speakers()

    assert count == 1
    alice = Speaker.objects.get(conference=conference, pretalx_code="SPK1")
    assert alice.name == "New Alice"
    assert alice.biography == "Updated Bio"


@pytest.mark.django_db
def test_sync_speakers_matches_user_by_email(settings):
    User = get_user_model()
    user = User.objects.create_user(username="alice", email="alice@example.com", password="pass")

    conference = _make_conference(slug="spk-user")
    service = _make_service(conference, settings)
    service.client.fetch_speakers = MagicMock(
        return_value=[
            PretalxSpeaker(code="SPK1", name="Alice", email="alice@example.com"),
        ]
    )

    count = service.sync_speakers()

    assert count == 1
    speaker = Speaker.objects.get(conference=conference, pretalx_code="SPK1")
    assert speaker.user == user


@pytest.mark.django_db
def test_sync_speakers_returns_zero_when_api_returns_empty(settings):
    conference = _make_conference(slug="spk-empty")
    service = _make_service(conference, settings)
    service.client.fetch_speakers = MagicMock(return_value=[])

    count = service.sync_speakers()

    assert count == 0


@pytest.mark.django_db
def test_sync_speakers_iter_yields_progress(settings):
    conference = _make_conference(slug="spk-iter")
    service = _make_service(conference, settings)
    service.client.fetch_speakers = MagicMock(
        return_value=[PretalxSpeaker(code=f"SPK{i}", name=f"Speaker {i}") for i in range(3)]
    )

    progress_updates = list(service.sync_speakers_iter())

    assert progress_updates[0] == {"phase": "fetching"}
    assert {"current": 0, "total": 3} in progress_updates
    assert progress_updates[-1] == {"count": 3}


@pytest.mark.django_db
def test_sync_speakers_iter_empty_yields_count_zero(settings):
    conference = _make_conference(slug="spk-iter-empty")
    service = _make_service(conference, settings)
    service.client.fetch_speakers = MagicMock(return_value=[])

    progress_updates = list(service.sync_speakers_iter())

    assert progress_updates == [{"phase": "fetching"}, {"count": 0}]


@pytest.mark.django_db
def test_sync_speakers_user_match_on_update(settings):
    """When updating an existing speaker that has no user, match by email."""
    User = get_user_model()
    user = User.objects.create_user(username="bob", email="bob@example.com", password="pass")

    conference = _make_conference(slug="spk-user-upd")
    Speaker.objects.create(conference=conference, pretalx_code="SPK1", name="Bob", email="")

    service = _make_service(conference, settings)
    service.client.fetch_speakers = MagicMock(
        return_value=[
            PretalxSpeaker(code="SPK1", name="Bob Updated", email="bob@example.com"),
        ]
    )

    service.sync_speakers()

    speaker = Speaker.objects.get(conference=conference, pretalx_code="SPK1")
    assert speaker.user == user
    assert speaker.name == "Bob Updated"


# ===========================================================================
# sync_talks / sync_talks_iter / _bulk_set_talk_speakers
# ===========================================================================


@pytest.mark.django_db
def test_sync_talks_clears_speakers_when_api_returns_empty_list(settings):
    settings.DJANGO_PROGRAM = _PRETALX_SETTINGS
    conference = _make_conference(slug="pycon-sync-talks", pretalx_slug="pycon-sync-2027")
    speaker = Speaker.objects.create(conference=conference, pretalx_code="SPK1", name="Speaker One")
    talk = Talk.objects.create(conference=conference, pretalx_code="TALK1", title="Initial Title")
    talk.speakers.add(speaker)

    service = _make_service(conference, settings)
    service.client.fetch_talks = lambda **kwargs: [
        PretalxTalk(code="TALK1", title="Updated Title", tags=["AI"], speaker_codes=[], state="confirmed")
    ]

    count = service.sync_talks()

    talk.refresh_from_db()
    assert count == 1
    assert talk.title == "Updated Title"
    assert talk.tags == ["AI"]
    assert talk.speakers.count() == 0


@pytest.mark.django_db
def test_sync_talks_links_room_fk(settings):
    settings.DJANGO_PROGRAM = _PRETALX_SETTINGS
    conference = _make_conference(slug="pycon-room-fk", pretalx_slug="pycon-room-fk-2027")
    room = Room.objects.create(conference=conference, pretalx_id=1, name="Hall A")

    service = PretalxSyncService(conference)
    service._rooms = {1: room}
    service._room_names = {1: "Hall A"}
    service._submission_types = {}
    service._tracks = {}
    service._tags = {}
    service.client.fetch_talks = lambda **kwargs: [
        PretalxTalk(code="TALK1", title="My Talk", room="Hall A", state="confirmed")
    ]

    count = service.sync_talks()

    assert count == 1
    talk = Talk.objects.get(conference=conference, pretalx_code="TALK1")
    assert talk.room == room


@pytest.mark.django_db
def test_sync_talks_iter_returns_zero_on_empty(settings):
    conference = _make_conference(slug="talks-empty")
    service = _make_service(conference, settings)
    service.client.fetch_talks = MagicMock(return_value=[])

    progress = list(service.sync_talks_iter())

    assert progress[-1] == {"count": 0}


@pytest.mark.django_db
def test_sync_talks_creates_new_talks(settings):
    conference = _make_conference(slug="talks-create")
    service = _make_service(conference, settings)
    service.client.fetch_talks = MagicMock(
        return_value=[
            PretalxTalk(code="T1", title="Talk One", state="confirmed"),
            PretalxTalk(code="T2", title="Talk Two", state="confirmed"),
        ]
    )

    count = service.sync_talks()

    assert count == 2
    assert Talk.objects.filter(conference=conference).count() == 2


@pytest.mark.django_db
def test_sync_talks_updates_existing_talks(settings):
    conference = _make_conference(slug="talks-update")
    Talk.objects.create(conference=conference, pretalx_code="T1", title="Old Title")

    service = _make_service(conference, settings)
    service.client.fetch_talks = MagicMock(
        return_value=[
            PretalxTalk(code="T1", title="New Title", state="confirmed", abstract="New abstract"),
        ]
    )

    count = service.sync_talks()

    assert count == 1
    talk = Talk.objects.get(conference=conference, pretalx_code="T1")
    assert talk.title == "New Title"
    assert talk.abstract == "New abstract"


@pytest.mark.django_db
def test_sync_talks_sets_m2m_speakers(settings):
    conference = _make_conference(slug="talks-m2m")
    speaker = Speaker.objects.create(conference=conference, pretalx_code="SPK1", name="Alice")

    service = _make_service(conference, settings)
    service.client.fetch_talks = MagicMock(
        return_value=[
            PretalxTalk(code="T1", title="Talk", state="confirmed", speaker_codes=["SPK1"]),
        ]
    )

    service.sync_talks()

    talk = Talk.objects.get(conference=conference, pretalx_code="T1")
    assert list(talk.speakers.values_list("pretalx_code", flat=True)) == ["SPK1"]


@pytest.mark.django_db
def test_bulk_set_talk_speakers_replaces_existing(settings):
    conference = _make_conference(slug="bulk-m2m")
    spk_a = Speaker.objects.create(conference=conference, pretalx_code="A", name="A")
    spk_b = Speaker.objects.create(conference=conference, pretalx_code="B", name="B")
    talk = Talk.objects.create(conference=conference, pretalx_code="T1", title="Talk")
    talk.speakers.add(spk_a)

    service = _make_service(conference, settings)
    service._bulk_set_talk_speakers({"T1": [spk_b.pk]})

    talk.refresh_from_db()
    assert list(talk.speakers.values_list("pk", flat=True)) == [spk_b.pk]


@pytest.mark.django_db
def test_bulk_set_talk_speakers_with_empty_map(settings):
    conference = _make_conference(slug="bulk-empty")
    service = _make_service(conference, settings)
    service._bulk_set_talk_speakers({})


@pytest.mark.django_db
def test_sync_talks_iter_yields_progress(settings):
    conference = _make_conference(slug="talks-progress")
    service = _make_service(conference, settings)
    service.client.fetch_talks = MagicMock(
        return_value=[PretalxTalk(code=f"T{i}", title=f"Talk {i}", state="confirmed") for i in range(3)]
    )

    progress = list(service.sync_talks_iter())

    assert progress[0] == {"phase": "fetching"}
    assert {"current": 0, "total": 3} in progress
    final = progress[-1]
    assert final["count"] == 3


@pytest.mark.django_db
def test_sync_talks_with_slot_times(settings):
    conference = _make_conference(slug="talks-times")
    service = _make_service(conference, settings)
    service.client.fetch_talks = MagicMock(
        return_value=[
            PretalxTalk(
                code="T1",
                title="Timed Talk",
                state="confirmed",
                slot_start="2027-05-01T10:00:00+00:00",
                slot_end="2027-05-01T10:30:00+00:00",
            ),
        ]
    )

    service.sync_talks()

    talk = Talk.objects.get(conference=conference, pretalx_code="T1")
    assert talk.slot_start is not None
    assert talk.slot_end is not None


# ===========================================================================
# sync_schedule
# ===========================================================================


@pytest.mark.django_db
def test_sync_schedule_creates_talk_slots(settings):
    conference = _make_conference(slug="sched-talk")
    Talk.objects.create(conference=conference, pretalx_code="T1", title="My Talk")

    service = _make_service(conference, settings)
    room = Room.objects.create(conference=conference, pretalx_id=1, name="Hall A")
    service._rooms = {1: room}
    service._room_names = {1: "Hall A"}

    service.client.fetch_schedule = MagicMock(
        return_value=[
            PretalxSlot(
                room="Hall A",
                start="2027-05-01T10:00:00+00:00",
                end="2027-05-01T10:30:00+00:00",
                code="T1",
                title="My Talk",
                start_dt=datetime(2027, 5, 1, 10, 0, tzinfo=UTC),
                end_dt=datetime(2027, 5, 1, 10, 30, tzinfo=UTC),
            ),
        ]
    )

    count, _unscheduled = service.sync_schedule()

    assert count == 1
    slot = ScheduleSlot.objects.get(conference=conference)
    assert slot.talk is not None
    assert slot.slot_type == ScheduleSlot.SlotType.TALK


@pytest.mark.django_db
def test_sync_schedule_creates_break_slots(settings):
    conference = _make_conference(slug="sched-break")
    service = _make_service(conference, settings)

    service.client.fetch_schedule = MagicMock(
        return_value=[
            PretalxSlot(
                room="",
                start="2027-05-01T12:00:00+00:00",
                end="2027-05-01T13:00:00+00:00",
                code="",
                title="Lunch Break",
                start_dt=datetime(2027, 5, 1, 12, 0, tzinfo=UTC),
                end_dt=datetime(2027, 5, 1, 13, 0, tzinfo=UTC),
            ),
        ]
    )

    count, _ = service.sync_schedule()

    assert count == 1
    slot = ScheduleSlot.objects.get(conference=conference)
    assert slot.slot_type == ScheduleSlot.SlotType.BREAK


@pytest.mark.django_db
def test_sync_schedule_deletes_stale_slots(settings):
    conference = _make_conference(slug="sched-stale")
    service = _make_service(conference, settings)

    # Pre-existing slot that won't appear in the sync
    ScheduleSlot.objects.create(
        conference=conference,
        title="Old Slot",
        start=datetime(2027, 5, 1, 9, 0, tzinfo=UTC),
        end=datetime(2027, 5, 1, 9, 30, tzinfo=UTC),
        slot_type=ScheduleSlot.SlotType.OTHER,
        synced_at=datetime(2020, 1, 1, tzinfo=UTC),
    )

    service.client.fetch_schedule = MagicMock(
        return_value=[
            PretalxSlot(
                room="",
                start="2027-05-01T10:00:00+00:00",
                end="2027-05-01T10:30:00+00:00",
                code="",
                title="New Slot",
                start_dt=datetime(2027, 5, 1, 10, 0, tzinfo=UTC),
                end_dt=datetime(2027, 5, 1, 10, 30, tzinfo=UTC),
            ),
        ]
    )

    count, _ = service.sync_schedule()

    assert count == 1
    assert ScheduleSlot.objects.filter(conference=conference).count() == 1
    assert ScheduleSlot.objects.filter(conference=conference, title="New Slot").exists()


@pytest.mark.django_db
def test_sync_schedule_blocks_large_deletion_anomaly(settings):
    settings.DJANGO_PROGRAM = {
        "pretalx": {
            "base_url": "https://pretalx.example.com",
            "token": "tok",
            "schedule_delete_guard_min_existing_slots": 1,
            "schedule_delete_guard_max_fraction_removed": 0.4,
        }
    }
    conference = _make_conference(slug="sched-guard")
    service = PretalxSyncService(conference)
    service._rooms = {}
    service._room_names = {}
    service._submission_types = {}
    service._tracks = {}
    service._tags = {}

    ScheduleSlot.objects.create(
        conference=conference,
        title="Old Slot 1",
        start=datetime(2027, 5, 1, 9, 0, tzinfo=UTC),
        end=datetime(2027, 5, 1, 9, 30, tzinfo=UTC),
        slot_type=ScheduleSlot.SlotType.OTHER,
        synced_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    ScheduleSlot.objects.create(
        conference=conference,
        title="Old Slot 2",
        start=datetime(2027, 5, 1, 10, 0, tzinfo=UTC),
        end=datetime(2027, 5, 1, 10, 30, tzinfo=UTC),
        slot_type=ScheduleSlot.SlotType.OTHER,
        synced_at=datetime(2020, 1, 1, tzinfo=UTC),
    )

    service.client.fetch_schedule = MagicMock(return_value=[])

    with pytest.raises(RuntimeError, match="Aborting schedule sync"):
        service.sync_schedule()

    assert ScheduleSlot.objects.filter(conference=conference).count() == 2


@pytest.mark.django_db
def test_sync_schedule_allows_large_deletion_with_override(settings):
    settings.DJANGO_PROGRAM = {
        "pretalx": {
            "base_url": "https://pretalx.example.com",
            "token": "tok",
            "schedule_delete_guard_min_existing_slots": 1,
            "schedule_delete_guard_max_fraction_removed": 0.4,
        }
    }
    conference = _make_conference(slug="sched-guard-override")
    service = PretalxSyncService(conference)
    service._rooms = {}
    service._room_names = {}
    service._submission_types = {}
    service._tracks = {}
    service._tags = {}

    ScheduleSlot.objects.create(
        conference=conference,
        title="Old Slot 1",
        start=datetime(2027, 5, 1, 9, 0, tzinfo=UTC),
        end=datetime(2027, 5, 1, 9, 30, tzinfo=UTC),
        slot_type=ScheduleSlot.SlotType.OTHER,
        synced_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    ScheduleSlot.objects.create(
        conference=conference,
        title="Old Slot 2",
        start=datetime(2027, 5, 1, 10, 0, tzinfo=UTC),
        end=datetime(2027, 5, 1, 10, 30, tzinfo=UTC),
        slot_type=ScheduleSlot.SlotType.OTHER,
        synced_at=datetime(2020, 1, 1, tzinfo=UTC),
    )

    service.client.fetch_schedule = MagicMock(return_value=[])

    count, _ = service.sync_schedule(allow_large_deletions=True)

    assert count == 0
    assert ScheduleSlot.objects.filter(conference=conference).count() == 0


@pytest.mark.django_db
def test_sync_schedule_skips_slots_without_parsable_times(settings):
    conference = _make_conference(slug="sched-notime")
    service = _make_service(conference, settings)
    service.client.fetch_schedule = MagicMock(
        return_value=[
            PretalxSlot(room="", start="", end="", code="", title="No times"),
        ]
    )

    count, _ = service.sync_schedule()

    assert count == 0
    assert ScheduleSlot.objects.filter(conference=conference).count() == 0


@pytest.mark.django_db
def test_sync_schedule_uses_start_dt_when_present(settings):
    conference = _make_conference(slug="sched-dt")
    service = _make_service(conference, settings)

    start = datetime(2027, 5, 1, 14, 0, tzinfo=UTC)
    end = datetime(2027, 5, 1, 14, 30, tzinfo=UTC)
    service.client.fetch_schedule = MagicMock(
        return_value=[
            PretalxSlot(
                room="",
                start="",
                end="",
                code="",
                title="DT Slot",
                start_dt=start,
                end_dt=end,
            ),
        ]
    )

    count, _ = service.sync_schedule()

    assert count == 1
    slot = ScheduleSlot.objects.get(conference=conference)
    assert slot.start == start
    assert slot.end == end


@pytest.mark.django_db
def test_sync_schedule_falls_back_to_iso_parsing(settings):
    conference = _make_conference(slug="sched-iso")
    service = _make_service(conference, settings)
    service.client.fetch_schedule = MagicMock(
        return_value=[
            PretalxSlot(
                room="",
                start="2027-05-01T15:00:00+00:00",
                end="2027-05-01T15:30:00+00:00",
                code="",
                title="ISO Slot",
            ),
        ]
    )

    count, _ = service.sync_schedule()

    assert count == 1
    slot = ScheduleSlot.objects.get(conference=conference)
    assert slot.start is not None


@pytest.mark.django_db
def test_sync_schedule_unscheduled_count(settings):
    conference = _make_conference(slug="sched-unsched")
    # Talk with no slot_start
    Talk.objects.create(conference=conference, pretalx_code="T1", title="Unscheduled")

    service = _make_service(conference, settings)
    service.client.fetch_schedule = MagicMock(return_value=[])

    _, unscheduled = service.sync_schedule()

    assert unscheduled == 1


@pytest.mark.django_db
def test_sync_schedule_talk_not_found_still_creates_slot(settings):
    conference = _make_conference(slug="sched-notalk")
    service = _make_service(conference, settings)
    service.client.fetch_schedule = MagicMock(
        return_value=[
            PretalxSlot(
                room="",
                start="2027-05-01T10:00:00+00:00",
                end="2027-05-01T10:30:00+00:00",
                code="NONEXISTENT",
                title="Talk slot without talk record",
                start_dt=datetime(2027, 5, 1, 10, 0, tzinfo=UTC),
                end_dt=datetime(2027, 5, 1, 10, 30, tzinfo=UTC),
            ),
        ]
    )

    count, _ = service.sync_schedule()

    assert count == 1
    slot = ScheduleSlot.objects.get(conference=conference)
    assert slot.talk is None
    assert slot.slot_type == ScheduleSlot.SlotType.TALK


@pytest.mark.django_db
def test_sync_schedule_uses_talk_title_when_slot_title_empty(settings):
    conference = _make_conference(slug="sched-title")
    Talk.objects.create(conference=conference, pretalx_code="T1", title="From DB")

    service = _make_service(conference, settings)
    service.client.fetch_schedule = MagicMock(
        return_value=[
            PretalxSlot(
                room="",
                start="2027-05-01T10:00:00+00:00",
                end="2027-05-01T10:30:00+00:00",
                code="T1",
                title="",
                start_dt=datetime(2027, 5, 1, 10, 0, tzinfo=UTC),
                end_dt=datetime(2027, 5, 1, 10, 30, tzinfo=UTC),
            ),
        ]
    )

    _count, _ = service.sync_schedule()

    slot = ScheduleSlot.objects.get(conference=conference)
    assert slot.title == "From DB"


@pytest.mark.django_db
def test_sync_schedule_social_slot(settings):
    conference = _make_conference(slug="sched-social")
    service = _make_service(conference, settings)
    service.client.fetch_schedule = MagicMock(
        return_value=[
            PretalxSlot(
                room="",
                start="",
                end="",
                code="",
                title="Social Event",
                start_dt=datetime(2027, 5, 1, 18, 0, tzinfo=UTC),
                end_dt=datetime(2027, 5, 1, 20, 0, tzinfo=UTC),
            ),
        ]
    )

    _count, _ = service.sync_schedule()

    slot = ScheduleSlot.objects.get(conference=conference)
    assert slot.slot_type == ScheduleSlot.SlotType.SOCIAL


# ===========================================================================
# _backfill_talks_from_schedule
# ===========================================================================


@pytest.mark.django_db
def test_backfill_talks_from_schedule(settings):
    conference = _make_conference(slug="backfill")
    room = Room.objects.create(conference=conference, pretalx_id=1, name="Hall A")
    talk = Talk.objects.create(conference=conference, pretalx_code="T1", title="My Talk")

    start = datetime(2027, 5, 1, 10, 0, tzinfo=UTC)
    end = datetime(2027, 5, 1, 10, 30, tzinfo=UTC)
    ScheduleSlot.objects.create(
        conference=conference,
        talk=talk,
        title="My Talk",
        room=room,
        start=start,
        end=end,
        slot_type=ScheduleSlot.SlotType.TALK,
    )

    service = _make_service(conference, settings)
    service._backfill_talks_from_schedule()

    talk.refresh_from_db()
    assert talk.room == room
    assert talk.slot_start == start
    assert talk.slot_end == end


@pytest.mark.django_db
def test_backfill_talks_no_changes_needed(settings):
    conference = _make_conference(slug="backfill-noop")
    room = Room.objects.create(conference=conference, pretalx_id=1, name="Hall A")
    start = datetime(2027, 5, 1, 10, 0, tzinfo=UTC)
    end = datetime(2027, 5, 1, 10, 30, tzinfo=UTC)
    talk = Talk.objects.create(
        conference=conference,
        pretalx_code="T1",
        title="My Talk",
        room=room,
        slot_start=start,
        slot_end=end,
    )
    ScheduleSlot.objects.create(
        conference=conference,
        talk=talk,
        title="My Talk",
        room=room,
        start=start,
        end=end,
        slot_type=ScheduleSlot.SlotType.TALK,
    )

    service = _make_service(conference, settings)
    service._backfill_talks_from_schedule()

    talk.refresh_from_db()
    assert talk.room == room


@pytest.mark.django_db
def test_backfill_talks_partial_update(settings):
    """Only slot_start differs -> should update just that."""
    conference = _make_conference(slug="backfill-partial")
    room = Room.objects.create(conference=conference, pretalx_id=1, name="Hall A")
    old_start = datetime(2027, 5, 1, 9, 0, tzinfo=UTC)
    new_start = datetime(2027, 5, 1, 10, 0, tzinfo=UTC)
    end = datetime(2027, 5, 1, 10, 30, tzinfo=UTC)
    talk = Talk.objects.create(
        conference=conference,
        pretalx_code="T1",
        title="My Talk",
        room=room,
        slot_start=old_start,
        slot_end=end,
    )
    ScheduleSlot.objects.create(
        conference=conference,
        talk=talk,
        title="My Talk",
        room=room,
        start=new_start,
        end=end,
        slot_type=ScheduleSlot.SlotType.TALK,
    )

    service = _make_service(conference, settings)
    service._backfill_talks_from_schedule()

    talk.refresh_from_db()
    assert talk.slot_start == new_start


# ===========================================================================
# _resolve_room
# ===========================================================================


@pytest.mark.django_db
def test_resolve_room_by_name(settings):
    conference = _make_conference(slug="resolve-room")
    room = Room.objects.create(conference=conference, pretalx_id=1, name="Hall A")

    service = _make_service(conference, settings)
    service._rooms = {1: room}

    assert service._resolve_room("Hall A") == room


@pytest.mark.django_db
def test_resolve_room_returns_none_for_empty_name(settings):
    conference = _make_conference(slug="resolve-empty")
    service = _make_service(conference, settings)
    service._rooms = {}

    assert service._resolve_room("") is None


@pytest.mark.django_db
def test_resolve_room_returns_none_when_not_found(settings):
    conference = _make_conference(slug="resolve-miss")
    room = Room.objects.create(conference=conference, pretalx_id=1, name="Hall A")
    service = _make_service(conference, settings)
    service._rooms = {1: room}

    assert service._resolve_room("Nonexistent Room") is None


@pytest.mark.django_db
def test_resolve_room_returns_none_when_rooms_is_none(settings):
    conference = _make_conference(slug="resolve-none")
    service = _make_service(conference, settings)
    service._rooms = None

    assert service._resolve_room("Hall A") is None


# ===========================================================================
# sync_all
# ===========================================================================


@pytest.mark.django_db
def test_sync_all_runs_all_syncs(settings):
    conference = _make_conference(slug="sync-all")
    service = _make_service(conference, settings)

    service.sync_schedule = MagicMock(return_value=(5, 2))
    service.sync_rooms = MagicMock(return_value=3)
    service.sync_speakers = MagicMock(return_value=10)
    service.sync_talks = MagicMock(return_value=8)

    result = service.sync_all()

    assert result == {
        "rooms": 3,
        "speakers": 10,
        "talks": 8,
        "schedule_slots": 5,
        "unscheduled_talks": 2,
    }
    service.sync_schedule.assert_called_once()
    service.sync_rooms.assert_called_once()
    service.sync_speakers.assert_called_once()
    service.sync_talks.assert_called_once()


@pytest.mark.django_db
def test_sync_all_omits_unscheduled_when_zero(settings):
    conference = _make_conference(slug="sync-all-nounsch")
    service = _make_service(conference, settings)

    service.sync_schedule = MagicMock(return_value=(5, 0))
    service.sync_rooms = MagicMock(return_value=3)
    service.sync_speakers = MagicMock(return_value=10)
    service.sync_talks = MagicMock(return_value=8)

    result = service.sync_all()

    assert "unscheduled_talks" not in result
    assert result["schedule_slots"] == 5


# ===========================================================================
# _build_speaker (module-level helper)
# ===========================================================================


@pytest.mark.django_db
def test_build_speaker_new(settings):
    conference = _make_conference(slug="build-new")
    now = datetime(2027, 5, 1, 12, 0, tzinfo=UTC)
    api_spk = PretalxSpeaker(code="SPK1", name="Alice", biography="Bio", avatar_url="http://img.png", email="a@b.com")

    speaker = _build_speaker(api_spk, conference, existing={}, users_by_email={}, now=now)

    assert speaker.pretalx_code == "SPK1"
    assert speaker.name == "Alice"
    assert speaker.biography == "Bio"
    assert speaker.avatar_url == "http://img.png"
    assert speaker.email == "a@b.com"
    assert speaker.conference == conference
    assert speaker.synced_at == now
    assert speaker.user is None


@pytest.mark.django_db
def test_build_speaker_new_with_user_match(settings):
    User = get_user_model()
    user = User.objects.create_user(username="alice", email="alice@example.com", password="pass")

    conference = _make_conference(slug="build-newuser")
    now = datetime(2027, 5, 1, 12, 0, tzinfo=UTC)
    api_spk = PretalxSpeaker(code="SPK1", name="Alice", email="alice@example.com")

    speaker = _build_speaker(
        api_spk,
        conference,
        existing={},
        users_by_email={"alice@example.com": user},
        now=now,
    )

    assert speaker.user == user


@pytest.mark.django_db
def test_build_speaker_update_existing(settings):
    conference = _make_conference(slug="build-update")
    existing_spk = Speaker.objects.create(
        conference=conference,
        pretalx_code="SPK1",
        name="Old",
        biography="Old bio",
    )
    now = datetime(2027, 5, 1, 12, 0, tzinfo=UTC)
    api_spk = PretalxSpeaker(code="SPK1", name="New", biography="New bio", avatar_url="http://img.png", email="a@b.com")

    speaker = _build_speaker(
        api_spk,
        conference,
        existing={"SPK1": existing_spk},
        users_by_email={},
        now=now,
    )

    assert speaker is existing_spk
    assert speaker.name == "New"
    assert speaker.biography == "New bio"
    assert speaker.synced_at == now


@pytest.mark.django_db
def test_build_speaker_update_matches_user_when_none(settings):
    User = get_user_model()
    user = User.objects.create_user(username="x", email="x@test.com", password="pass")

    conference = _make_conference(slug="build-upduser")
    existing_spk = Speaker.objects.create(
        conference=conference,
        pretalx_code="SPK1",
        name="Old",
    )
    now = datetime(2027, 5, 1, 12, 0, tzinfo=UTC)
    api_spk = PretalxSpeaker(code="SPK1", name="New", email="x@test.com")

    speaker = _build_speaker(
        api_spk,
        conference,
        existing={"SPK1": existing_spk},
        users_by_email={"x@test.com": user},
        now=now,
    )

    assert speaker.user == user


@pytest.mark.django_db
def test_build_speaker_new_without_email(settings):
    conference = _make_conference(slug="build-noemail")
    now = datetime(2027, 5, 1, 12, 0, tzinfo=UTC)
    api_spk = PretalxSpeaker(code="SPK1", name="NoEmail")

    speaker = _build_speaker(api_spk, conference, existing={}, users_by_email={}, now=now)

    assert speaker.user is None
    assert speaker.email == ""


# ===========================================================================
# _parse_iso_datetime (module-level helper)
# ===========================================================================


def test_parse_iso_datetime_valid():
    result = _parse_iso_datetime("2027-05-01T10:00:00+00:00")
    assert isinstance(result, datetime)
    assert result.year == 2027


def test_parse_iso_datetime_empty_string():
    assert _parse_iso_datetime("") is None


def test_parse_iso_datetime_invalid_string():
    assert _parse_iso_datetime("not-a-date") is None


def test_parse_iso_datetime_none_like():
    assert _parse_iso_datetime("") is None


# ===========================================================================
# _classify_slot (module-level helper)
# ===========================================================================


def test_classify_slot_talk_with_code():
    assert _classify_slot("My Talk", "TALK1") == ScheduleSlot.SlotType.TALK


def test_classify_slot_break():
    assert _classify_slot("Coffee Break", "") == ScheduleSlot.SlotType.BREAK


def test_classify_slot_lunch():
    assert _classify_slot("Lunch", "") == ScheduleSlot.SlotType.BREAK


def test_classify_slot_social():
    assert _classify_slot("Social Event", "") == ScheduleSlot.SlotType.SOCIAL


def test_classify_slot_party():
    assert _classify_slot("After Party", "") == ScheduleSlot.SlotType.SOCIAL


def test_classify_slot_other():
    assert _classify_slot("Opening Ceremony", "") == ScheduleSlot.SlotType.OTHER


def test_classify_slot_case_insensitive():
    assert _classify_slot("COFFEE BREAK", "") == ScheduleSlot.SlotType.BREAK
    assert _classify_slot("Social PARTY", "") == ScheduleSlot.SlotType.SOCIAL


# ===========================================================================
# _sync_activities_from_talks
# ===========================================================================


@pytest.mark.django_db
def test_sync_talks_creates_activities_for_known_submission_types(settings):
    conference = _make_conference(slug="act-sync")
    service = _make_service(conference, settings)
    service.client.fetch_talks = MagicMock(
        return_value=[
            PretalxTalk(code="T1", title="Intro to Django", state="confirmed", submission_type="Tutorial"),
            PretalxTalk(code="T2", title="Advanced ORM", state="confirmed", submission_type="Tutorial"),
            PretalxTalk(code="T3", title="Quick Demo", state="confirmed", submission_type="Lightning Talk"),
        ]
    )

    service.sync_talks()

    # Should have created 2 activities: "Tutorials" and "Lightning Talks"
    activities = Activity.objects.filter(conference=conference).order_by("activity_type")
    assert activities.count() == 2

    tutorial_act = Activity.objects.get(conference=conference, pretalx_submission_type="Tutorial")
    assert tutorial_act.activity_type == Activity.ActivityType.TUTORIAL
    assert tutorial_act.talks.count() == 2
    assert tutorial_act.synced_at is not None

    lt_act = Activity.objects.get(conference=conference, pretalx_submission_type="Lightning Talk")
    assert lt_act.activity_type == Activity.ActivityType.LIGHTNING_TALK
    assert lt_act.talks.count() == 1


@pytest.mark.django_db
def test_sync_talks_updates_existing_activity(settings):
    conference = _make_conference(slug="act-update")
    Activity.objects.create(
        conference=conference,
        name="Tutorials",
        slug="tutorials",
        activity_type=Activity.ActivityType.TUTORIAL,
        pretalx_submission_type="Tutorial",
    )

    service = _make_service(conference, settings)
    service.client.fetch_talks = MagicMock(
        return_value=[
            PretalxTalk(code="T1", title="Django Intro", state="confirmed", submission_type="Tutorial"),
        ]
    )

    service.sync_talks()

    # Should not create a duplicate
    assert Activity.objects.filter(conference=conference, pretalx_submission_type="Tutorial").count() == 1
    activity = Activity.objects.get(conference=conference, pretalx_submission_type="Tutorial")
    assert activity.talks.count() == 1
    assert activity.synced_at is not None


@pytest.mark.django_db
def test_sync_talks_ignores_unknown_submission_types(settings):
    conference = _make_conference(slug="act-unknown")
    service = _make_service(conference, settings)
    service.client.fetch_talks = MagicMock(
        return_value=[
            PretalxTalk(code="T1", title="Keynote", state="confirmed", submission_type="Keynote"),
        ]
    )

    service.sync_talks()

    assert Activity.objects.filter(conference=conference).count() == 0


@pytest.mark.django_db
def test_sync_talks_activity_slug_uniqueness(settings):
    conference = _make_conference(slug="act-sluguniq")
    Activity.objects.create(
        conference=conference,
        name="Existing",
        slug="tutorial",
        activity_type=Activity.ActivityType.OTHER,
    )

    service = _make_service(conference, settings)
    service.client.fetch_talks = MagicMock(
        return_value=[
            PretalxTalk(code="T1", title="Django Intro", state="confirmed", submission_type="Tutorial"),
        ]
    )

    service.sync_talks()

    new_act = Activity.objects.get(conference=conference, pretalx_submission_type="Tutorial")
    assert new_act.slug == "tutorial-2"


# ===========================================================================
# _sync_activities_from_talks enrichment
# ===========================================================================


@pytest.mark.django_db
def test_sync_enrichment_populates_description(settings):
    conference = _make_conference(slug="enrich-desc")
    service = _make_service(conference, settings)
    service.client.fetch_talks = MagicMock(
        return_value=[
            PretalxTalk(code="T1", title="Django Intro", state="confirmed", submission_type="Tutorial"),
            PretalxTalk(code="T2", title="Advanced ORM", state="confirmed", submission_type="Tutorial"),
        ]
    )

    service.sync_talks()

    activity = Activity.objects.get(conference=conference, pretalx_submission_type="Tutorial")
    assert "2 talks" in activity.description


@pytest.mark.django_db
def test_sync_enrichment_populates_start_end_times(settings):
    conference = _make_conference(slug="enrich-times")
    service = _make_service(conference, settings)
    service.client.fetch_talks = MagicMock(
        return_value=[
            PretalxTalk(
                code="T1",
                title="Talk A",
                state="confirmed",
                submission_type="Tutorial",
                slot_start="2027-05-01T10:00:00+00:00",
                slot_end="2027-05-01T11:00:00+00:00",
            ),
            PretalxTalk(
                code="T2",
                title="Talk B",
                state="confirmed",
                submission_type="Tutorial",
                slot_start="2027-05-01T14:00:00+00:00",
                slot_end="2027-05-01T15:00:00+00:00",
            ),
        ]
    )

    service.sync_talks()

    activity = Activity.objects.get(conference=conference, pretalx_submission_type="Tutorial")
    assert activity.start_time is not None
    assert activity.end_time is not None
    assert activity.start_time.hour == 10
    assert activity.end_time.hour == 15


@pytest.mark.django_db
def test_sync_enrichment_sets_room_when_all_same(settings):
    conference = _make_conference(slug="enrich-room")
    room = Room.objects.create(conference=conference, pretalx_id=1, name="Hall A")

    service = _make_service(conference, settings)
    service._rooms = {1: room}
    service._room_names = {1: "Hall A"}
    service.client.fetch_talks = MagicMock(
        return_value=[
            PretalxTalk(code="T1", title="Talk A", state="confirmed", submission_type="Tutorial", room="Hall A"),
            PretalxTalk(code="T2", title="Talk B", state="confirmed", submission_type="Tutorial", room="Hall A"),
        ]
    )

    service.sync_talks()

    # Verify talks have room set
    talks = Talk.objects.filter(conference=conference, submission_type="Tutorial")
    for t in talks:
        assert t.room == room, f"Talk {t.pretalx_code} room={t.room} (expected {room})"

    activity = Activity.objects.get(conference=conference, pretalx_submission_type="Tutorial")
    assert "in Hall A" in activity.description
    assert activity.room == room


@pytest.mark.django_db
def test_sync_enrichment_no_room_when_different_rooms(settings):
    conference = _make_conference(slug="enrich-multiroom")
    room_a = Room.objects.create(conference=conference, pretalx_id=1, name="Hall A")
    room_b = Room.objects.create(conference=conference, pretalx_id=2, name="Hall B")

    service = _make_service(conference, settings)
    service._rooms = {1: room_a, 2: room_b}
    service._room_names = {1: "Hall A", 2: "Hall B"}
    service.client.fetch_talks = MagicMock(
        return_value=[
            PretalxTalk(code="T1", title="Talk A", state="confirmed", submission_type="Tutorial", room="Hall A"),
            PretalxTalk(code="T2", title="Talk B", state="confirmed", submission_type="Tutorial", room="Hall B"),
        ]
    )

    service.sync_talks()

    activity = Activity.objects.get(conference=conference, pretalx_submission_type="Tutorial")
    assert activity.room is None
    assert "across 2 rooms" in activity.description
