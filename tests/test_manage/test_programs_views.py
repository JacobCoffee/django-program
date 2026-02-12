"""Tests for programs management views in the manage app."""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from django_program.conference.models import Conference
from django_program.programs.models import Activity, ActivitySignup, TravelGrant


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(username="admin", password="password", email="admin@test.com")


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(username="attendee", password="password")


@pytest.fixture
def conference(db):
    return Conference.objects.create(
        name="ProgramMgmt Conf",
        slug="program-mgmt",
        start_date=date(2027, 7, 1),
        end_date=date(2027, 7, 3),
        timezone="UTC",
        is_active=True,
    )


@pytest.fixture
def activity(conference):
    return Activity.objects.create(
        conference=conference,
        name="Django Sprint",
        slug="django-sprint",
        activity_type=Activity.ActivityType.SPRINT,
        is_active=True,
    )


@pytest.fixture
def grant(conference, regular_user):
    return TravelGrant.objects.create(
        conference=conference,
        user=regular_user,
        requested_amount=Decimal("500.00"),
        travel_from="Chicago",
        reason="Cannot afford travel",
    )


@pytest.fixture
def authed_client(client: Client, superuser):
    client.force_login(superuser)
    return client


# ---- Dashboard includes programs stats ----


@pytest.mark.django_db
def test_dashboard_includes_programs_stats(authed_client: Client, conference, activity, grant):
    url = reverse("manage:dashboard", kwargs={"conference_slug": conference.slug})
    response = authed_client.get(url)
    assert response.status_code == 200
    assert response.context["stats"]["activities"] == 1
    assert response.context["stats"]["travel_grants"] == 1


# ---- Activity views ----


@pytest.mark.django_db
def test_activity_manage_list(authed_client: Client, conference, activity):
    url = reverse("manage:activity-list", kwargs={"conference_slug": conference.slug})
    response = authed_client.get(url)
    assert response.status_code == 200
    assert activity in response.context["activities"]
    assert response.context["active_nav"] == "activities"


@pytest.mark.django_db
def test_activity_create_get(authed_client: Client, conference):
    url = reverse("manage:activity-add", kwargs={"conference_slug": conference.slug})
    response = authed_client.get(url)
    assert response.status_code == 200
    assert response.context["is_create"] is True


@pytest.mark.django_db
def test_activity_create_post(authed_client: Client, conference):
    url = reverse("manage:activity-add", kwargs={"conference_slug": conference.slug})
    response = authed_client.post(
        url,
        {
            "name": "Workshop Day",
            "slug": "workshop-day",
            "activity_type": "workshop",
            "is_active": "on",
        },
    )
    assert response.status_code == 302
    assert Activity.objects.filter(conference=conference, slug="workshop-day").exists()


@pytest.mark.django_db
def test_activity_edit_get(authed_client: Client, conference, activity, regular_user):
    ActivitySignup.objects.create(activity=activity, user=regular_user)
    url = reverse("manage:activity-edit", kwargs={"conference_slug": conference.slug, "pk": activity.pk})
    response = authed_client.get(url)
    assert response.status_code == 200
    assert response.context["activity"] == activity
    assert response.context["signup_count"] == 1


@pytest.mark.django_db
def test_activity_edit_post(authed_client: Client, conference, activity):
    url = reverse("manage:activity-edit", kwargs={"conference_slug": conference.slug, "pk": activity.pk})
    response = authed_client.post(
        url,
        {
            "name": "Updated Sprint",
            "slug": "django-sprint",
            "activity_type": "sprint",
            "is_active": "on",
        },
    )
    assert response.status_code == 302
    activity.refresh_from_db()
    assert activity.name == "Updated Sprint"


# ---- Travel Grant views ----


@pytest.mark.django_db
def test_travel_grant_manage_list(authed_client: Client, conference, grant):
    url = reverse("manage:travel-grant-list", kwargs={"conference_slug": conference.slug})
    response = authed_client.get(url)
    assert response.status_code == 200
    assert grant in response.context["grants"]
    assert response.context["active_nav"] == "travel-grants"


@pytest.mark.django_db
def test_travel_grant_manage_list_status_filter(authed_client: Client, conference, grant):
    url = reverse("manage:travel-grant-list", kwargs={"conference_slug": conference.slug})
    response = authed_client.get(url, {"status": "pending"})
    assert response.status_code == 200
    assert grant in response.context["grants"]

    response = authed_client.get(url, {"status": "approved"})
    assert list(response.context["grants"]) == []


@pytest.mark.django_db
def test_travel_grant_review_get(authed_client: Client, conference, grant):
    url = reverse("manage:travel-grant-review", kwargs={"conference_slug": conference.slug, "pk": grant.pk})
    response = authed_client.get(url)
    assert response.status_code == 200
    assert response.context["grant"] == grant
    assert response.context["active_nav"] == "travel-grants"


@pytest.mark.django_db
def test_travel_grant_review_post(authed_client: Client, conference, grant, superuser):
    url = reverse("manage:travel-grant-review", kwargs={"conference_slug": conference.slug, "pk": grant.pk})
    response = authed_client.post(
        url,
        {
            "status": "approved",
            "approved_amount": "400.00",
            "reviewer_notes": "Approved for reduced amount.",
        },
    )
    assert response.status_code == 302
    grant.refresh_from_db()
    assert grant.status == "approved"
    assert grant.approved_amount == Decimal("400.00")
    assert grant.reviewed_by == superuser
    assert grant.reviewed_at is not None
