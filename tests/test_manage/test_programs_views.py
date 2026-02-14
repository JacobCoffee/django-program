"""Tests for programs management views in the manage app."""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
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


# ---- Manual room creation (no pretalx_id) ----


@pytest.mark.django_db
def test_manual_room_creation_without_pretalx_id(conference):
    """Rooms can be created without a pretalx_id for non-Pretalx venues."""
    room = Room.objects.create(conference=conference, name="Off-Venue Space")
    assert room.pretalx_id is None
    assert room.pk is not None


@pytest.mark.django_db
def test_multiple_manual_rooms_allowed(conference):
    """Multiple rooms with pretalx_id=None should not violate uniqueness."""
    Room.objects.create(conference=conference, name="Room A")
    Room.objects.create(conference=conference, name="Room B")
    assert Room.objects.filter(conference=conference, pretalx_id=None).count() == 2


@pytest.mark.django_db
def test_activity_create_with_manual_room(authed_client: Client, conference):
    """Activities can be assigned to manually created rooms."""
    room = Room.objects.create(conference=conference, name="Off-Site Venue")
    url = reverse("manage:activity-add", kwargs={"conference_slug": conference.slug})
    response = authed_client.post(
        url,
        {
            "name": "Off-Site Workshop",
            "activity_type": "workshop",
            "room": room.pk,
            "is_active": "on",
        },
    )
    assert response.status_code == 302
    activity = Activity.objects.get(conference=conference, name="Off-Site Workshop")
    assert activity.room == room
    assert activity.room.pretalx_id is None


@pytest.mark.django_db
def test_room_search_includes_manual_rooms(authed_client: Client, conference):
    """Room search API returns both Pretalx-synced and manual rooms."""
    Room.objects.create(conference=conference, pretalx_id=1, name="Main Hall")
    Room.objects.create(conference=conference, name="Garden Tent")
    url = reverse("manage:room-search", kwargs={"conference_slug": conference.slug})
    response = authed_client.get(url)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    names = {r["name"] for r in data}
    assert "Garden Tent" in names


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


# ---- Activity Dashboard views ----


@pytest.mark.django_db
def test_activity_dashboard_get(authed_client: Client, conference, activity, regular_user):
    ActivitySignup.objects.create(activity=activity, user=regular_user, status=ActivitySignup.SignupStatus.CONFIRMED)
    url = reverse("manage:activity-dashboard", kwargs={"conference_slug": conference.slug, "pk": activity.pk})
    response = authed_client.get(url)
    assert response.status_code == 200
    assert response.context["active_nav"] == "activities"
    stats = response.context["signup_stats"]
    assert stats["confirmed"] == 1
    assert stats["total_active"] == 1


@pytest.mark.django_db
def test_activity_dashboard_status_filter(authed_client: Client, conference, activity, regular_user, superuser):
    ActivitySignup.objects.create(activity=activity, user=regular_user, status=ActivitySignup.SignupStatus.CONFIRMED)
    ActivitySignup.objects.create(activity=activity, user=superuser, status=ActivitySignup.SignupStatus.WAITLISTED)
    url = reverse("manage:activity-dashboard", kwargs={"conference_slug": conference.slug, "pk": activity.pk})
    response = authed_client.get(url, {"status": "waitlisted"})
    assert response.status_code == 200
    assert len(response.context["signups"]) == 1
    assert response.context["signups"][0].user == superuser


@pytest.mark.django_db
def test_activity_dashboard_excludes_cancelled_by_default(authed_client: Client, conference, activity, regular_user):
    ActivitySignup.objects.create(activity=activity, user=regular_user, status=ActivitySignup.SignupStatus.CANCELLED)
    url = reverse("manage:activity-dashboard", kwargs={"conference_slug": conference.slug, "pk": activity.pk})
    response = authed_client.get(url)
    assert len(response.context["signups"]) == 0


@pytest.mark.django_db
def test_activity_dashboard_accessible_by_activity_organizer(client: Client, conference, activity):
    organizer = User.objects.create_user(username="organizer", password="password")
    activity.organizers.add(organizer)
    client.force_login(organizer)
    url = reverse("manage:activity-dashboard", kwargs={"conference_slug": conference.slug, "pk": activity.pk})
    response = client.get(url)
    assert response.status_code == 200


@pytest.mark.django_db
def test_activity_dashboard_hides_edit_link_for_activity_organizer(client: Client, conference, activity):
    organizer = User.objects.create_user(username="organizer-no-edit", password="password")
    activity.organizers.add(organizer)
    client.force_login(organizer)
    url = reverse("manage:activity-dashboard", kwargs={"conference_slug": conference.slug, "pk": activity.pk})
    response = client.get(url)
    assert response.status_code == 200
    assert f"/manage/{conference.slug}/activities/{activity.pk}/edit/" not in response.content.decode()


@pytest.mark.django_db
def test_activity_dashboard_denied_for_non_organizer(client: Client, conference, activity):
    nobody = User.objects.create_user(username="nobody", password="password")
    client.force_login(nobody)
    url = reverse("manage:activity-dashboard", kwargs={"conference_slug": conference.slug, "pk": activity.pk})
    response = client.get(url)
    assert response.status_code == 403


# ---- Activity Dashboard CSV Export ----


@pytest.mark.django_db
def test_activity_dashboard_csv_export(authed_client: Client, conference, activity, regular_user):
    ActivitySignup.objects.create(activity=activity, user=regular_user, status=ActivitySignup.SignupStatus.CONFIRMED)
    url = reverse("manage:activity-dashboard-export", kwargs={"conference_slug": conference.slug, "pk": activity.pk})
    response = authed_client.get(url)
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"
    content = response.content.decode()
    assert "Username" in content
    assert regular_user.username in content


@pytest.mark.django_db
def test_activity_dashboard_csv_export_with_status_filter(
    authed_client: Client, conference, activity, regular_user, superuser
):
    ActivitySignup.objects.create(activity=activity, user=regular_user, status=ActivitySignup.SignupStatus.CONFIRMED)
    ActivitySignup.objects.create(activity=activity, user=superuser, status=ActivitySignup.SignupStatus.WAITLISTED)
    url = reverse("manage:activity-dashboard-export", kwargs={"conference_slug": conference.slug, "pk": activity.pk})
    response = authed_client.get(url, {"status": "confirmed"})
    content = response.content.decode()
    assert regular_user.username in content
    assert superuser.username not in content


@pytest.mark.django_db
def test_activity_dashboard_csv_export_escapes_formula_cells(authed_client: Client, conference, activity):
    user = User.objects.create_user(
        username="formula_user",
        password="password",
        first_name="=Malicious Name",
    )
    ActivitySignup.objects.create(
        activity=activity, user=user, status=ActivitySignup.SignupStatus.CONFIRMED, note="+SUM(1,2)"
    )
    url = reverse("manage:activity-dashboard-export", kwargs={"conference_slug": conference.slug, "pk": activity.pk})
    response = authed_client.get(url)
    content = response.content.decode()
    assert "'=Malicious Name" in content
    assert "'+SUM(1,2)" in content


# ---- Activity Promote Signup ----


@pytest.mark.django_db
def test_activity_promote_waitlisted_signup(authed_client: Client, conference, activity, regular_user):
    signup = ActivitySignup.objects.create(
        activity=activity, user=regular_user, status=ActivitySignup.SignupStatus.WAITLISTED
    )
    url = reverse(
        "manage:activity-promote-signup",
        kwargs={"conference_slug": conference.slug, "pk": activity.pk, "signup_pk": signup.pk},
    )
    response = authed_client.post(url)
    assert response.status_code == 302
    signup.refresh_from_db()
    assert signup.status == "confirmed"


@pytest.mark.django_db
def test_activity_promote_waitlisted_signup_warns_on_overbook(authed_client: Client, conference, regular_user):
    activity = Activity.objects.create(
        conference=conference,
        name="Limited Session",
        slug="limited-session",
        activity_type=Activity.ActivityType.SPRINT,
        max_participants=1,
        is_active=True,
    )
    holder = User.objects.create_user(username="holder", password="password")
    ActivitySignup.objects.create(activity=activity, user=holder, status=ActivitySignup.SignupStatus.CONFIRMED)
    signup = ActivitySignup.objects.create(
        activity=activity, user=regular_user, status=ActivitySignup.SignupStatus.WAITLISTED
    )
    url = reverse(
        "manage:activity-promote-signup",
        kwargs={"conference_slug": conference.slug, "pk": activity.pk, "signup_pk": signup.pk},
    )
    response = authed_client.post(url, follow=True)
    assert response.status_code == 200

    signup.refresh_from_db()
    assert signup.status == "confirmed"

    msgs = [str(message) for message in get_messages(response.wsgi_request)]
    assert any("may now be overbooked" in message for message in msgs)


@pytest.mark.django_db
def test_activity_promote_non_waitlisted_404(authed_client: Client, conference, activity, regular_user):
    signup = ActivitySignup.objects.create(
        activity=activity, user=regular_user, status=ActivitySignup.SignupStatus.CONFIRMED
    )
    url = reverse(
        "manage:activity-promote-signup",
        kwargs={"conference_slug": conference.slug, "pk": activity.pk, "signup_pk": signup.pk},
    )
    response = authed_client.post(url)
    assert response.status_code == 404


@pytest.mark.django_db
def test_activity_dashboard_redirects_unauthenticated_user(client: Client, conference, activity):
    url = reverse("manage:activity-dashboard", kwargs={"conference_slug": conference.slug, "pk": activity.pk})
    response = client.get(url)
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


# ---- Activity organizers M2M ----


@pytest.mark.django_db
def test_activity_organizers_m2m(activity, regular_user):
    activity.organizers.add(regular_user)
    assert regular_user in activity.organizers.all()
    assert activity in regular_user.organized_activities.all()
