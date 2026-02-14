"""Tests for programs utility functions."""

from datetime import UTC, datetime

import pytest

from django_program.conference.models import Conference
from django_program.pretalx.models import Room, ScheduleSlot, Talk
from django_program.programs.utils import get_conference_days


@pytest.fixture
def conference(db) -> Conference:
    return Conference.objects.create(
        name="UtilCon",
        slug="utilcon",
        start_date=datetime(2027, 5, 14, tzinfo=UTC).date(),
        end_date=datetime(2027, 5, 18, tzinfo=UTC).date(),
        timezone="UTC",
    )


@pytest.fixture
def room(conference: Conference) -> Room:
    return Room.objects.create(conference=conference, pretalx_id=1, name="Main Hall")


@pytest.mark.django_db
def test_get_conference_days_no_schedule_data(conference: Conference):
    """Returns an empty list when the conference has no schedule slots."""
    assert get_conference_days(conference) == []


@pytest.mark.django_db
def test_get_conference_days_returns_sorted_dates(conference: Conference, room: Room):
    """Dates are sorted chronologically even when slots are created out of order."""
    talk_day2 = Talk.objects.create(
        conference=conference,
        pretalx_code="T2",
        title="Day 2 Talk",
        submission_type="Talk",
    )
    talk_day1 = Talk.objects.create(
        conference=conference,
        pretalx_code="T1",
        title="Day 1 Talk",
        submission_type="Talk",
    )
    # Create day 2 slot first to ensure sorting works
    ScheduleSlot.objects.create(
        conference=conference,
        talk=talk_day2,
        room=room,
        start=datetime(2027, 5, 16, 10, 0, tzinfo=UTC),
        end=datetime(2027, 5, 16, 11, 0, tzinfo=UTC),
        slot_type=ScheduleSlot.SlotType.TALK,
    )
    ScheduleSlot.objects.create(
        conference=conference,
        talk=talk_day1,
        room=Room.objects.create(conference=conference, pretalx_id=2, name="Room B"),
        start=datetime(2027, 5, 15, 10, 0, tzinfo=UTC),
        end=datetime(2027, 5, 15, 11, 0, tzinfo=UTC),
        slot_type=ScheduleSlot.SlotType.TALK,
    )

    result = get_conference_days(conference)
    assert len(result) == 2
    assert result[0][0] == "2027-05-15"
    assert result[1][0] == "2027-05-16"


@pytest.mark.django_db
def test_get_conference_days_dominant_type_labeled(conference: Conference, room: Room):
    """When one submission type accounts for more than half the slots, the label includes it."""
    for i in range(3):
        talk = Talk.objects.create(
            conference=conference,
            pretalx_code=f"TUT{i}",
            title=f"Tutorial {i}",
            submission_type="Tutorial",
        )
        ScheduleSlot.objects.create(
            conference=conference,
            talk=talk,
            room=Room.objects.create(conference=conference, pretalx_id=10 + i, name=f"Room {i}"),
            start=datetime(2027, 5, 14, 9 + i, 0, tzinfo=UTC),
            end=datetime(2027, 5, 14, 10 + i, 0, tzinfo=UTC),
            slot_type=ScheduleSlot.SlotType.TALK,
        )

    result = get_conference_days(conference)
    assert len(result) == 1
    iso_date, label = result[0]
    assert iso_date == "2027-05-14"
    assert "(Tutorial)" in label


@pytest.mark.django_db
def test_get_conference_days_mixed_day_no_suffix(conference: Conference, room: Room):
    """When no single type is dominant, the day label has no type suffix."""
    # 2 Talks, 2 Tutorials on the same day -- neither is > 50%
    for i, stype in enumerate(["Talk", "Talk", "Tutorial", "Tutorial"]):
        talk = Talk.objects.create(
            conference=conference,
            pretalx_code=f"MIX{i}",
            title=f"Mixed {i}",
            submission_type=stype,
        )
        ScheduleSlot.objects.create(
            conference=conference,
            talk=talk,
            room=Room.objects.create(conference=conference, pretalx_id=20 + i, name=f"Mix Room {i}"),
            start=datetime(2027, 5, 15, 9 + i, 0, tzinfo=UTC),
            end=datetime(2027, 5, 15, 10 + i, 0, tzinfo=UTC),
            slot_type=ScheduleSlot.SlotType.TALK,
        )

    result = get_conference_days(conference)
    assert len(result) == 1
    _iso, label = result[0]
    # No parenthesized type should appear
    assert "(" not in label
    assert ")" not in label


@pytest.mark.django_db
def test_get_conference_days_slots_without_talks(conference: Conference, room: Room):
    """Slots not linked to a talk (breaks, socials) produce a label with no type suffix."""
    ScheduleSlot.objects.create(
        conference=conference,
        talk=None,
        room=room,
        start=datetime(2027, 5, 14, 12, 0, tzinfo=UTC),
        end=datetime(2027, 5, 14, 13, 0, tzinfo=UTC),
        slot_type=ScheduleSlot.SlotType.BREAK,
        title="Lunch Break",
    )

    result = get_conference_days(conference)
    assert len(result) == 1
    iso_date, label = result[0]
    assert iso_date == "2027-05-14"
    # No type suffix for non-talk slots
    assert "(" not in label


@pytest.mark.django_db
def test_get_conference_days_talk_without_submission_type(conference: Conference, room: Room):
    """A talk with an empty submission_type does not contribute to type counts."""
    talk = Talk.objects.create(
        conference=conference,
        pretalx_code="NOTYPE",
        title="Untyped Talk",
        submission_type="",
    )
    ScheduleSlot.objects.create(
        conference=conference,
        talk=talk,
        room=room,
        start=datetime(2027, 5, 14, 14, 0, tzinfo=UTC),
        end=datetime(2027, 5, 14, 15, 0, tzinfo=UTC),
        slot_type=ScheduleSlot.SlotType.TALK,
    )

    result = get_conference_days(conference)
    assert len(result) == 1
    _iso, label = result[0]
    assert "(" not in label
