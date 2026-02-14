"""Tests for TalkOverride and SubmissionTypeDefault models and sync integration."""

import zoneinfo
from datetime import UTC, date, datetime, time
from unittest.mock import MagicMock

import pytest
from django.core.exceptions import ValidationError

from django_program.conference.models import Conference
from django_program.pretalx.models import Room, SubmissionTypeDefault, Talk, TalkOverride
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
# TalkOverride.apply()
# ===========================================================================


@pytest.mark.django_db
class TestTalkOverrideApply:
    def test_apply_overrides_title(self):
        conf = _make_conference(slug="apply-title")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="Original")
        override = TalkOverride.objects.create(talk=talk, conference=conf, override_title="New Title")
        changed = override.apply()
        assert "title" in changed
        assert talk.title == "New Title"

    def test_apply_does_not_change_matching_title(self):
        conf = _make_conference(slug="apply-same")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="Same")
        override = TalkOverride.objects.create(talk=talk, conference=conf, override_title="Same")
        changed = override.apply()
        assert "title" not in changed

    def test_apply_overrides_state(self):
        conf = _make_conference(slug="apply-state")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="T", state="confirmed")
        override = TalkOverride.objects.create(talk=talk, conference=conf, override_state="withdrawn")
        changed = override.apply()
        assert "state" in changed
        assert talk.state == "withdrawn"

    def test_apply_is_cancelled_sets_state(self):
        conf = _make_conference(slug="apply-cancel")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="T", state="confirmed")
        override = TalkOverride.objects.create(talk=talk, conference=conf, is_cancelled=True)
        changed = override.apply()
        assert "state" in changed
        assert talk.state == "cancelled"

    def test_apply_is_cancelled_no_op_when_already_cancelled(self):
        conf = _make_conference(slug="apply-cancel-noop")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="T", state="cancelled")
        override = TalkOverride.objects.create(talk=talk, conference=conf, is_cancelled=True)
        changed = override.apply()
        assert "state" not in changed

    def test_apply_overrides_abstract(self):
        conf = _make_conference(slug="apply-abstract")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="T", abstract="old")
        override = TalkOverride.objects.create(talk=talk, conference=conf, override_abstract="new abstract")
        changed = override.apply()
        assert "abstract" in changed
        assert talk.abstract == "new abstract"

    def test_apply_overrides_room(self):
        conf = _make_conference(slug="apply-room")
        room = Room.objects.create(conference=conf, pretalx_id=1, name="Hall A")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="T")
        override = TalkOverride.objects.create(talk=talk, conference=conf, override_room=room)
        changed = override.apply()
        assert "room" in changed
        assert talk.room == room

    def test_apply_overrides_slot_times(self):
        conf = _make_conference(slug="apply-slot")
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="T")
        start = datetime(2027, 5, 1, 9, 0, tzinfo=UTC)
        end = datetime(2027, 5, 1, 10, 0, tzinfo=UTC)
        override = TalkOverride.objects.create(
            talk=talk,
            conference=conf,
            override_slot_start=start,
            override_slot_end=end,
        )
        changed = override.apply()
        assert "slot_start" in changed
        assert "slot_end" in changed
        assert talk.slot_start == start
        assert talk.slot_end == end

    def test_apply_empty_override_changes_nothing(self):
        conf = _make_conference(slug="apply-empty")
        talk = Talk.objects.create(
            conference=conf,
            pretalx_code="T1",
            title="T",
            state="confirmed",
        )
        override = TalkOverride.objects.create(talk=talk, conference=conf)
        changed = override.apply()
        assert changed == []


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
# apply_overrides() in sync service
# ===========================================================================


@pytest.mark.django_db
class TestApplyOverrides:
    def test_apply_overrides_updates_talk(self, settings):
        conf = _make_conference(slug="sync-override")
        service = _make_service(conf, settings)
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="Original", state="confirmed")
        TalkOverride.objects.create(
            talk=talk,
            conference=conf,
            override_title="Patched",
            override_state="withdrawn",
        )

        count = service.apply_overrides()

        assert count == 1
        talk.refresh_from_db()
        assert talk.title == "Patched"
        assert talk.state == "withdrawn"

    def test_apply_overrides_skips_unchanged(self, settings):
        conf = _make_conference(slug="sync-override-noop")
        service = _make_service(conf, settings)
        talk = Talk.objects.create(conference=conf, pretalx_code="T1", title="T")
        TalkOverride.objects.create(talk=talk, conference=conf)

        count = service.apply_overrides()
        assert count == 0

    def test_apply_overrides_filters_by_talk_conference(self, settings):
        """Overrides where talk.conference differs from override.conference are excluded."""
        conf_a = _make_conference(slug="sync-ov-a", pretalx_slug="ev-a")
        conf_b = _make_conference(slug="sync-ov-b", pretalx_slug="ev-b")
        talk = Talk.objects.create(conference=conf_a, pretalx_code="T1", title="T")
        # Create override with mismatched conferences
        TalkOverride.objects.create(
            talk=talk,
            conference=conf_b,
            override_title="Should Not Apply",
        )

        service = _make_service(conf_b, settings)
        count = service.apply_overrides()
        assert count == 0

        talk.refresh_from_db()
        assert talk.title == "T"


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
# sync_all includes overrides and type defaults
# ===========================================================================


@pytest.mark.django_db
class TestSyncAllIncludesOverrides:
    def test_sync_all_applies_overrides_and_type_defaults(self, settings):
        conf = _make_conference(slug="sync-all-ov")
        service = _make_service(conf, settings)

        talk = Talk.objects.create(
            conference=conf,
            pretalx_code="T1",
            title="Original",
            state="confirmed",
        )
        TalkOverride.objects.create(
            talk=talk,
            conference=conf,
            override_title="Patched",
        )

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

        assert result["overrides_applied"] == 1
        assert result["type_defaults_applied"] == 1

        talk.refresh_from_db()
        assert talk.title == "Patched"

        unscheduled.refresh_from_db()
        assert unscheduled.room == room
