"""Tests for pretalx model __str__ methods and ScheduleSlot.display_title property."""

from datetime import date

import pytest
from django.utils import timezone

from django_program.conference.models import Conference
from django_program.pretalx.models import Room, ScheduleSlot, Speaker, Talk


@pytest.fixture
def conference(db):
    return Conference.objects.create(
        name="TestCon",
        slug="testcon",
        start_date=date(2027, 5, 1),
        end_date=date(2027, 5, 3),
        timezone="UTC",
    )


@pytest.fixture
def room(conference):
    return Room.objects.create(
        conference=conference,
        pretalx_id=1,
        name="Hall A",
    )


@pytest.fixture
def speaker(conference):
    return Speaker.objects.create(
        conference=conference,
        pretalx_code="SPK1",
        name="Alice Johnson",
    )


@pytest.fixture
def talk(conference):
    return Talk.objects.create(
        conference=conference,
        pretalx_code="TALK1",
        title="Building Great APIs",
    )


@pytest.mark.django_db
class TestRoomStr:
    def test_str_returns_name(self, room):
        assert str(room) == "Hall A"

    def test_str_with_long_name(self, conference):
        long_name = "A" * 300
        room = Room.objects.create(conference=conference, pretalx_id=99, name=long_name)
        assert str(room) == long_name


@pytest.mark.django_db
class TestSpeakerStr:
    def test_str_returns_name(self, speaker):
        assert str(speaker) == "Alice Johnson"

    def test_str_with_single_name(self, conference):
        s = Speaker.objects.create(conference=conference, pretalx_code="SPK2", name="Guido")
        assert str(s) == "Guido"


@pytest.mark.django_db
class TestTalkStr:
    def test_str_returns_title(self, talk):
        assert str(talk) == "Building Great APIs"

    def test_str_with_different_title(self, conference):
        t = Talk.objects.create(conference=conference, pretalx_code="TALK2", title="Async Patterns")
        assert str(t) == "Async Patterns"


@pytest.mark.django_db
class TestScheduleSlotDisplayTitle:
    def test_display_title_with_talk(self, conference, room, talk):
        now = timezone.now()
        slot = ScheduleSlot.objects.create(
            conference=conference,
            room=room,
            talk=talk,
            title="Fallback Title",
            start=now,
            end=now,
            slot_type=ScheduleSlot.SlotType.TALK,
        )
        assert slot.display_title == "Building Great APIs"

    def test_display_title_without_talk(self, conference, room):
        now = timezone.now()
        slot = ScheduleSlot.objects.create(
            conference=conference,
            room=room,
            talk=None,
            title="Lunch Break",
            start=now,
            end=now,
            slot_type=ScheduleSlot.SlotType.BREAK,
        )
        assert slot.display_title == "Lunch Break"

    def test_str_delegates_to_display_title_with_talk(self, conference, room, talk):
        now = timezone.now()
        slot = ScheduleSlot.objects.create(
            conference=conference,
            room=room,
            talk=talk,
            title="Should Not Show",
            start=now,
            end=now,
            slot_type=ScheduleSlot.SlotType.TALK,
        )
        assert str(slot) == "Building Great APIs"

    def test_str_delegates_to_display_title_without_talk(self, conference, room):
        now = timezone.now()
        slot = ScheduleSlot.objects.create(
            conference=conference,
            room=room,
            talk=None,
            title="Social Event",
            start=now,
            end=now,
            slot_type=ScheduleSlot.SlotType.SOCIAL,
        )
        assert str(slot) == "Social Event"
