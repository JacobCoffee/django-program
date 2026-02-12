"""Tests for programs management views in the manage app."""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from django_program.conference.models import Conference
from django_program.pretalx.models import Room
from django_program.programs.models import Activity, ActivitySignup, PaymentInfo, Receipt, TravelGrant


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
            "activity_type": "workshop",
            "is_active": "on",
        },
    )
    assert response.status_code == 302
    activity = Activity.objects.get(conference=conference, name="Workshop Day")
    assert activity.slug == "workshop-day"


@pytest.mark.django_db
def test_activity_create_auto_slug_uniqueness(authed_client: Client, conference):
    Activity.objects.create(conference=conference, name="Existing", slug="workshop-day", activity_type="other")
    url = reverse("manage:activity-add", kwargs={"conference_slug": conference.slug})
    response = authed_client.post(
        url,
        {
            "name": "Workshop Day",
            "activity_type": "workshop",
            "is_active": "on",
        },
    )
    assert response.status_code == 302
    activity = Activity.objects.get(conference=conference, name="Workshop Day")
    assert activity.slug == "workshop-day-2"


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
            "activity_type": "sprint",
            "is_active": "on",
        },
    )
    assert response.status_code == 302
    activity.refresh_from_db()
    assert activity.name == "Updated Sprint"
    assert activity.slug == "updated-sprint"


# ---- Travel Grant views ----


@pytest.mark.django_db
def test_travel_grant_manage_list(authed_client: Client, conference, grant):
    url = reverse("manage:travel-grant-list", kwargs={"conference_slug": conference.slug})
    response = authed_client.get(url)
    assert response.status_code == 200
    assert grant in response.context["grants"]
    assert response.context["active_nav"] == "travel-grants"


@pytest.mark.django_db
def test_travel_grant_manage_list_grant_stats(authed_client: Client, conference, regular_user, superuser):
    TravelGrant.objects.create(
        conference=conference,
        user=regular_user,
        requested_amount=Decimal("500.00"),
        travel_from="Chicago",
        reason="Need help",
        status="submitted",
    )
    user2 = User.objects.create_user(username="other", password="password")
    TravelGrant.objects.create(
        conference=conference,
        user=user2,
        requested_amount=Decimal("300.00"),
        travel_from="NYC",
        reason="Also need help",
        status="accepted",
        approved_amount=Decimal("250.00"),
        reviewed_by=superuser,
    )
    url = reverse("manage:travel-grant-list", kwargs={"conference_slug": conference.slug})
    response = authed_client.get(url)
    stats = response.context["grant_stats"]
    assert stats["total"] == 2
    assert stats["pending"] == 1
    assert stats["approved"] == 1
    assert stats["rejected"] == 0
    assert stats["total_requested"] == Decimal("800.00")
    assert stats["total_approved"] == Decimal("250.00")


@pytest.mark.django_db
def test_travel_grant_manage_list_current_status(authed_client: Client, conference, grant):
    url = reverse("manage:travel-grant-list", kwargs={"conference_slug": conference.slug})
    response = authed_client.get(url, {"status": "submitted"})
    assert response.context["current_status"] == "submitted"

    response = authed_client.get(url)
    assert response.context["current_status"] == ""


@pytest.mark.django_db
def test_travel_grant_manage_list_status_filter(authed_client: Client, conference, grant):
    url = reverse("manage:travel-grant-list", kwargs={"conference_slug": conference.slug})
    response = authed_client.get(url, {"status": "submitted"})
    assert response.status_code == 200
    assert grant in response.context["grants"]

    response = authed_client.get(url, {"status": "accepted"})
    assert list(response.context["grants"]) == []


@pytest.mark.django_db
def test_travel_grant_review_get(authed_client: Client, conference, grant):
    url = reverse("manage:travel-grant-review", kwargs={"conference_slug": conference.slug, "pk": grant.pk})
    response = authed_client.get(url)
    assert response.status_code == 200
    assert response.context["grant"] == grant
    assert response.context["active_nav"] == "travel-grants"
    assert response.context["has_previous_review"] is False


@pytest.mark.django_db
def test_travel_grant_review_has_previous_review(authed_client: Client, conference, grant, superuser):
    grant.reviewed_by = superuser
    grant.reviewed_at = timezone.now()
    grant.status = "accepted"
    grant.approved_amount = Decimal("400.00")
    grant.save()
    url = reverse("manage:travel-grant-review", kwargs={"conference_slug": conference.slug, "pk": grant.pk})
    response = authed_client.get(url)
    assert response.context["has_previous_review"] is True


@pytest.mark.django_db
def test_travel_grant_review_post(authed_client: Client, conference, grant, superuser):
    url = reverse("manage:travel-grant-review", kwargs={"conference_slug": conference.slug, "pk": grant.pk})
    response = authed_client.post(
        url,
        {
            "status": "accepted",
            "approved_amount": "400.00",
            "reviewer_notes": "Approved for reduced amount.",
        },
    )
    assert response.status_code == 302
    grant.refresh_from_db()
    assert grant.status == "accepted"
    assert grant.approved_amount == Decimal("400.00")
    assert grant.reviewed_by == superuser
    assert grant.reviewed_at is not None


# ---- Room search API ----


@pytest.mark.django_db
def test_room_search_api(authed_client: Client, conference):
    Room.objects.create(conference=conference, pretalx_id=1, name="Main Hall")
    Room.objects.create(conference=conference, pretalx_id=2, name="Workshop Room")
    url = reverse("manage:room-search", kwargs={"conference_slug": conference.slug})
    response = authed_client.get(url, {"q": "main"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Main Hall"


@pytest.mark.django_db
def test_room_search_api_empty_query(authed_client: Client, conference):
    Room.objects.create(conference=conference, pretalx_id=1, name="Room A")
    Room.objects.create(conference=conference, pretalx_id=2, name="Room B")
    url = reverse("manage:room-search", kwargs={"conference_slug": conference.slug})
    response = authed_client.get(url)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


# ---- Activity with room ----


@pytest.mark.django_db
def test_activity_create_with_room(authed_client: Client, conference):
    room = Room.objects.create(conference=conference, pretalx_id=1, name="Hall A")
    url = reverse("manage:activity-add", kwargs={"conference_slug": conference.slug})
    response = authed_client.post(
        url,
        {
            "name": "Room Activity",
            "activity_type": "workshop",
            "room": room.pk,
            "is_active": "on",
        },
    )
    assert response.status_code == 302
    activity = Activity.objects.get(conference=conference, name="Room Activity")
    assert activity.room == room
    assert activity.slug == "room-activity"


# ---- Receipt review views ----


@pytest.fixture
def accepted_grant(conference, regular_user):
    return TravelGrant.objects.create(
        conference=conference,
        user=regular_user,
        status=TravelGrant.GrantStatus.ACCEPTED,
        requested_amount=Decimal("500.00"),
        approved_amount=Decimal("400.00"),
        travel_from="Chicago",
        reason="Need help",
    )


@pytest.fixture
def pending_receipt(accepted_grant):
    return Receipt.objects.create(
        grant=accepted_grant,
        receipt_type=Receipt.ReceiptType.AIRFARE,
        amount=Decimal("250.00"),
        date=date(2027, 6, 15),
        receipt_file="test.pdf",
    )


@pytest.mark.django_db
def test_receipt_review_queue_redirects_to_receipt(authed_client: Client, conference, pending_receipt):
    url = reverse("manage:receipt-review-queue", kwargs={"conference_slug": conference.slug})
    response = authed_client.get(url)
    assert response.status_code == 302
    assert str(pending_receipt.pk) in response.url


@pytest.mark.django_db
def test_receipt_review_queue_no_pending(authed_client: Client, conference, accepted_grant):
    url = reverse("manage:receipt-review-queue", kwargs={"conference_slug": conference.slug})
    response = authed_client.get(url)
    assert response.status_code == 302
    assert "travel-grants" in response.url


@pytest.mark.django_db
def test_receipt_review_detail(authed_client: Client, conference, pending_receipt):
    url = reverse("manage:receipt-review-detail", kwargs={"conference_slug": conference.slug, "pk": pending_receipt.pk})
    response = authed_client.get(url)
    assert response.status_code == 200
    assert response.context["receipt"] == pending_receipt


@pytest.mark.django_db
def test_receipt_approve(authed_client: Client, conference, pending_receipt):
    url = reverse("manage:receipt-approve", kwargs={"conference_slug": conference.slug, "pk": pending_receipt.pk})
    response = authed_client.post(url)
    assert response.status_code == 302
    pending_receipt.refresh_from_db()
    assert pending_receipt.approved is True
    assert pending_receipt.approved_by is not None


@pytest.mark.django_db
def test_receipt_flag(authed_client: Client, conference, pending_receipt):
    url = reverse("manage:receipt-flag", kwargs={"conference_slug": conference.slug, "pk": pending_receipt.pk})
    response = authed_client.post(url, {"reason": "Blurry image"})
    assert response.status_code == 302
    pending_receipt.refresh_from_db()
    assert pending_receipt.flagged is True
    assert pending_receipt.flagged_reason == "Blurry image"


@pytest.mark.django_db
def test_travel_grant_review_cache_control(authed_client: Client, conference, grant):
    url = reverse("manage:travel-grant-review", kwargs={"conference_slug": conference.slug, "pk": grant.pk})
    response = authed_client.get(url)
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"


# ---- Disbursement views ----


@pytest.fixture
def disbursable_grant(conference, regular_user):
    """Accepted grant with payment info and an approved receipt -- ready for disbursement."""
    grant = TravelGrant.objects.create(
        conference=conference,
        user=regular_user,
        status=TravelGrant.GrantStatus.ACCEPTED,
        requested_amount=Decimal("500.00"),
        approved_amount=Decimal("400.00"),
        travel_from="Chicago",
        reason="Need help",
    )
    PaymentInfo.objects.create(
        grant=grant,
        payment_method="zelle",
        legal_name="Test User",
        address_street="123 Main St",
        address_city="Pittsburgh",
        address_zip="15213",
        address_country="US",
    )
    Receipt.objects.create(
        grant=grant,
        receipt_type="airfare",
        amount=Decimal("500.00"),
        date=date.today(),
        receipt_file=SimpleUploadedFile("test.pdf", b"fake", content_type="application/pdf"),
        approved=True,
    )
    return grant


@pytest.mark.django_db
def test_disburse_accepted_grant(authed_client: Client, conference, disbursable_grant, superuser):
    """POST to disburse sets status, amount, timestamp, and user."""
    url = reverse(
        "manage:travel-grant-disburse",
        kwargs={"conference_slug": conference.slug, "pk": disbursable_grant.pk},
    )
    response = authed_client.post(url, {"disbursed_amount": "400.00"})
    assert response.status_code == 302
    disbursable_grant.refresh_from_db()
    assert disbursable_grant.status == TravelGrant.GrantStatus.DISBURSED
    assert disbursable_grant.disbursed_amount == Decimal("400.00")
    assert disbursable_grant.disbursed_at is not None
    assert disbursable_grant.disbursed_by == superuser


@pytest.mark.django_db
def test_disburse_non_accepted_grant_rejected(authed_client: Client, conference, grant):
    """POST to disburse a non-accepted grant should not change its status."""
    url = reverse(
        "manage:travel-grant-disburse",
        kwargs={"conference_slug": conference.slug, "pk": grant.pk},
    )
    response = authed_client.post(url, {"disbursed_amount": "400.00"})
    assert response.status_code == 302
    grant.refresh_from_db()
    assert grant.status == TravelGrant.GrantStatus.SUBMITTED


@pytest.mark.django_db
def test_disburse_requires_manage_access(client: Client, conference, disbursable_grant):
    """Anonymous user should be redirected to login."""
    url = reverse(
        "manage:travel-grant-disburse",
        kwargs={"conference_slug": conference.slug, "pk": disbursable_grant.pk},
    )
    response = client.post(url, {"disbursed_amount": "400.00"})
    assert response.status_code == 302
    assert "/accounts/login/" in response.url or "login" in response.url


@pytest.mark.django_db
def test_disbursed_grant_shows_info_on_review(authed_client: Client, conference, disbursable_grant, superuser):
    """After disbursement the review page includes disbursement details."""
    disbursable_grant.status = TravelGrant.GrantStatus.DISBURSED
    disbursable_grant.disbursed_amount = Decimal("400.00")
    disbursable_grant.disbursed_at = timezone.now()
    disbursable_grant.disbursed_by = superuser
    disbursable_grant.save()

    url = reverse(
        "manage:travel-grant-review",
        kwargs={"conference_slug": conference.slug, "pk": disbursable_grant.pk},
    )
    response = authed_client.get(url)
    assert response.status_code == 200
    grant_ctx = response.context["grant"]
    assert grant_ctx.status == TravelGrant.GrantStatus.DISBURSED
    assert grant_ctx.disbursed_amount == Decimal("400.00")
    assert grant_ctx.disbursed_by == superuser
