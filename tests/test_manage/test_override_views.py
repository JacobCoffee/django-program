"""Tests for override management views (all override types and SubmissionTypeDefault CRUD)."""

from datetime import date, timedelta

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from django_program.conference.models import Conference
from django_program.manage.forms_overrides import SponsorOverrideForm, SubmissionTypeDefaultForm
from django_program.pretalx.models import (
    Room,
    RoomOverride,
    Speaker,
    SpeakerOverride,
    SubmissionTypeDefault,
    Talk,
    TalkOverride,
)
from django_program.sponsors.models import Sponsor, SponsorLevel, SponsorOverride

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(username="admin", password="password", email="admin@test.com")


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(username="regular", password="password", email="regular@test.com")


@pytest.fixture
def conference(db):
    return Conference.objects.create(
        name="Test Conf",
        slug="test-conf",
        start_date=date(2027, 5, 1),
        end_date=date(2027, 5, 3),
        timezone="UTC",
        pretalx_event_slug="test-event",
        is_active=True,
    )


@pytest.fixture
def room(conference):
    return Room.objects.create(conference=conference, pretalx_id=1, name="Main Hall", capacity=500, position=1)


@pytest.fixture
def talk(conference, room):
    return Talk.objects.create(
        conference=conference,
        pretalx_code="TALK1",
        title="My Great Talk",
        abstract="An abstract.",
        submission_type="Talk",
        state="confirmed",
        room=room,
        slot_start=timezone.now(),
        slot_end=timezone.now() + timedelta(hours=1),
    )


@pytest.fixture
def speaker(conference):
    return Speaker.objects.create(
        conference=conference,
        pretalx_code="SPK1",
        name="Alice Speaker",
        email="alice@test.com",
    )


@pytest.fixture
def sponsor_level(conference):
    return SponsorLevel.objects.create(
        conference=conference,
        name="Gold",
        slug="gold",
        cost=5000,
    )


@pytest.fixture
def sponsor(conference, sponsor_level):
    return Sponsor.objects.create(
        conference=conference,
        level=sponsor_level,
        name="Acme Corp",
        slug="acme-corp",
    )


@pytest.fixture
def talk_override(talk, conference, superuser):
    return TalkOverride.objects.create(
        talk=talk,
        conference=conference,
        override_title="Overridden Title",
        note="Test override",
        created_by=superuser,
    )


@pytest.fixture
def speaker_override(speaker, conference, superuser):
    return SpeakerOverride.objects.create(
        speaker=speaker,
        conference=conference,
        override_name="Bob Speaker",
        note="Test speaker override",
        created_by=superuser,
    )


@pytest.fixture
def room_override(room, conference, superuser):
    return RoomOverride.objects.create(
        room=room,
        conference=conference,
        override_name="Grand Hall",
        note="Test room override",
        created_by=superuser,
    )


@pytest.fixture
def sponsor_override(sponsor, conference, superuser):
    return SponsorOverride.objects.create(
        sponsor=sponsor,
        conference=conference,
        override_name="Acme Inc",
        note="Test sponsor override",
        created_by=superuser,
    )


@pytest.fixture
def type_default(conference, room):
    return SubmissionTypeDefault.objects.create(
        conference=conference,
        submission_type="Poster",
        default_room=room,
    )


@pytest.fixture
def authed_client(superuser):
    c = Client()
    c.login(username="admin", password="password")
    return c


@pytest.fixture
def anon_client():
    return Client()


@pytest.fixture
def regular_client(regular_user):
    c = Client()
    c.login(username="regular", password="password")
    return c


# ===========================================================================
# TalkOverride List View
# ===========================================================================


@pytest.mark.django_db
class TestTalkOverrideListView:
    def test_list_loads(self, authed_client, conference, talk_override):
        url = reverse("manage:override-list", kwargs={"conference_slug": conference.slug})
        resp = authed_client.get(url)
        assert resp.status_code == 200
        assert "overrides" in resp.context
        assert resp.context["active_nav"] == "overrides"
        assert resp.context["active_override_tab"] == "talks"
        overrides = list(resp.context["overrides"])
        assert len(overrides) == 1

    def test_list_empty(self, authed_client, conference):
        url = reverse("manage:override-list", kwargs={"conference_slug": conference.slug})
        resp = authed_client.get(url)
        assert resp.status_code == 200
        assert list(resp.context["overrides"]) == []

    def test_anonymous_redirect(self, anon_client, conference):
        url = reverse("manage:override-list", kwargs={"conference_slug": conference.slug})
        resp = anon_client.get(url)
        assert resp.status_code == 302

    def test_regular_user_forbidden(self, regular_client, conference):
        url = reverse("manage:override-list", kwargs={"conference_slug": conference.slug})
        resp = regular_client.get(url)
        assert resp.status_code == 403


# ===========================================================================
# TalkOverride Create View
# ===========================================================================


@pytest.mark.django_db
class TestTalkOverrideCreateView:
    def test_get_create_form(self, authed_client, conference, talk):
        url = reverse("manage:override-add", kwargs={"conference_slug": conference.slug})
        resp = authed_client.get(url)
        assert resp.status_code == 200
        assert resp.context["is_create"] is True
        assert resp.context["active_nav"] == "overrides"

    def test_get_create_form_with_talk_prepopulated(self, authed_client, conference, talk):
        url = reverse("manage:override-add", kwargs={"conference_slug": conference.slug})
        resp = authed_client.get(url, {"talk": talk.pk})
        assert resp.status_code == 200
        assert resp.context["is_create"] is True
        assert resp.context["form"].initial.get("talk") == str(talk.pk)

    def test_post_creates_override(self, authed_client, conference, talk, superuser):
        url = reverse("manage:override-add", kwargs={"conference_slug": conference.slug})
        resp = authed_client.post(
            url,
            {
                "talk": talk.pk,
                "override_title": "New Title",
                "override_state": "",
                "override_abstract": "",
                "override_room": "",
                "override_slot_start": "",
                "override_slot_end": "",
                "is_cancelled": False,
                "note": "created via test",
            },
        )
        assert resp.status_code == 302
        expected_url = reverse("manage:override-list", kwargs={"conference_slug": conference.slug})
        assert resp.url == expected_url

        override = TalkOverride.objects.get(talk=talk)
        assert override.override_title == "New Title"
        assert override.conference == conference
        assert override.created_by == superuser

    def test_anonymous_redirect(self, anon_client, conference):
        url = reverse("manage:override-add", kwargs={"conference_slug": conference.slug})
        resp = anon_client.get(url)
        assert resp.status_code == 302


# ===========================================================================
# TalkOverride Edit View
# ===========================================================================


@pytest.mark.django_db
class TestTalkOverrideEditView:
    def test_get_edit_form(self, authed_client, conference, talk_override):
        url = reverse(
            "manage:override-edit",
            kwargs={"conference_slug": conference.slug, "pk": talk_override.pk},
        )
        resp = authed_client.get(url)
        assert resp.status_code == 200
        assert resp.context["is_create"] is False
        assert resp.context["active_nav"] == "overrides"

    def test_post_updates_override(self, authed_client, conference, talk, talk_override):
        url = reverse(
            "manage:override-edit",
            kwargs={"conference_slug": conference.slug, "pk": talk_override.pk},
        )
        resp = authed_client.post(
            url,
            {
                "talk": talk.pk,
                "override_title": "Updated Title",
                "override_state": "",
                "override_abstract": "",
                "override_room": "",
                "override_slot_start": "",
                "override_slot_end": "",
                "is_cancelled": False,
                "note": "updated",
            },
        )
        assert resp.status_code == 302
        talk_override.refresh_from_db()
        assert talk_override.override_title == "Updated Title"

    def test_edit_empty_deletes_override(self, authed_client, conference, talk, talk_override):
        url = reverse(
            "manage:override-edit",
            kwargs={"conference_slug": conference.slug, "pk": talk_override.pk},
        )
        resp = authed_client.post(
            url,
            {
                "talk": talk.pk,
                "override_title": "",
                "override_state": "",
                "override_abstract": "",
                "override_room": "",
                "override_slot_start": "",
                "override_slot_end": "",
                "is_cancelled": False,
                "note": "",
            },
        )
        assert resp.status_code == 302
        assert not TalkOverride.objects.filter(pk=talk_override.pk).exists()

    def test_edit_nonexistent_returns_404(self, authed_client, conference):
        url = reverse(
            "manage:override-edit",
            kwargs={"conference_slug": conference.slug, "pk": 99999},
        )
        resp = authed_client.get(url)
        assert resp.status_code == 404


# ===========================================================================
# SpeakerOverride Views
# ===========================================================================


@pytest.mark.django_db
class TestSpeakerOverrideListView:
    def test_list_loads(self, authed_client, conference, speaker_override):
        url = reverse("manage:speaker-override-list", kwargs={"conference_slug": conference.slug})
        resp = authed_client.get(url)
        assert resp.status_code == 200
        assert resp.context["active_override_tab"] == "speakers"
        assert len(list(resp.context["overrides"])) == 1

    def test_anonymous_redirect(self, anon_client, conference):
        url = reverse("manage:speaker-override-list", kwargs={"conference_slug": conference.slug})
        resp = anon_client.get(url)
        assert resp.status_code == 302


@pytest.mark.django_db
class TestSpeakerOverrideCreateView:
    def test_get_create_form(self, authed_client, conference, speaker):
        url = reverse("manage:speaker-override-add", kwargs={"conference_slug": conference.slug})
        resp = authed_client.get(url)
        assert resp.status_code == 200
        assert resp.context["is_create"] is True

    def test_get_create_form_with_speaker_prepopulated(self, authed_client, conference, speaker):
        url = reverse("manage:speaker-override-add", kwargs={"conference_slug": conference.slug})
        resp = authed_client.get(url, {"speaker": speaker.pk})
        assert resp.status_code == 200
        assert resp.context["is_create"] is True
        assert resp.context["form"].initial.get("speaker") == str(speaker.pk)

    def test_post_creates_override(self, authed_client, conference, speaker, superuser):
        url = reverse("manage:speaker-override-add", kwargs={"conference_slug": conference.slug})
        resp = authed_client.post(
            url,
            {
                "speaker": speaker.pk,
                "override_name": "New Name",
                "override_biography": "",
                "override_avatar_url": "",
                "override_email": "",
                "note": "test",
            },
        )
        assert resp.status_code == 302
        override = SpeakerOverride.objects.get(speaker=speaker)
        assert override.override_name == "New Name"
        assert override.created_by == superuser


@pytest.mark.django_db
class TestSpeakerOverrideEditView:
    def test_get_edit_form(self, authed_client, conference, speaker_override):
        url = reverse(
            "manage:speaker-override-edit",
            kwargs={"conference_slug": conference.slug, "pk": speaker_override.pk},
        )
        resp = authed_client.get(url)
        assert resp.status_code == 200
        assert resp.context["is_create"] is False
        assert resp.context["active_override_tab"] == "speakers"

    def test_post_updates(self, authed_client, conference, speaker, speaker_override):
        url = reverse(
            "manage:speaker-override-edit",
            kwargs={"conference_slug": conference.slug, "pk": speaker_override.pk},
        )
        resp = authed_client.post(
            url,
            {
                "speaker": speaker.pk,
                "override_name": "Updated Name",
                "override_biography": "",
                "override_avatar_url": "",
                "override_email": "",
                "note": "",
            },
        )
        assert resp.status_code == 302
        speaker_override.refresh_from_db()
        assert speaker_override.override_name == "Updated Name"

    def test_edit_empty_deletes(self, authed_client, conference, speaker, speaker_override):
        url = reverse(
            "manage:speaker-override-edit",
            kwargs={"conference_slug": conference.slug, "pk": speaker_override.pk},
        )
        resp = authed_client.post(
            url,
            {
                "speaker": speaker.pk,
                "override_name": "",
                "override_biography": "",
                "override_avatar_url": "",
                "override_email": "",
                "note": "",
            },
        )
        assert resp.status_code == 302
        assert not SpeakerOverride.objects.filter(pk=speaker_override.pk).exists()


# ===========================================================================
# RoomOverride Views
# ===========================================================================


@pytest.mark.django_db
class TestRoomOverrideListView:
    def test_list_loads(self, authed_client, conference, room_override):
        url = reverse("manage:room-override-list", kwargs={"conference_slug": conference.slug})
        resp = authed_client.get(url)
        assert resp.status_code == 200
        assert resp.context["active_override_tab"] == "rooms"
        assert len(list(resp.context["overrides"])) == 1

    def test_anonymous_redirect(self, anon_client, conference):
        url = reverse("manage:room-override-list", kwargs={"conference_slug": conference.slug})
        resp = anon_client.get(url)
        assert resp.status_code == 302


@pytest.mark.django_db
class TestRoomOverrideCreateView:
    def test_get_create_form(self, authed_client, conference, room):
        url = reverse("manage:room-override-add", kwargs={"conference_slug": conference.slug})
        resp = authed_client.get(url)
        assert resp.status_code == 200
        assert resp.context["is_create"] is True

    def test_get_create_form_with_room_prepopulated(self, authed_client, conference, room):
        url = reverse("manage:room-override-add", kwargs={"conference_slug": conference.slug})
        resp = authed_client.get(url, {"room": room.pk})
        assert resp.status_code == 200
        assert resp.context["is_create"] is True
        assert resp.context["form"].initial.get("room") == str(room.pk)

    def test_post_creates_override(self, authed_client, conference, room, superuser):
        url = reverse("manage:room-override-add", kwargs={"conference_slug": conference.slug})
        resp = authed_client.post(
            url,
            {
                "room": room.pk,
                "override_name": "New Room Name",
                "override_description": "",
                "override_capacity": "",
                "note": "test",
            },
        )
        assert resp.status_code == 302
        override = RoomOverride.objects.get(room=room)
        assert override.override_name == "New Room Name"
        assert override.created_by == superuser


@pytest.mark.django_db
class TestRoomOverrideEditView:
    def test_get_edit_form(self, authed_client, conference, room_override):
        url = reverse(
            "manage:room-override-edit",
            kwargs={"conference_slug": conference.slug, "pk": room_override.pk},
        )
        resp = authed_client.get(url)
        assert resp.status_code == 200
        assert resp.context["is_create"] is False
        assert resp.context["active_override_tab"] == "rooms"

    def test_post_updates(self, authed_client, conference, room, room_override):
        url = reverse(
            "manage:room-override-edit",
            kwargs={"conference_slug": conference.slug, "pk": room_override.pk},
        )
        resp = authed_client.post(
            url,
            {
                "room": room.pk,
                "override_name": "Updated Room",
                "override_description": "",
                "override_capacity": "",
                "note": "",
            },
        )
        assert resp.status_code == 302
        room_override.refresh_from_db()
        assert room_override.override_name == "Updated Room"

    def test_edit_empty_deletes(self, authed_client, conference, room, room_override):
        url = reverse(
            "manage:room-override-edit",
            kwargs={"conference_slug": conference.slug, "pk": room_override.pk},
        )
        resp = authed_client.post(
            url,
            {
                "room": room.pk,
                "override_name": "",
                "override_description": "",
                "override_capacity": "",
                "note": "",
            },
        )
        assert resp.status_code == 302
        assert not RoomOverride.objects.filter(pk=room_override.pk).exists()


# ===========================================================================
# SponsorOverride Views
# ===========================================================================


@pytest.mark.django_db
class TestSponsorOverrideListView:
    def test_list_loads(self, authed_client, conference, sponsor_override):
        url = reverse("manage:sponsor-override-list", kwargs={"conference_slug": conference.slug})
        resp = authed_client.get(url)
        assert resp.status_code == 200
        assert resp.context["active_override_tab"] == "sponsors"
        assert len(list(resp.context["overrides"])) == 1

    def test_anonymous_redirect(self, anon_client, conference):
        url = reverse("manage:sponsor-override-list", kwargs={"conference_slug": conference.slug})
        resp = anon_client.get(url)
        assert resp.status_code == 302


@pytest.mark.django_db
class TestSponsorOverrideCreateView:
    def test_get_create_form(self, authed_client, conference, sponsor):
        url = reverse("manage:sponsor-override-add", kwargs={"conference_slug": conference.slug})
        resp = authed_client.get(url)
        assert resp.status_code == 200
        assert resp.context["is_create"] is True

    def test_get_create_form_with_sponsor_prepopulated(self, authed_client, conference, sponsor):
        url = reverse("manage:sponsor-override-add", kwargs={"conference_slug": conference.slug})
        resp = authed_client.get(url, {"sponsor": sponsor.pk})
        assert resp.status_code == 200
        assert resp.context["is_create"] is True
        assert resp.context["form"].initial.get("sponsor") == str(sponsor.pk)

    def test_post_creates_override(self, authed_client, conference, sponsor, superuser):
        url = reverse("manage:sponsor-override-add", kwargs={"conference_slug": conference.slug})
        resp = authed_client.post(
            url,
            {
                "sponsor": sponsor.pk,
                "override_name": "Acme Inc",
                "override_description": "",
                "override_website_url": "",
                "override_logo_url": "",
                "override_contact_name": "",
                "override_contact_email": "",
                "override_is_active": "",
                "override_level": "",
                "note": "test",
            },
        )
        assert resp.status_code == 302
        override = SponsorOverride.objects.get(sponsor=sponsor)
        assert override.override_name == "Acme Inc"
        assert override.created_by == superuser


@pytest.mark.django_db
class TestSponsorOverrideEditView:
    def test_get_edit_form(self, authed_client, conference, sponsor_override):
        url = reverse(
            "manage:sponsor-override-edit",
            kwargs={"conference_slug": conference.slug, "pk": sponsor_override.pk},
        )
        resp = authed_client.get(url)
        assert resp.status_code == 200
        assert resp.context["is_create"] is False
        assert resp.context["active_override_tab"] == "sponsors"

    def test_post_updates(self, authed_client, conference, sponsor, sponsor_override):
        url = reverse(
            "manage:sponsor-override-edit",
            kwargs={"conference_slug": conference.slug, "pk": sponsor_override.pk},
        )
        resp = authed_client.post(
            url,
            {
                "sponsor": sponsor.pk,
                "override_name": "Updated Corp",
                "override_description": "",
                "override_website_url": "",
                "override_logo_url": "",
                "override_contact_name": "",
                "override_contact_email": "",
                "override_is_active": "",
                "override_level": "",
                "note": "",
            },
        )
        assert resp.status_code == 302
        sponsor_override.refresh_from_db()
        assert sponsor_override.override_name == "Updated Corp"

    def test_edit_empty_deletes(self, authed_client, conference, sponsor, sponsor_override):
        url = reverse(
            "manage:sponsor-override-edit",
            kwargs={"conference_slug": conference.slug, "pk": sponsor_override.pk},
        )
        resp = authed_client.post(
            url,
            {
                "sponsor": sponsor.pk,
                "override_name": "",
                "override_description": "",
                "override_website_url": "",
                "override_logo_url": "",
                "override_contact_name": "",
                "override_contact_email": "",
                "override_is_active": "",
                "override_level": "",
                "note": "",
            },
        )
        assert resp.status_code == 302
        assert not SponsorOverride.objects.filter(pk=sponsor_override.pk).exists()


# ===========================================================================
# SubmissionTypeDefault List View
# ===========================================================================


@pytest.mark.django_db
class TestSubmissionTypeDefaultListView:
    def test_list_loads(self, authed_client, conference, type_default):
        url = reverse("manage:type-default-list", kwargs={"conference_slug": conference.slug})
        resp = authed_client.get(url)
        assert resp.status_code == 200
        assert "type_defaults" in resp.context
        assert resp.context["active_nav"] == "overrides"
        defaults = list(resp.context["type_defaults"])
        assert len(defaults) == 1

    def test_anonymous_redirect(self, anon_client, conference):
        url = reverse("manage:type-default-list", kwargs={"conference_slug": conference.slug})
        resp = anon_client.get(url)
        assert resp.status_code == 302

    def test_regular_user_forbidden(self, regular_client, conference):
        url = reverse("manage:type-default-list", kwargs={"conference_slug": conference.slug})
        resp = regular_client.get(url)
        assert resp.status_code == 403


# ===========================================================================
# SubmissionTypeDefault Create View
# ===========================================================================


@pytest.mark.django_db
class TestSubmissionTypeDefaultCreateView:
    def test_get_create_form(self, authed_client, conference):
        url = reverse("manage:type-default-add", kwargs={"conference_slug": conference.slug})
        resp = authed_client.get(url)
        assert resp.status_code == 200
        assert resp.context["is_create"] is True
        assert resp.context["active_nav"] == "overrides"

    def test_post_creates_default(self, authed_client, conference, room):
        url = reverse("manage:type-default-add", kwargs={"conference_slug": conference.slug})
        resp = authed_client.post(
            url,
            {
                "submission_type": "Tutorial",
                "default_room": room.pk,
                "default_date": "2027-05-01",
                "default_start_time": "09:00",
                "default_end_time": "17:00",
            },
        )
        assert resp.status_code == 302
        expected_url = reverse("manage:type-default-list", kwargs={"conference_slug": conference.slug})
        assert resp.url == expected_url

        td = SubmissionTypeDefault.objects.get(conference=conference, submission_type="Tutorial")
        assert td.default_room == room
        assert td.conference == conference

    def test_anonymous_redirect(self, anon_client, conference):
        url = reverse("manage:type-default-add", kwargs={"conference_slug": conference.slug})
        resp = anon_client.get(url)
        assert resp.status_code == 302


# ===========================================================================
# SubmissionTypeDefault Edit View
# ===========================================================================


@pytest.mark.django_db
class TestSubmissionTypeDefaultEditView:
    def test_get_edit_form(self, authed_client, conference, type_default):
        url = reverse(
            "manage:type-default-edit",
            kwargs={"conference_slug": conference.slug, "pk": type_default.pk},
        )
        resp = authed_client.get(url)
        assert resp.status_code == 200
        assert resp.context["is_create"] is False
        assert resp.context["active_nav"] == "overrides"

    def test_post_updates_default(self, authed_client, conference, type_default, room):
        url = reverse(
            "manage:type-default-edit",
            kwargs={"conference_slug": conference.slug, "pk": type_default.pk},
        )
        resp = authed_client.post(
            url,
            {
                "submission_type": "Workshop",
                "default_room": room.pk,
                "default_date": "",
                "default_start_time": "",
                "default_end_time": "",
            },
        )
        assert resp.status_code == 302
        type_default.refresh_from_db()
        assert type_default.submission_type == "Workshop"

    def test_edit_nonexistent_returns_404(self, authed_client, conference):
        url = reverse(
            "manage:type-default-edit",
            kwargs={"conference_slug": conference.slug, "pk": 99999},
        )
        resp = authed_client.get(url)
        assert resp.status_code == 404


# ===========================================================================
# URL Resolution Tests
# ===========================================================================


class TestOverrideURLResolution:
    def test_override_list_url(self):
        url = reverse("manage:override-list", kwargs={"conference_slug": "test-conf"})
        assert url == "/manage/test-conf/overrides/talks/"

    def test_override_add_url(self):
        url = reverse("manage:override-add", kwargs={"conference_slug": "test-conf"})
        assert url == "/manage/test-conf/overrides/talks/add/"

    def test_override_edit_url(self):
        url = reverse("manage:override-edit", kwargs={"conference_slug": "test-conf", "pk": 1})
        assert url == "/manage/test-conf/overrides/talks/1/edit/"

    def test_speaker_override_list_url(self):
        url = reverse("manage:speaker-override-list", kwargs={"conference_slug": "test-conf"})
        assert url == "/manage/test-conf/overrides/speakers/"

    def test_speaker_override_add_url(self):
        url = reverse("manage:speaker-override-add", kwargs={"conference_slug": "test-conf"})
        assert url == "/manage/test-conf/overrides/speakers/add/"

    def test_speaker_override_edit_url(self):
        url = reverse("manage:speaker-override-edit", kwargs={"conference_slug": "test-conf", "pk": 1})
        assert url == "/manage/test-conf/overrides/speakers/1/edit/"

    def test_room_override_list_url(self):
        url = reverse("manage:room-override-list", kwargs={"conference_slug": "test-conf"})
        assert url == "/manage/test-conf/overrides/rooms/"

    def test_room_override_add_url(self):
        url = reverse("manage:room-override-add", kwargs={"conference_slug": "test-conf"})
        assert url == "/manage/test-conf/overrides/rooms/add/"

    def test_room_override_edit_url(self):
        url = reverse("manage:room-override-edit", kwargs={"conference_slug": "test-conf", "pk": 1})
        assert url == "/manage/test-conf/overrides/rooms/1/edit/"

    def test_sponsor_override_list_url(self):
        url = reverse("manage:sponsor-override-list", kwargs={"conference_slug": "test-conf"})
        assert url == "/manage/test-conf/overrides/sponsors/"

    def test_sponsor_override_add_url(self):
        url = reverse("manage:sponsor-override-add", kwargs={"conference_slug": "test-conf"})
        assert url == "/manage/test-conf/overrides/sponsors/add/"

    def test_sponsor_override_edit_url(self):
        url = reverse("manage:sponsor-override-edit", kwargs={"conference_slug": "test-conf", "pk": 1})
        assert url == "/manage/test-conf/overrides/sponsors/1/edit/"

    def test_type_default_list_url(self):
        url = reverse("manage:type-default-list", kwargs={"conference_slug": "test-conf"})
        assert url == "/manage/test-conf/overrides/type-defaults/"

    def test_type_default_add_url(self):
        url = reverse("manage:type-default-add", kwargs={"conference_slug": "test-conf"})
        assert url == "/manage/test-conf/overrides/type-defaults/add/"

    def test_type_default_edit_url(self):
        url = reverse("manage:type-default-edit", kwargs={"conference_slug": "test-conf", "pk": 1})
        assert url == "/manage/test-conf/overrides/type-defaults/1/edit/"


# ===========================================================================
# SubmissionTypeDefaultForm Validation
# ===========================================================================


@pytest.mark.django_db
class TestSubmissionTypeDefaultFormValidation:
    """Validate that SubmissionTypeDefaultForm.clean() enforces time/date consistency."""

    def test_valid_with_all_time_fields(self, conference, room):
        form = SubmissionTypeDefaultForm(
            data={
                "submission_type": "Tutorial",
                "default_room": room.pk,
                "default_date": "2027-05-01",
                "default_start_time": "09:00",
                "default_end_time": "17:00",
            },
            conference=conference,
        )
        assert form.is_valid(), form.errors

    def test_valid_with_no_time_fields(self, conference, room):
        form = SubmissionTypeDefaultForm(
            data={
                "submission_type": "Tutorial",
                "default_room": room.pk,
                "default_date": "",
                "default_start_time": "",
                "default_end_time": "",
            },
            conference=conference,
        )
        assert form.is_valid(), form.errors

    def test_valid_with_date_only(self, conference, room):
        form = SubmissionTypeDefaultForm(
            data={
                "submission_type": "Tutorial",
                "default_room": room.pk,
                "default_date": "2027-05-01",
                "default_start_time": "",
                "default_end_time": "",
            },
            conference=conference,
        )
        assert form.is_valid(), form.errors

    def test_rejects_start_time_without_date(self, conference, room):
        form = SubmissionTypeDefaultForm(
            data={
                "submission_type": "Tutorial",
                "default_room": room.pk,
                "default_date": "",
                "default_start_time": "09:00",
                "default_end_time": "17:00",
            },
            conference=conference,
        )
        assert not form.is_valid()
        assert "default_date" in form.errors

    def test_rejects_end_time_without_date(self, conference, room):
        form = SubmissionTypeDefaultForm(
            data={
                "submission_type": "Tutorial",
                "default_room": room.pk,
                "default_date": "",
                "default_start_time": "",
                "default_end_time": "17:00",
            },
            conference=conference,
        )
        assert not form.is_valid()
        assert "default_date" in form.errors

    def test_rejects_start_time_without_end_time(self, conference, room):
        form = SubmissionTypeDefaultForm(
            data={
                "submission_type": "Tutorial",
                "default_room": room.pk,
                "default_date": "2027-05-01",
                "default_start_time": "09:00",
                "default_end_time": "",
            },
            conference=conference,
        )
        assert not form.is_valid()
        assert "default_end_time" in form.errors

    def test_rejects_end_time_without_start_time(self, conference, room):
        form = SubmissionTypeDefaultForm(
            data={
                "submission_type": "Tutorial",
                "default_room": room.pk,
                "default_date": "2027-05-01",
                "default_start_time": "",
                "default_end_time": "17:00",
            },
            conference=conference,
        )
        assert not form.is_valid()
        assert "default_start_time" in form.errors

    def test_post_rejects_times_without_date_via_view(self, authed_client, conference, room):
        url = reverse("manage:type-default-add", kwargs={"conference_slug": conference.slug})
        resp = authed_client.post(
            url,
            {
                "submission_type": "Tutorial",
                "default_room": room.pk,
                "default_date": "",
                "default_start_time": "09:00",
                "default_end_time": "17:00",
            },
        )
        assert resp.status_code == 200
        assert resp.context["form"].errors


# ===========================================================================
# SponsorOverrideForm.clean_override_is_active
# ===========================================================================


@pytest.mark.django_db
class TestSponsorOverrideFormIsActive:
    """Validate that override_is_active converts string widget values correctly."""

    def test_empty_string_becomes_none(self, conference, sponsor):
        form = SponsorOverrideForm(
            data={
                "sponsor": sponsor.pk,
                "override_name": "",
                "override_description": "",
                "override_website_url": "",
                "override_logo_url": "",
                "override_contact_name": "",
                "override_contact_email": "",
                "override_is_active": "",
                "override_level": "",
                "note": "",
            },
            conference=conference,
        )
        assert form.is_valid(), form.errors
        assert form.cleaned_data["override_is_active"] is None

    def test_true_string_becomes_true(self, conference, sponsor):
        form = SponsorOverrideForm(
            data={
                "sponsor": sponsor.pk,
                "override_name": "",
                "override_description": "",
                "override_website_url": "",
                "override_logo_url": "",
                "override_contact_name": "",
                "override_contact_email": "",
                "override_is_active": "True",
                "override_level": "",
                "note": "",
            },
            conference=conference,
        )
        assert form.is_valid(), form.errors
        assert form.cleaned_data["override_is_active"] is True

    def test_false_string_becomes_false(self, conference, sponsor):
        form = SponsorOverrideForm(
            data={
                "sponsor": sponsor.pk,
                "override_name": "",
                "override_description": "",
                "override_website_url": "",
                "override_logo_url": "",
                "override_contact_name": "",
                "override_contact_email": "",
                "override_is_active": "False",
                "override_level": "",
                "note": "",
            },
            conference=conference,
        )
        assert form.is_valid(), form.errors
        assert form.cleaned_data["override_is_active"] is False

    def test_unexpected_value_becomes_none(self, conference, sponsor):
        form = SponsorOverrideForm(
            data={
                "sponsor": sponsor.pk,
                "override_name": "",
                "override_description": "",
                "override_website_url": "",
                "override_logo_url": "",
                "override_contact_name": "",
                "override_contact_email": "",
                "override_is_active": "maybe",
                "override_level": "",
                "note": "",
            },
            conference=conference,
        )
        assert form.is_valid(), form.errors
        assert form.cleaned_data["override_is_active"] is None
