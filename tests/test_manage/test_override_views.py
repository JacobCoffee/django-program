"""Tests for override management views (TalkOverride and SubmissionTypeDefault CRUD)."""

from datetime import date, timedelta

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from django_program.conference.models import Conference
from django_program.pretalx.models import Room, SubmissionTypeDefault, Talk, TalkOverride

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
def talk_override(talk, conference, superuser):
    return TalkOverride.objects.create(
        talk=talk,
        conference=conference,
        override_title="Overridden Title",
        note="Test override",
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
        assert resp.context["active_nav"] == "talks"
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
        assert resp.context["active_nav"] == "talks"

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
            kwargs={
                "conference_slug": conference.slug,
                "pk": talk_override.pk,
            },
        )
        resp = authed_client.get(url)
        assert resp.status_code == 200
        assert resp.context["is_create"] is False
        assert resp.context["active_nav"] == "talks"

    def test_post_updates_override(self, authed_client, conference, talk, talk_override):
        url = reverse(
            "manage:override-edit",
            kwargs={
                "conference_slug": conference.slug,
                "pk": talk_override.pk,
            },
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

    def test_edit_nonexistent_returns_404(self, authed_client, conference):
        url = reverse(
            "manage:override-edit",
            kwargs={
                "conference_slug": conference.slug,
                "pk": 99999,
            },
        )
        resp = authed_client.get(url)
        assert resp.status_code == 404


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
        assert resp.context["active_nav"] == "talks"
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
        assert resp.context["active_nav"] == "talks"

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
            kwargs={
                "conference_slug": conference.slug,
                "pk": type_default.pk,
            },
        )
        resp = authed_client.get(url)
        assert resp.status_code == 200
        assert resp.context["is_create"] is False
        assert resp.context["active_nav"] == "talks"

    def test_post_updates_default(self, authed_client, conference, type_default, room):
        url = reverse(
            "manage:type-default-edit",
            kwargs={
                "conference_slug": conference.slug,
                "pk": type_default.pk,
            },
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
            kwargs={
                "conference_slug": conference.slug,
                "pk": 99999,
            },
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

    def test_type_default_list_url(self):
        url = reverse("manage:type-default-list", kwargs={"conference_slug": "test-conf"})
        assert url == "/manage/test-conf/overrides/type-defaults/"

    def test_type_default_add_url(self):
        url = reverse("manage:type-default-add", kwargs={"conference_slug": "test-conf"})
        assert url == "/manage/test-conf/overrides/type-defaults/add/"

    def test_type_default_edit_url(self):
        url = reverse("manage:type-default-edit", kwargs={"conference_slug": "test-conf", "pk": 1})
        assert url == "/manage/test-conf/overrides/type-defaults/1/edit/"
