"""Tests for the pretalx admin configuration."""

from datetime import date

import pytest
from django.utils import timezone

from django_program.conference.models import Conference
from django_program.pretalx.admin import ScheduleSlotAdmin
from django_program.pretalx.models import Room, ScheduleSlot, Talk


@pytest.fixture
def conference(db):
    return Conference.objects.create(
        name="TestCon",
        slug="testcon-admin",
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


@pytest.mark.django_db
class TestScheduleSlotAdminDisplayTitle:
    def test_display_title_with_talk(self, conference, room):
        talk = Talk.objects.create(
            conference=conference,
            pretalx_code="TALK1",
            title="Admin Talk Title",
        )
        now = timezone.now()
        slot = ScheduleSlot.objects.create(
            conference=conference,
            room=room,
            talk=talk,
            title="Fallback",
            start=now,
            end=now,
            slot_type=ScheduleSlot.SlotType.TALK,
        )
        admin_instance = ScheduleSlotAdmin(ScheduleSlot, None)
        assert admin_instance.display_title(slot) == "Admin Talk Title"

    def test_display_title_without_talk(self, conference, room):
        now = timezone.now()
        slot = ScheduleSlot.objects.create(
            conference=conference,
            room=room,
            talk=None,
            title="Coffee Break",
            start=now,
            end=now,
            slot_type=ScheduleSlot.SlotType.BREAK,
        )
        admin_instance = ScheduleSlotAdmin(ScheduleSlot, None)
        assert admin_instance.display_title(slot) == "Coffee Break"
