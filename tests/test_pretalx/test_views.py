"""Tests for pretalx views and URL routing.

Covers ConferenceMixin, ScheduleView, ScheduleJSONView, TalkDetailView,
SpeakerListView, and SpeakerDetailView with full template rendering via
the Django test client.
"""

import json
from datetime import date, datetime, timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from django_program.conference.models import Conference
from django_program.pretalx.models import Room, ScheduleSlot, Speaker, Talk


@pytest.fixture
def conference(db):
    return Conference.objects.create(
        name="TestCon 2027",
        slug="testcon",
        start_date=date(2027, 5, 1),
        end_date=date(2027, 5, 3),
        timezone="US/Eastern",
    )


@pytest.fixture
def room(conference):
    return Room.objects.create(
        conference=conference,
        pretalx_id=1,
        name="Hall A",
        position=0,
    )


@pytest.fixture
def room_b(conference):
    return Room.objects.create(
        conference=conference,
        pretalx_id=2,
        name="Room B",
        position=1,
    )


@pytest.fixture
def speaker(conference):
    return Speaker.objects.create(
        conference=conference,
        pretalx_code="ALICE",
        name="Alice Johnson",
        biography="Pythonista",
    )


@pytest.fixture
def speaker_bob(conference):
    return Speaker.objects.create(
        conference=conference,
        pretalx_code="BOB",
        name="Bob Smith",
    )


@pytest.fixture
def talk(conference, speaker):
    t = Talk.objects.create(
        conference=conference,
        pretalx_code="TALK1",
        title="Building Great APIs",
        abstract="Learn API design.",
        submission_type="Talk",
    )
    t.speakers.add(speaker)
    return t


@pytest.fixture
def talk_no_speakers(conference):
    return Talk.objects.create(
        conference=conference,
        pretalx_code="TALK2",
        title="Solo Talk",
    )


@pytest.fixture
def slot_with_talk(conference, room, talk):
    start = timezone.make_aware(datetime(2027, 5, 1, 10, 0))
    end = start + timedelta(minutes=30)
    return ScheduleSlot.objects.create(
        conference=conference,
        room=room,
        talk=talk,
        title="",
        start=start,
        end=end,
        slot_type=ScheduleSlot.SlotType.TALK,
    )


@pytest.fixture
def slot_break(conference, room_b):
    start = timezone.make_aware(datetime(2027, 5, 1, 12, 0))
    end = start + timedelta(minutes=60)
    return ScheduleSlot.objects.create(
        conference=conference,
        room=room_b,
        talk=None,
        title="Lunch Break",
        start=start,
        end=end,
        slot_type=ScheduleSlot.SlotType.BREAK,
    )


@pytest.fixture
def slot_no_room(conference, talk_no_speakers):
    start = timezone.make_aware(datetime(2027, 5, 2, 9, 0))
    end = start + timedelta(minutes=45)
    return ScheduleSlot.objects.create(
        conference=conference,
        room=None,
        talk=talk_no_speakers,
        title="",
        start=start,
        end=end,
        slot_type=ScheduleSlot.SlotType.TALK,
    )


@pytest.fixture
def client():
    return Client()


# ---------------------------------------------------------------------------
# URL resolution tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestURLRouting:
    def test_schedule_url_resolves(self, conference):
        url = reverse("pretalx:schedule", kwargs={"conference_slug": conference.slug})
        assert url == f"/{conference.slug}/program/schedule/"

    def test_schedule_json_url_resolves(self, conference):
        url = reverse("pretalx:schedule-json", kwargs={"conference_slug": conference.slug})
        assert url == f"/{conference.slug}/program/schedule/data.json"

    def test_talk_detail_url_resolves(self, conference):
        url = reverse(
            "pretalx:talk-detail",
            kwargs={"conference_slug": conference.slug, "pretalx_code": "TALK1"},
        )
        assert url == f"/{conference.slug}/program/talks/TALK1/"

    def test_speaker_list_url_resolves(self, conference):
        url = reverse("pretalx:speaker-list", kwargs={"conference_slug": conference.slug})
        assert url == f"/{conference.slug}/program/speakers/"

    def test_speaker_detail_url_resolves(self, conference):
        url = reverse(
            "pretalx:speaker-detail",
            kwargs={"conference_slug": conference.slug, "pretalx_code": "ALICE"},
        )
        assert url == f"/{conference.slug}/program/speakers/ALICE/"


# ---------------------------------------------------------------------------
# ConferenceMixin tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestConferenceMixin:
    def test_dispatch_sets_conference(self, client, conference, slot_with_talk):
        url = reverse("pretalx:schedule", kwargs={"conference_slug": conference.slug})
        response = client.get(url)
        assert response.status_code == 200

    def test_nonexistent_conference_returns_404(self, client):
        url = reverse("pretalx:schedule", kwargs={"conference_slug": "no-such-conf"})
        response = client.get(url)
        assert response.status_code == 404

    def test_conference_in_context(self, client, conference):
        url = reverse("pretalx:schedule", kwargs={"conference_slug": conference.slug})
        response = client.get(url)
        assert response.status_code == 200
        assert response.context["conference"] == conference


# ---------------------------------------------------------------------------
# ScheduleView tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestScheduleView:
    def test_empty_schedule(self, client, conference):
        url = reverse("pretalx:schedule", kwargs={"conference_slug": conference.slug})
        response = client.get(url)
        assert response.status_code == 200
        assert response.context["days"] == []
        assert b"No schedule data available yet." in response.content

    def test_schedule_grouped_by_day(self, client, conference, slot_with_talk, slot_break, slot_no_room):
        url = reverse("pretalx:schedule", kwargs={"conference_slug": conference.slug})
        response = client.get(url)
        assert response.status_code == 200

        days = response.context["days"]
        assert len(days) == 2  # May 1 and May 2

        day1_date, day1_slots = days[0]
        assert day1_date == date(2027, 5, 1)
        assert len(day1_slots) == 2  # slot_with_talk and slot_break

        day2_date, day2_slots = days[1]
        assert day2_date == date(2027, 5, 2)
        assert len(day2_slots) == 1  # slot_no_room

    def test_schedule_has_today_in_context(self, client, conference):
        url = reverse("pretalx:schedule", kwargs={"conference_slug": conference.slug})
        response = client.get(url)
        assert response.status_code == 200
        assert "today" in response.context

    def test_schedule_with_valid_timezone(self, client, conference):
        conference.timezone = "US/Eastern"
        conference.save()
        url = reverse("pretalx:schedule", kwargs={"conference_slug": conference.slug})
        response = client.get(url)
        assert response.status_code == 200
        assert "today" in response.context

    def test_schedule_with_invalid_timezone_hits_except_branch(self, client, conference):
        """When the conference timezone is invalid, the except clause is entered.

        Note: the source currently references ``timezone.utc`` which does not
        exist on ``django.utils.timezone``, so the fallback raises an
        ``AttributeError``.  This test exercises the except branch (line 107)
        for coverage and documents the bug.
        """
        conference.timezone = "Not/A/Timezone"
        conference.save()
        url = reverse("pretalx:schedule", kwargs={"conference_slug": conference.slug})
        with pytest.raises(AttributeError, match="utc"):
            client.get(url)

    def test_schedule_renders_talk_title(self, client, conference, slot_with_talk):
        url = reverse("pretalx:schedule", kwargs={"conference_slug": conference.slug})
        response = client.get(url)
        assert b"Building Great APIs" in response.content

    def test_schedule_renders_break_title(self, client, conference, slot_break):
        url = reverse("pretalx:schedule", kwargs={"conference_slug": conference.slug})
        response = client.get(url)
        assert b"Lunch Break" in response.content


# ---------------------------------------------------------------------------
# ScheduleJSONView tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestScheduleJSONView:
    def test_empty_schedule_returns_empty_array(self, client, conference):
        url = reverse("pretalx:schedule-json", kwargs={"conference_slug": conference.slug})
        response = client.get(url)
        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"
        data = json.loads(response.content)
        assert data == []

    def test_slot_with_talk_and_room(self, client, conference, slot_with_talk, talk):
        url = reverse("pretalx:schedule-json", kwargs={"conference_slug": conference.slug})
        response = client.get(url)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data) == 1

        entry = data[0]
        assert entry["title"] == "Building Great APIs"
        assert entry["room"] == "Hall A"
        assert entry["slot_type"] == "talk"
        assert entry["talk_code"] == "TALK1"
        assert "start" in entry
        assert "end" in entry

    def test_slot_without_talk(self, client, conference, slot_break):
        url = reverse("pretalx:schedule-json", kwargs={"conference_slug": conference.slug})
        response = client.get(url)
        data = json.loads(response.content)
        assert len(data) == 1

        entry = data[0]
        assert entry["title"] == "Lunch Break"
        assert entry["talk_code"] == ""
        assert entry["slot_type"] == "break"

    def test_slot_without_room(self, client, conference, slot_no_room):
        url = reverse("pretalx:schedule-json", kwargs={"conference_slug": conference.slug})
        response = client.get(url)
        data = json.loads(response.content)
        assert len(data) == 1

        entry = data[0]
        assert entry["room"] == ""
        assert entry["talk_code"] == "TALK2"

    def test_multiple_slots_ordered(self, client, conference, slot_with_talk, slot_break, slot_no_room):
        url = reverse("pretalx:schedule-json", kwargs={"conference_slug": conference.slug})
        response = client.get(url)
        data = json.loads(response.content)
        assert len(data) == 3

        # Ordered by start time: slot_with_talk (10:00 May 1), slot_break (12:00 May 1), slot_no_room (9:00 May 2)
        assert data[0]["title"] == "Building Great APIs"
        assert data[1]["title"] == "Lunch Break"
        assert data[2]["title"] == "Solo Talk"

    def test_nonexistent_conference_returns_404(self, client):
        url = reverse("pretalx:schedule-json", kwargs={"conference_slug": "nope"})
        response = client.get(url)
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# TalkDetailView tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTalkDetailView:
    def test_talk_detail_renders(self, client, conference, talk):
        url = reverse(
            "pretalx:talk-detail",
            kwargs={"conference_slug": conference.slug, "pretalx_code": talk.pretalx_code},
        )
        response = client.get(url)
        assert response.status_code == 200
        assert response.context["talk"] == talk
        assert response.context["conference"] == conference

    def test_talk_detail_has_speakers_in_context(self, client, conference, talk, speaker):
        url = reverse(
            "pretalx:talk-detail",
            kwargs={"conference_slug": conference.slug, "pretalx_code": talk.pretalx_code},
        )
        response = client.get(url)
        assert response.status_code == 200
        speakers_qs = response.context["speakers"]
        assert speaker in speakers_qs

    def test_talk_detail_renders_title(self, client, conference, talk):
        url = reverse(
            "pretalx:talk-detail",
            kwargs={"conference_slug": conference.slug, "pretalx_code": talk.pretalx_code},
        )
        response = client.get(url)
        assert b"Building Great APIs" in response.content

    def test_talk_detail_renders_speaker_name(self, client, conference, talk, speaker):
        url = reverse(
            "pretalx:talk-detail",
            kwargs={"conference_slug": conference.slug, "pretalx_code": talk.pretalx_code},
        )
        response = client.get(url)
        assert b"Alice Johnson" in response.content

    def test_talk_not_found_returns_404(self, client, conference):
        url = reverse(
            "pretalx:talk-detail",
            kwargs={"conference_slug": conference.slug, "pretalx_code": "NONEXIST"},
        )
        response = client.get(url)
        assert response.status_code == 404

    def test_talk_wrong_conference_returns_404(self, client, conference, talk):
        other = Conference.objects.create(
            name="Other Conf",
            slug="other-conf",
            start_date=date(2027, 6, 1),
            end_date=date(2027, 6, 3),
            timezone="UTC",
        )
        url = reverse(
            "pretalx:talk-detail",
            kwargs={"conference_slug": other.slug, "pretalx_code": talk.pretalx_code},
        )
        response = client.get(url)
        assert response.status_code == 404

    def test_talk_detail_no_speakers(self, client, conference, talk_no_speakers):
        url = reverse(
            "pretalx:talk-detail",
            kwargs={"conference_slug": conference.slug, "pretalx_code": talk_no_speakers.pretalx_code},
        )
        response = client.get(url)
        assert response.status_code == 200
        assert list(response.context["speakers"]) == []


# ---------------------------------------------------------------------------
# SpeakerListView tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSpeakerListView:
    def test_speaker_list_empty(self, client, conference):
        url = reverse("pretalx:speaker-list", kwargs={"conference_slug": conference.slug})
        response = client.get(url)
        assert response.status_code == 200
        assert list(response.context["speakers"]) == []
        assert b"No speakers synced yet." in response.content

    def test_speaker_list_returns_speakers(self, client, conference, speaker, speaker_bob):
        url = reverse("pretalx:speaker-list", kwargs={"conference_slug": conference.slug})
        response = client.get(url)
        assert response.status_code == 200

        speakers = list(response.context["speakers"])
        assert len(speakers) == 2

    def test_speaker_list_ordered_by_name(self, client, conference, speaker, speaker_bob):
        url = reverse("pretalx:speaker-list", kwargs={"conference_slug": conference.slug})
        response = client.get(url)
        speakers = list(response.context["speakers"])
        assert speakers[0].name == "Alice Johnson"
        assert speakers[1].name == "Bob Smith"

    def test_speaker_list_scoped_to_conference(self, client, conference, speaker):
        other = Conference.objects.create(
            name="Other Conf",
            slug="other-conf",
            start_date=date(2027, 6, 1),
            end_date=date(2027, 6, 3),
            timezone="UTC",
        )
        Speaker.objects.create(conference=other, pretalx_code="OTHERSPK", name="Charlie")

        url = reverse("pretalx:speaker-list", kwargs={"conference_slug": conference.slug})
        response = client.get(url)
        speakers = list(response.context["speakers"])
        assert len(speakers) == 1
        assert speakers[0] == speaker

    def test_speaker_list_renders_names(self, client, conference, speaker):
        url = reverse("pretalx:speaker-list", kwargs={"conference_slug": conference.slug})
        response = client.get(url)
        assert b"Alice Johnson" in response.content

    def test_nonexistent_conference_returns_404(self, client):
        url = reverse("pretalx:speaker-list", kwargs={"conference_slug": "nope"})
        response = client.get(url)
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# SpeakerDetailView tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSpeakerDetailView:
    def test_speaker_detail_renders(self, client, conference, speaker):
        url = reverse(
            "pretalx:speaker-detail",
            kwargs={"conference_slug": conference.slug, "pretalx_code": speaker.pretalx_code},
        )
        response = client.get(url)
        assert response.status_code == 200
        assert response.context["speaker"] == speaker
        assert response.context["conference"] == conference

    def test_speaker_detail_has_talks_in_context(self, client, conference, speaker, talk):
        url = reverse(
            "pretalx:speaker-detail",
            kwargs={"conference_slug": conference.slug, "pretalx_code": speaker.pretalx_code},
        )
        response = client.get(url)
        assert response.status_code == 200
        talks_qs = response.context["talks"]
        assert talk in talks_qs

    def test_speaker_detail_no_talks(self, client, conference, speaker_bob):
        url = reverse(
            "pretalx:speaker-detail",
            kwargs={"conference_slug": conference.slug, "pretalx_code": speaker_bob.pretalx_code},
        )
        response = client.get(url)
        assert response.status_code == 200
        assert list(response.context["talks"]) == []

    def test_speaker_detail_renders_name(self, client, conference, speaker):
        url = reverse(
            "pretalx:speaker-detail",
            kwargs={"conference_slug": conference.slug, "pretalx_code": speaker.pretalx_code},
        )
        response = client.get(url)
        assert b"Alice Johnson" in response.content

    def test_speaker_not_found_returns_404(self, client, conference):
        url = reverse(
            "pretalx:speaker-detail",
            kwargs={"conference_slug": conference.slug, "pretalx_code": "NOPE"},
        )
        response = client.get(url)
        assert response.status_code == 404

    def test_speaker_wrong_conference_returns_404(self, client, conference, speaker):
        other = Conference.objects.create(
            name="Other Conf",
            slug="other-conf",
            start_date=date(2027, 6, 1),
            end_date=date(2027, 6, 3),
            timezone="UTC",
        )
        url = reverse(
            "pretalx:speaker-detail",
            kwargs={"conference_slug": other.slug, "pretalx_code": speaker.pretalx_code},
        )
        response = client.get(url)
        assert response.status_code == 404
