"""Tests for programs models."""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.db import IntegrityError

from django_program.conference.models import Conference
from django_program.programs.models import Activity, ActivitySignup, TravelGrant


@pytest.fixture
def conference() -> Conference:
    return Conference.objects.create(
        name="ProgramCon",
        slug="programcon",
        start_date=date(2027, 7, 1),
        end_date=date(2027, 7, 3),
        timezone="UTC",
    )


@pytest.fixture
def user() -> User:
    return User.objects.create_user(username="attendee", password="testpass123")


@pytest.fixture
def activity(conference: Conference) -> Activity:
    return Activity.objects.create(
        conference=conference,
        name="Django Sprint",
        slug="django-sprint",
        activity_type=Activity.ActivityType.SPRINT,
    )


@pytest.mark.django_db
def test_activity_str(activity: Activity):
    assert str(activity) == "Django Sprint"


@pytest.mark.django_db
def test_activity_spots_remaining_unlimited(activity: Activity):
    assert activity.spots_remaining is None


@pytest.mark.django_db
def test_activity_spots_remaining_limited(activity: Activity, user: User):
    activity.max_participants = 10
    activity.save()
    assert activity.spots_remaining == 10
    ActivitySignup.objects.create(activity=activity, user=user)
    assert activity.spots_remaining == 9


@pytest.mark.django_db
def test_activity_spots_remaining_zero(activity: Activity, user: User):
    activity.max_participants = 1
    activity.save()
    ActivitySignup.objects.create(activity=activity, user=user)
    assert activity.spots_remaining == 0


@pytest.mark.django_db
def test_activity_signup_str(activity: Activity, user: User):
    signup = ActivitySignup.objects.create(activity=activity, user=user)
    assert str(signup) == "attendee - Django Sprint"


@pytest.mark.django_db
def test_activity_signup_unique(activity: Activity, user: User):
    ActivitySignup.objects.create(activity=activity, user=user)
    with pytest.raises(IntegrityError):
        ActivitySignup.objects.create(activity=activity, user=user)


@pytest.mark.django_db
def test_travel_grant_str(conference: Conference, user: User):
    grant = TravelGrant.objects.create(
        conference=conference,
        user=user,
        requested_amount=Decimal("500.00"),
        travel_from="Chicago",
        reason="Cannot afford travel",
    )
    assert str(grant) == "Travel grant: attendee (pending)"


@pytest.mark.django_db
def test_travel_grant_unique_per_conference(conference: Conference, user: User):
    TravelGrant.objects.create(
        conference=conference,
        user=user,
        requested_amount=Decimal("500.00"),
        travel_from="Chicago",
        reason="Need help",
    )
    with pytest.raises(IntegrityError):
        TravelGrant.objects.create(
            conference=conference,
            user=user,
            requested_amount=Decimal("300.00"),
            travel_from="Denver",
            reason="Also need help",
        )
