"""Tests for programs views."""

from datetime import date

import pytest
from django.contrib.auth.models import User
from django.test import Client

from django_program.conference.models import Conference
from django_program.programs.models import Activity, ActivitySignup, TravelGrant


@pytest.fixture
def conference() -> Conference:
    return Conference.objects.create(
        name="ViewCon",
        slug="viewcon",
        start_date=date(2027, 8, 1),
        end_date=date(2027, 8, 3),
        timezone="UTC",
    )


@pytest.fixture
def user() -> User:
    return User.objects.create_user(username="testuser", password="testpass123")


@pytest.fixture
def activity(conference: Conference) -> Activity:
    return Activity.objects.create(
        conference=conference,
        name="Sprint Day",
        slug="sprint-day",
        activity_type=Activity.ActivityType.SPRINT,
        is_active=True,
    )


@pytest.mark.django_db
def test_activity_list_view(client: Client, conference: Conference, activity: Activity):
    response = client.get(f"/{conference.slug}/programs/")
    assert response.status_code == 200
    assert activity in response.context["activities"]


@pytest.mark.django_db
def test_activity_list_excludes_inactive(client: Client, conference: Conference):
    Activity.objects.create(
        conference=conference,
        name="Hidden",
        slug="hidden",
        activity_type=Activity.ActivityType.OTHER,
        is_active=False,
    )
    response = client.get(f"/{conference.slug}/programs/")
    assert response.status_code == 200
    assert list(response.context["activities"]) == []


@pytest.mark.django_db
def test_activity_detail_view(client: Client, conference: Conference, activity: Activity):
    response = client.get(f"/{conference.slug}/programs/{activity.slug}/")
    assert response.status_code == 200
    assert response.context["activity"] == activity


@pytest.mark.django_db
def test_activity_detail_404_for_inactive(client: Client, conference: Conference):
    inactive = Activity.objects.create(
        conference=conference,
        name="Inactive",
        slug="inactive",
        activity_type=Activity.ActivityType.OTHER,
        is_active=False,
    )
    response = client.get(f"/{conference.slug}/programs/{inactive.slug}/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_activity_signup_creates_signup(client: Client, conference: Conference, activity: Activity, user: User):
    client.force_login(user)
    response = client.post(f"/{conference.slug}/programs/{activity.slug}/signup/")
    assert response.status_code == 302
    assert ActivitySignup.objects.filter(activity=activity, user=user).exists()


@pytest.mark.django_db
def test_activity_signup_requires_login(client: Client, conference: Conference, activity: Activity):
    response = client.post(f"/{conference.slug}/programs/{activity.slug}/signup/")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url or "login" in response.url


@pytest.mark.django_db
def test_activity_signup_full(client: Client, conference: Conference, user: User):
    full_activity = Activity.objects.create(
        conference=conference,
        name="Full Event",
        slug="full-event",
        activity_type=Activity.ActivityType.WORKSHOP,
        max_participants=0,
        is_active=True,
    )
    client.force_login(user)
    response = client.post(f"/{conference.slug}/programs/{full_activity.slug}/signup/")
    assert response.status_code == 302
    assert not ActivitySignup.objects.filter(activity=full_activity, user=user).exists()


@pytest.mark.django_db
def test_travel_grant_apply_get(client: Client, conference: Conference, user: User):
    client.force_login(user)
    response = client.get(f"/{conference.slug}/programs/travel-grants/apply/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_travel_grant_apply_post(client: Client, conference: Conference, user: User):
    client.force_login(user)
    response = client.post(
        f"/{conference.slug}/programs/travel-grants/apply/",
        {
            "requested_amount": "500.00",
            "travel_from": "Chicago",
            "reason": "Cannot afford travel costs",
        },
    )
    assert response.status_code == 302
    assert TravelGrant.objects.filter(conference=conference, user=user).exists()


@pytest.mark.django_db
def test_travel_grant_apply_invalid_amount(client: Client, conference: Conference, user: User):
    client.force_login(user)
    response = client.post(
        f"/{conference.slug}/programs/travel-grants/apply/",
        {
            "requested_amount": "not-a-number",
            "travel_from": "Chicago",
            "reason": "Need help",
        },
    )
    assert response.status_code == 200
    assert not TravelGrant.objects.filter(conference=conference, user=user).exists()


@pytest.mark.django_db
def test_travel_grant_apply_requires_login(client: Client, conference: Conference):
    response = client.get(f"/{conference.slug}/programs/travel-grants/apply/")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url or "login" in response.url
