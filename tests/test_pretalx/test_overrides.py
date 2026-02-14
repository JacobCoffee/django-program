"""Tests for override models, effective properties, and sync integration."""

import zoneinfo
from datetime import UTC, date, datetime, time
from unittest.mock import MagicMock

import pytest
from django.core.exceptions import ValidationError

from django_program.conference.models import Conference
from django_program.pretalx.models import (
    Room,
    RoomOverride,
    Speaker,
    SpeakerOverride,
    SubmissionTypeDefault,
    Talk,
    TalkOverride,
)
from django_program.pretalx.sync import PretalxSyncService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PRETALX_SETTINGS = {
    "pretalx": {"base_url": "https://pretalx.example.com", "token": "tok"},
}


def _make_conference(slug="override-conf", pretalx_slug="override-event", **overrides):
    """Create and return a Conference with sensible defaults."""
    defaults = {
        "name": "Override Conf",
        "slug": slug,
        "start_date": date(2027, 5, 1),
        "end_date": date(2027, 5, 3),
        "timezone": "US/Eastern",
        "pretalx_event_slug": pretalx_slug,
    }
    defaults.update(overrides)
    return Conference.objects.create(**defaults)


def _make_service(conference, settings):
    """Build a PretalxSyncService with mocked client dependencies."""
    settings.DJANGO_PROGRAM = _PRETALX_SETTINGS
    service = PretalxSyncService(conference)
    service._rooms = {}
    service._room_names = {}
    service._submission_types = {}
    service._tracks = {}
    service._tags = {}
    return service


# ===========================================================================
# TalkOverride.__str__
# ===========================================================================


@pytest.mark.django_db
class TestTalkOverrideStr:
    def test_str(self):
        conf = _make_conference(slug="str-conf")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="My Talk")
        override = TalkOverride.objects.create(talk=talk, conference=conf)
        assert str(override) == "Override for My Talk"


# ===========================================================================
# TalkOverride.clean()
# ===========================================================================


@pytest.mark.django_db
class TestTalkOverrideClean:
    def test_clean_valid_same_conference(self):
        conf = _make_conference(slug="clean-ok")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="Talk A")
        override = TalkOverride(talk=talk, conference=conf)
        override.clean()

    def test_clean_rejects_mismatched_conference(self):
        conf_a = _make_conference(slug="clean-a", pretalx_slug="event-a")
        conf_b = _make_conference(slug="clean-b", pretalx_slug="event-b")
        talk = Talk.objects.create(conference=conf_a, pretalx_code="T1", title="Talk A")
        override = TalkOverride(talk=talk, conference=conf_b)
        with pytest.raises(ValidationError, match="does not belong to this conference"):
            override.clean()

    def test_clean_skips_when_no_talk(self):
        conf = _make_conference(slug="clean-notalk")
        override = TalkOverride(conference=conf)
        override.clean()

    def test_clean_skips_when_no_conference(self):
        conf = _make_conference(slug="clean-noconf")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="Talk A")
        override = TalkOverride(talk=talk)
        override.clean()


# ===========================================================================
# TalkOverride.save() auto-set conference
# ===========================================================================


@pytest.mark.django_db
class TestTalkOverrideSave:
    def test_save_auto_sets_conference_from_talk(self):
        conf = _make_conference(slug="save-auto")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="Talk A")
        override = TalkOverride(talk=talk)
        override.save()
        assert override.conference_id == conf.pk

    def test_save_does_not_override_explicit_conference(self):
        conf_a = _make_conference(slug="save-explicit-a", pretalx_slug="ev-a")
        conf_b = _make_conference(slug="save-explicit-b", pretalx_slug="ev-b")
        talk = Talk.objects.create(conference=conf_a, pretalx_code="T1", title="Talk A")
        override = TalkOverride(talk=talk, conference=conf_b)
        override.save()
        assert override.conference_id == conf_b.pk


# ===========================================================================
# TalkOverride.is_empty
# ===========================================================================


@pytest.mark.django_db
class TestTalkOverrideIsEmpty:
    def test_empty_override(self):
        conf = _make_conference(slug="empty-ov")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="T")
        override = TalkOverride.objects.create(talk=talk, conference=conf)
        assert override.is_empty is True

    def test_non_empty_override(self):
        conf = _make_conference(slug="notempty-ov")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="T")
        override = TalkOverride.objects.create(talk=talk, conference=conf, override_title="New")
        assert override.is_empty is False


# ===========================================================================
# Talk effective_* properties
# ===========================================================================


@pytest.mark.django_db
class TestTalkEffectiveProperties:
    def test_effective_title_no_override(self):
        conf = _make_conference(slug="eff-title-none")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="Original")
        assert talk.effective_title == "Original"

    def test_effective_title_with_override(self):
        conf = _make_conference(slug="eff-title-ov")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="Original")
        TalkOverride.objects.create(talk=talk, conference=conf, override_title="Overridden")
        assert talk.effective_title == "Overridden"

    def test_effective_title_blank_override_falls_back(self):
        conf = _make_conference(slug="eff-title-blank")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="Original")
        TalkOverride.objects.create(talk=talk, conference=conf, override_title="")
        assert talk.effective_title == "Original"

    def test_effective_state_cancelled(self):
        conf = _make_conference(slug="eff-state-cancel")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="T", state="confirmed")
        TalkOverride.objects.create(talk=talk, conference=conf, is_cancelled=True)
        assert talk.effective_state == "cancelled"

    def test_effective_state_override(self):
        conf = _make_conference(slug="eff-state-ov")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="T", state="confirmed")
        TalkOverride.objects.create(talk=talk, conference=conf, override_state="withdrawn")
        assert talk.effective_state == "withdrawn"

    def test_effective_state_no_override(self):
        conf = _make_conference(slug="eff-state-none")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="T", state="confirmed")
        assert talk.effective_state == "confirmed"

    def test_effective_room_override(self):
        conf = _make_conference(slug="eff-room")
        room_a = Room.objects.create(conference=conf, pretalx_id=1, name="Room A")
        room_b = Room.objects.create(conference=conf, pretalx_id=2, name="Room B")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="T", room=room_a)
        TalkOverride.objects.create(talk=talk, conference=conf, override_room=room_b)
        assert talk.effective_room == room_b

    def test_effective_room_no_override(self):
        conf = _make_conference(slug="eff-room-none")
        room_a = Room.objects.create(conference=conf, pretalx_id=1, name="Room A")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="T", room=room_a)
        assert talk.effective_room == room_a

    def test_effective_abstract_override(self):
        conf = _make_conference(slug="eff-abstract")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="T", abstract="old")
        TalkOverride.objects.create(talk=talk, conference=conf, override_abstract="new abstract")
        assert talk.effective_abstract == "new abstract"

    def test_effective_abstract_no_override(self):
        conf = _make_conference(slug="eff-abstract-none")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="T", abstract="old")
        assert talk.effective_abstract == "old"

    def test_effective_slot_start_override(self):
        conf = _make_conference(slug="eff-slot")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="T")
        start = datetime(2027, 5, 1, 9, 0, tzinfo=UTC)
        TalkOverride.objects.create(talk=talk, conference=conf, override_slot_start=start)
        assert talk.effective_slot_start == start

    def test_effective_slot_start_no_override(self):
        conf = _make_conference(slug="eff-slot-start-none")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="T")
        start = datetime(2027, 5, 1, 9, 0, tzinfo=UTC)
        talk.slot_start = start
        talk.save()
        assert talk.effective_slot_start == start

    def test_effective_slot_end_with_override(self):
        conf = _make_conference(slug="eff-slot-end")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="T")
        end = datetime(2027, 5, 1, 10, 0, tzinfo=UTC)
        TalkOverride.objects.create(talk=talk, conference=conf, override_slot_end=end)
        assert talk.effective_slot_end == end

    def test_effective_slot_end_no_override(self):
        conf = _make_conference(slug="eff-slot-end-none")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="T")
        end = datetime(2027, 5, 1, 10, 0, tzinfo=UTC)
        talk.slot_end = end
        talk.save()
        assert talk.effective_slot_end == end


# ===========================================================================
# SpeakerOverride
# ===========================================================================


@pytest.mark.django_db
class TestSpeakerOverride:
    def test_str(self):
        conf = _make_conference(slug="spk-str")
        speaker = Speaker.objects.create(conference=conf, pretalx_code="S1", name="Alice")
        override = SpeakerOverride.objects.create(speaker=speaker, conference=conf)
        assert str(override) == "Override for Alice"

    def test_save_auto_sets_conference(self):
        conf = _make_conference(slug="spk-save")
        speaker = Speaker.objects.create(conference=conf, pretalx_code="S1", name="Alice")
        override = SpeakerOverride(speaker=speaker)
        override.save()
        assert override.conference_id == conf.pk

    def test_clean_rejects_mismatched_conference(self):
        conf_a = _make_conference(slug="spk-clean-a", pretalx_slug="ev-a")
        conf_b = _make_conference(slug="spk-clean-b", pretalx_slug="ev-b")
        speaker = Speaker.objects.create(conference=conf_a, pretalx_code="S1", name="Alice")
        override = SpeakerOverride(speaker=speaker, conference=conf_b)
        with pytest.raises(ValidationError, match="does not belong to this conference"):
            override.clean()

    def test_is_empty_true(self):
        conf = _make_conference(slug="spk-empty")
        speaker = Speaker.objects.create(conference=conf, pretalx_code="S1", name="Alice")
        override = SpeakerOverride.objects.create(speaker=speaker, conference=conf)
        assert override.is_empty is True

    def test_is_empty_false(self):
        conf = _make_conference(slug="spk-notempty")
        speaker = Speaker.objects.create(conference=conf, pretalx_code="S1", name="Alice")
        override = SpeakerOverride.objects.create(speaker=speaker, conference=conf, override_name="Bob")
        assert override.is_empty is False


# ===========================================================================
# Speaker effective_* properties
# ===========================================================================


@pytest.mark.django_db
class TestSpeakerEffectiveProperties:
    def test_effective_name_no_override(self):
        conf = _make_conference(slug="spk-eff-none")
        speaker = Speaker.objects.create(conference=conf, pretalx_code="S1", name="Alice")
        assert speaker.effective_name == "Alice"

    def test_effective_name_with_override(self):
        conf = _make_conference(slug="spk-eff-ov")
        speaker = Speaker.objects.create(conference=conf, pretalx_code="S1", name="Alice")
        SpeakerOverride.objects.create(speaker=speaker, conference=conf, override_name="Bob")
        assert speaker.effective_name == "Bob"

    def test_effective_biography_with_override(self):
        conf = _make_conference(slug="spk-eff-bio")
        speaker = Speaker.objects.create(conference=conf, pretalx_code="S1", name="Alice", biography="old bio")
        SpeakerOverride.objects.create(speaker=speaker, conference=conf, override_biography="new bio")
        assert speaker.effective_biography == "new bio"

    def test_effective_biography_no_override(self):
        conf = _make_conference(slug="spk-eff-bio-none")
        speaker = Speaker.objects.create(conference=conf, pretalx_code="S1", name="Alice", biography="old bio")
        assert speaker.effective_biography == "old bio"

    def test_effective_avatar_url_with_override(self):
        conf = _make_conference(slug="spk-eff-avatar")
        speaker = Speaker.objects.create(
            conference=conf, pretalx_code="S1", name="Alice", avatar_url="https://old.com/avatar.jpg"
        )
        SpeakerOverride.objects.create(
            speaker=speaker, conference=conf, override_avatar_url="https://new.com/avatar.jpg"
        )
        assert speaker.effective_avatar_url == "https://new.com/avatar.jpg"

    def test_effective_avatar_url_no_override(self):
        conf = _make_conference(slug="spk-eff-avatar-none")
        speaker = Speaker.objects.create(
            conference=conf, pretalx_code="S1", name="Alice", avatar_url="https://old.com/avatar.jpg"
        )
        assert speaker.effective_avatar_url == "https://old.com/avatar.jpg"

    def test_effective_email_with_override(self):
        conf = _make_conference(slug="spk-eff-email")
        speaker = Speaker.objects.create(conference=conf, pretalx_code="S1", name="Alice", email="old@test.com")
        SpeakerOverride.objects.create(speaker=speaker, conference=conf, override_email="new@test.com")
        assert speaker.effective_email == "new@test.com"

    def test_effective_email_no_override(self):
        conf = _make_conference(slug="spk-eff-email-none")
        speaker = Speaker.objects.create(conference=conf, pretalx_code="S1", name="Alice", email="old@test.com")
        assert speaker.effective_email == "old@test.com"


# ===========================================================================
# RoomOverride
# ===========================================================================


@pytest.mark.django_db
class TestRoomOverride:
    def test_str(self):
        conf = _make_conference(slug="rm-str")
        room = Room.objects.create(conference=conf, pretalx_id=1, name="Main Hall")
        override = RoomOverride.objects.create(room=room, conference=conf)
        assert str(override) == "Override for Main Hall"

    def test_save_auto_sets_conference(self):
        conf = _make_conference(slug="rm-save")
        room = Room.objects.create(conference=conf, pretalx_id=1, name="Main Hall")
        override = RoomOverride(room=room)
        override.save()
        assert override.conference_id == conf.pk

    def test_clean_rejects_mismatched_conference(self):
        conf_a = _make_conference(slug="rm-clean-a", pretalx_slug="ev-a")
        conf_b = _make_conference(slug="rm-clean-b", pretalx_slug="ev-b")
        room = Room.objects.create(conference=conf_a, pretalx_id=1, name="Room A")
        override = RoomOverride(room=room, conference=conf_b)
        with pytest.raises(ValidationError, match="does not belong to this conference"):
            override.clean()

    def test_is_empty_true(self):
        conf = _make_conference(slug="rm-empty")
        room = Room.objects.create(conference=conf, pretalx_id=1, name="Room A")
        override = RoomOverride.objects.create(room=room, conference=conf)
        assert override.is_empty is True

    def test_is_empty_false(self):
        conf = _make_conference(slug="rm-notempty")
        room = Room.objects.create(conference=conf, pretalx_id=1, name="Room A")
        override = RoomOverride.objects.create(room=room, conference=conf, override_name="Room B")
        assert override.is_empty is False


# ===========================================================================
# Room effective_* properties
# ===========================================================================


@pytest.mark.django_db
class TestRoomEffectiveProperties:
    def test_effective_name_no_override(self):
        conf = _make_conference(slug="rm-eff-none")
        room = Room.objects.create(conference=conf, pretalx_id=1, name="Room A")
        assert room.effective_name == "Room A"

    def test_effective_name_with_override(self):
        conf = _make_conference(slug="rm-eff-ov")
        room = Room.objects.create(conference=conf, pretalx_id=1, name="Room A")
        RoomOverride.objects.create(room=room, conference=conf, override_name="Room B")
        assert room.effective_name == "Room B"

    def test_effective_capacity_with_override(self):
        conf = _make_conference(slug="rm-eff-cap")
        room = Room.objects.create(conference=conf, pretalx_id=1, name="Room A", capacity=100)
        RoomOverride.objects.create(room=room, conference=conf, override_capacity=200)
        assert room.effective_capacity == 200

    def test_effective_capacity_no_override(self):
        conf = _make_conference(slug="rm-eff-cap-none")
        room = Room.objects.create(conference=conf, pretalx_id=1, name="Room A", capacity=100)
        assert room.effective_capacity == 100

    def test_effective_description_with_override(self):
        conf = _make_conference(slug="rm-eff-desc")
        room = Room.objects.create(conference=conf, pretalx_id=1, name="Room A", description="old")
        RoomOverride.objects.create(room=room, conference=conf, override_description="new desc")
        assert room.effective_description == "new desc"

    def test_effective_description_no_override(self):
        conf = _make_conference(slug="rm-eff-desc-none")
        room = Room.objects.create(conference=conf, pretalx_id=1, name="Room A", description="old")
        assert room.effective_description == "old"


# ===========================================================================
# SubmissionTypeDefault.__str__
# ===========================================================================


@pytest.mark.django_db
class TestSubmissionTypeDefaultStr:
    def test_str(self):
        conf = _make_conference(slug="std-str")
        std = SubmissionTypeDefault.objects.create(conference=conf, submission_type="Poster")
        assert str(std) == "Defaults for 'Poster'"


# ===========================================================================
# apply_type_defaults() in sync service
# ===========================================================================


@pytest.mark.django_db
class TestApplyTypeDefaults:
    def test_assigns_room_to_unscheduled_talk(self, settings):
        conf = _make_conference(slug="td-room")
        service = _make_service(conf, settings)
        room = Room.objects.create(conference=conf, pretalx_id=1, name="Poster Hall")
        Talk.objects.create(
            conference=conf,
            pretalx_code="P1",
            title="Poster",
            submission_type="Poster",
        )
        SubmissionTypeDefault.objects.create(
            conference=conf,
            submission_type="Poster",
            default_room=room,
        )

        count = service.apply_type_defaults()

        assert count == 1
        talk = Talk.objects.get(pretalx_code="P1")
        assert talk.room == room

    def test_assigns_slot_times_to_unscheduled_talk(self, settings):
        conf = _make_conference(slug="td-time", timezone="US/Eastern")
        service = _make_service(conf, settings)
        Talk.objects.create(
            conference=conf,
            pretalx_code="P1",
            title="Poster",
            submission_type="Poster",
        )
        SubmissionTypeDefault.objects.create(
            conference=conf,
            submission_type="Poster",
            default_date=date(2027, 5, 1),
            default_start_time=time(9, 0),
            default_end_time=time(17, 0),
        )

        count = service.apply_type_defaults()

        assert count == 1
        talk = Talk.objects.get(pretalx_code="P1")
        assert talk.slot_start is not None
        assert talk.slot_end is not None
        eastern = zoneinfo.ZoneInfo("US/Eastern")
        assert talk.slot_start.tzinfo is not None
        expected_start = datetime.combine(date(2027, 5, 1), time(9, 0), tzinfo=eastern)
        assert talk.slot_start == expected_start

    def test_skips_talks_with_room_assigned(self, settings):
        conf = _make_conference(slug="td-skip")
        service = _make_service(conf, settings)
        room = Room.objects.create(conference=conf, pretalx_id=1, name="Room A")
        Talk.objects.create(
            conference=conf,
            pretalx_code="P1",
            title="Poster",
            submission_type="Poster",
            room=room,
        )
        SubmissionTypeDefault.objects.create(
            conference=conf,
            submission_type="Poster",
        )

        count = service.apply_type_defaults()
        assert count == 0

    def test_returns_zero_when_no_defaults(self, settings):
        conf = _make_conference(slug="td-none")
        service = _make_service(conf, settings)
        count = service.apply_type_defaults()
        assert count == 0

    def test_skips_slot_start_when_already_set(self, settings):
        conf = _make_conference(slug="td-start-set")
        service = _make_service(conf, settings)
        existing_start = datetime(2027, 5, 1, 8, 0, tzinfo=UTC)
        Talk.objects.create(
            conference=conf,
            pretalx_code="P1",
            title="Poster",
            submission_type="Poster",
            slot_start=existing_start,
        )
        SubmissionTypeDefault.objects.create(
            conference=conf,
            submission_type="Poster",
            default_date=date(2027, 5, 1),
            default_start_time=time(9, 0),
            default_end_time=time(17, 0),
        )

        count = service.apply_type_defaults()
        assert count == 1
        talk = Talk.objects.get(pretalx_code="P1")
        assert talk.slot_start == existing_start
        assert talk.slot_end is not None

    def test_assigns_only_room_when_no_date(self, settings):
        conf = _make_conference(slug="td-nodate")
        service = _make_service(conf, settings)
        room = Room.objects.create(conference=conf, pretalx_id=1, name="R")
        Talk.objects.create(
            conference=conf,
            pretalx_code="P1",
            title="P",
            submission_type="Poster",
        )
        SubmissionTypeDefault.objects.create(
            conference=conf,
            submission_type="Poster",
            default_room=room,
            default_start_time=time(9, 0),
            default_end_time=time(17, 0),
        )

        count = service.apply_type_defaults()
        assert count == 1
        talk = Talk.objects.get(pretalx_code="P1")
        assert talk.room == room
        assert talk.slot_start is None


# ===========================================================================
# AbstractOverride._get_parent_conference_id
# ===========================================================================


@pytest.mark.django_db
class TestAbstractOverrideGetParentConferenceId:
    def test_get_parent_conference_id_returns_none_when_no_parent(self):
        conf = _make_conference(slug="parent-none")
        override = TalkOverride(conference=conf)
        assert override._get_parent_conference_id() is None


# ===========================================================================
# sync_all includes type defaults (overrides no longer applied in sync)
# ===========================================================================


@pytest.mark.django_db
class TestSyncAllIncludesTypeDefaults:
    def test_sync_all_applies_type_defaults(self, settings):
        conf = _make_conference(slug="sync-all-td")
        service = _make_service(conf, settings)

        unscheduled = Talk.objects.create(
            conference=conf,
            pretalx_code="P1",
            title="Poster",
            submission_type="Poster",
        )
        room = Room.objects.create(conference=conf, pretalx_id=1, name="Hall")
        SubmissionTypeDefault.objects.create(
            conference=conf,
            submission_type="Poster",
            default_room=room,
        )

        # Mock all sync methods since they need real API calls
        service.sync_rooms = MagicMock(return_value=0)
        service.sync_speakers = MagicMock(return_value=0)
        service.sync_talks = MagicMock(return_value=0)
        service.sync_schedule = MagicMock(return_value=(0, 0))

        result = service.sync_all()

        assert result["type_defaults_applied"] == 1
        assert "overrides_applied" not in result

        unscheduled.refresh_from_db()
        assert unscheduled.room == room
