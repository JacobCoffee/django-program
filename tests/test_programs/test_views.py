"""Tests for programs views."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from django_program.conference.models import Conference
from django_program.pretalx.models import Room, Speaker, Talk
from django_program.programs.models import (
    Activity,
    ActivitySignup,
    PaymentInfo,
    Receipt,
    TravelGrant,
    TravelGrantMessage,
)


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
    assert "form" in response.context


@pytest.mark.django_db
def test_travel_grant_apply_post(client: Client, conference: Conference, user: User):
    client.force_login(user)
    response = client.post(
        f"/{conference.slug}/programs/travel-grants/apply/",
        {
            "request_type": "ticket_and_grant",
            "application_type": "general",
            "requested_amount": "500.00",
            "travel_from": "Chicago",
            "reason": "Cannot afford travel costs",
            "experience_level": "intermediate",
            "occupation": "Software developer",
            "involvement": "Active in local meetups",
            "i_have_read": "on",
            "first_time": "True",
        },
    )
    assert response.status_code == 302
    grant = TravelGrant.objects.get(conference=conference, user=user)
    assert grant.requested_amount == Decimal("500.00")


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
def test_travel_grant_apply_negative_amount(client: Client, conference: Conference, user: User):
    """Negative requested amounts are rejected by form validation."""
    client.force_login(user)
    response = client.post(
        f"/{conference.slug}/programs/travel-grants/apply/",
        {
            "requested_amount": "-100.00",
            "travel_from": "Denver",
            "reason": "Need help",
        },
    )
    assert response.status_code == 200
    assert not TravelGrant.objects.filter(conference=conference, user=user).exists()


@pytest.mark.django_db
def test_travel_grant_apply_empty_required_fields(client: Client, conference: Conference, user: User):
    """Empty travel_from and reason are rejected by form validation."""
    client.force_login(user)
    response = client.post(
        f"/{conference.slug}/programs/travel-grants/apply/",
        {
            "requested_amount": "500.00",
            "travel_from": "",
            "reason": "",
        },
    )
    assert response.status_code == 200
    assert not TravelGrant.objects.filter(conference=conference, user=user).exists()


@pytest.mark.django_db
def test_travel_grant_apply_duplicate(client: Client, conference: Conference, user: User):
    """A user who already has a grant for this conference gets an error."""
    TravelGrant.objects.create(
        conference=conference,
        user=user,
        requested_amount=Decimal("500.00"),
        travel_from="Chicago",
        reason="First application",
    )
    client.force_login(user)
    response = client.post(
        f"/{conference.slug}/programs/travel-grants/apply/",
        {
            "request_type": "ticket_and_grant",
            "application_type": "general",
            "requested_amount": "300.00",
            "travel_from": "Denver",
            "reason": "Second attempt",
            "experience_level": "beginner",
            "occupation": "Student",
            "involvement": "Open source contributor",
            "i_have_read": "on",
            "first_time": "True",
        },
    )
    assert response.status_code == 302
    assert TravelGrant.objects.filter(conference=conference, user=user).count() == 1


@pytest.mark.django_db
def test_travel_grant_apply_requires_login(client: Client, conference: Conference):
    response = client.get(f"/{conference.slug}/programs/travel-grants/apply/")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url or "login" in response.url


# ---- Travel Grant Status View ----


@pytest.mark.django_db
def test_travel_grant_status_no_grant(client: Client, conference: Conference, user: User):
    client.force_login(user)
    response = client.get(f"/{conference.slug}/programs/travel-grants/status/")
    assert response.status_code == 200
    assert response.context["grant"] is None


@pytest.mark.django_db
def test_travel_grant_status_with_grant(client: Client, conference: Conference, user: User):
    grant = TravelGrant.objects.create(
        conference=conference,
        user=user,
        requested_amount=Decimal("500.00"),
        travel_from="Chicago",
        reason="Cannot afford travel",
    )
    client.force_login(user)
    response = client.get(f"/{conference.slug}/programs/travel-grants/status/")
    assert response.status_code == 200
    assert response.context["grant"] == grant


@pytest.mark.django_db
def test_travel_grant_status_requires_login(client: Client, conference: Conference):
    response = client.get(f"/{conference.slug}/programs/travel-grants/status/")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url or "login" in response.url


@pytest.mark.django_db
def test_travel_grant_apply_redirects_to_status(client: Client, conference: Conference, user: User):
    client.force_login(user)
    response = client.post(
        f"/{conference.slug}/programs/travel-grants/apply/",
        {
            "request_type": "ticket_and_grant",
            "application_type": "general",
            "requested_amount": "500.00",
            "travel_from": "Chicago",
            "reason": "Need travel help",
            "experience_level": "intermediate",
            "occupation": "Software developer",
            "involvement": "Active in community",
            "i_have_read": "on",
            "first_time": "False",
        },
    )
    assert response.status_code == 302
    assert f"/{conference.slug}/programs/travel-grants/status/" in response.url


# ---- Activity List Type Filter ----


@pytest.mark.django_db
def test_activity_list_type_filter(client: Client, conference: Conference):
    Activity.objects.create(
        conference=conference,
        name="Sprint",
        slug="sprint",
        activity_type=Activity.ActivityType.SPRINT,
        is_active=True,
    )
    Activity.objects.create(
        conference=conference,
        name="Workshop",
        slug="workshop",
        activity_type=Activity.ActivityType.WORKSHOP,
        is_active=True,
    )
    response = client.get(f"/{conference.slug}/programs/?type=sprint")
    assert response.status_code == 200
    activities = list(response.context["activities"])
    assert len(activities) == 1
    assert activities[0].activity_type == Activity.ActivityType.SPRINT


@pytest.mark.django_db
def test_activity_list_type_filter_all(client: Client, conference: Conference):
    Activity.objects.create(
        conference=conference,
        name="Sprint",
        slug="sprint",
        activity_type=Activity.ActivityType.SPRINT,
        is_active=True,
    )
    Activity.objects.create(
        conference=conference,
        name="Workshop",
        slug="workshop",
        activity_type=Activity.ActivityType.WORKSHOP,
        is_active=True,
    )
    response = client.get(f"/{conference.slug}/programs/")
    assert response.status_code == 200
    assert len(list(response.context["activities"])) == 2


@pytest.mark.django_db
def test_activity_list_has_type_choices(client: Client, conference: Conference, activity: Activity):
    response = client.get(f"/{conference.slug}/programs/")
    assert "activity_types" in response.context
    assert "current_type" in response.context


@pytest.mark.django_db
def test_activity_list_has_talk_count(client: Client, conference: Conference):
    act = Activity.objects.create(
        conference=conference,
        name="Tutorials",
        slug="tutorials",
        activity_type=Activity.ActivityType.TUTORIAL,
        is_active=True,
    )
    talk = Talk.objects.create(
        conference=conference,
        pretalx_code="T1",
        title="Django Intro",
        submission_type="Tutorial",
    )
    act.talks.add(talk)
    response = client.get(f"/{conference.slug}/programs/")
    activities = list(response.context["activities"])
    assert activities[0].talk_count == 1


# ---- Activity Detail with Linked Talks ----


@pytest.mark.django_db
def test_activity_detail_linked_talks(client: Client, conference: Conference):
    room = Room.objects.create(conference=conference, pretalx_id=1, name="Hall A")
    act = Activity.objects.create(
        conference=conference,
        name="Tutorials",
        slug="tutorials",
        activity_type=Activity.ActivityType.TUTORIAL,
        is_active=True,
    )
    speaker = Speaker.objects.create(conference=conference, pretalx_code="SPK1", name="Alice")
    talk = Talk.objects.create(
        conference=conference,
        pretalx_code="T1",
        title="Django Intro",
        submission_type="Tutorial",
        room=room,
        slot_start=datetime(2027, 8, 1, 10, 0, tzinfo=UTC),
        slot_end=datetime(2027, 8, 1, 11, 0, tzinfo=UTC),
    )
    talk.speakers.add(speaker)
    act.talks.add(talk)

    response = client.get(f"/{conference.slug}/programs/tutorials/")
    assert response.status_code == 200
    assert list(response.context["linked_talks"]) == [talk]
    assert speaker in response.context["speakers"]
    assert len(response.context["schedule_by_day"]) == 1


@pytest.mark.django_db
def test_activity_detail_no_talks(client: Client, conference: Conference, activity: Activity):
    response = client.get(f"/{conference.slug}/programs/{activity.slug}/")
    assert response.status_code == 200
    assert list(response.context["linked_talks"]) == []
    assert response.context["speakers"] == []
    assert response.context["schedule_by_day"] == []


# ---- Navigation Links ----


@pytest.mark.django_db
def test_nav_links_present(client: Client, conference: Conference, activity: Activity):
    response = client.get(f"/{conference.slug}/programs/")
    content = response.content.decode()
    assert "Programs" in content
    assert "Travel Grants" in content


# ---- Travel Grant Accept/Decline/Withdraw/Edit/Message ----


@pytest.fixture
def offered_grant(conference: Conference, user: User) -> TravelGrant:
    return TravelGrant.objects.create(
        conference=conference,
        user=user,
        status=TravelGrant.GrantStatus.OFFERED,
        requested_amount=Decimal("500.00"),
        approved_amount=Decimal("400.00"),
        travel_from="Chicago",
        reason="Need help",
    )


@pytest.fixture
def submitted_grant(conference: Conference, user: User) -> TravelGrant:
    return TravelGrant.objects.create(
        conference=conference,
        user=user,
        status=TravelGrant.GrantStatus.SUBMITTED,
        requested_amount=Decimal("500.00"),
        travel_from="Chicago",
        reason="Need help",
    )


@pytest.mark.django_db
def test_accept_offered_grant(client: Client, conference: Conference, user: User, offered_grant: TravelGrant):
    client.force_login(user)
    response = client.post(f"/{conference.slug}/programs/travel-grants/accept/")
    assert response.status_code == 302
    offered_grant.refresh_from_db()
    assert offered_grant.status == TravelGrant.GrantStatus.ACCEPTED


@pytest.mark.django_db
def test_accept_creates_message(client: Client, conference: Conference, user: User, offered_grant: TravelGrant):
    client.force_login(user)
    client.post(f"/{conference.slug}/programs/travel-grants/accept/")
    assert TravelGrantMessage.objects.filter(grant=offered_grant, visible=True).exists()


@pytest.mark.django_db
def test_accept_wrong_status(client: Client, conference: Conference, user: User, submitted_grant: TravelGrant):
    client.force_login(user)
    response = client.post(f"/{conference.slug}/programs/travel-grants/accept/")
    assert response.status_code == 302
    submitted_grant.refresh_from_db()
    assert submitted_grant.status == TravelGrant.GrantStatus.SUBMITTED


@pytest.mark.django_db
def test_accept_requires_login(client: Client, conference: Conference):
    response = client.post(f"/{conference.slug}/programs/travel-grants/accept/")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url or "login" in response.url


@pytest.mark.django_db
def test_decline_offered_grant(client: Client, conference: Conference, user: User, offered_grant: TravelGrant):
    client.force_login(user)
    response = client.post(f"/{conference.slug}/programs/travel-grants/decline/")
    assert response.status_code == 302
    offered_grant.refresh_from_db()
    assert offered_grant.status == TravelGrant.GrantStatus.DECLINED


@pytest.mark.django_db
def test_decline_wrong_status(client: Client, conference: Conference, user: User, submitted_grant: TravelGrant):
    client.force_login(user)
    response = client.post(f"/{conference.slug}/programs/travel-grants/decline/")
    assert response.status_code == 302
    submitted_grant.refresh_from_db()
    assert submitted_grant.status == TravelGrant.GrantStatus.SUBMITTED


@pytest.mark.django_db
def test_withdraw_submitted_grant(client: Client, conference: Conference, user: User, submitted_grant: TravelGrant):
    client.force_login(user)
    response = client.post(f"/{conference.slug}/programs/travel-grants/withdraw/")
    assert response.status_code == 302
    submitted_grant.refresh_from_db()
    assert submitted_grant.status == TravelGrant.GrantStatus.WITHDRAWN


@pytest.mark.django_db
def test_withdraw_wrong_status(client: Client, conference: Conference, user: User, offered_grant: TravelGrant):
    client.force_login(user)
    response = client.post(f"/{conference.slug}/programs/travel-grants/withdraw/")
    assert response.status_code == 302
    offered_grant.refresh_from_db()
    assert offered_grant.status == TravelGrant.GrantStatus.OFFERED


@pytest.mark.django_db
def test_edit_get(client: Client, conference: Conference, user: User, submitted_grant: TravelGrant):
    client.force_login(user)
    response = client.get(f"/{conference.slug}/programs/travel-grants/edit/")
    assert response.status_code == 200
    assert "form" in response.context
    assert response.context.get("is_edit") is True


@pytest.mark.django_db
def test_edit_post(client: Client, conference: Conference, user: User, submitted_grant: TravelGrant):
    client.force_login(user)
    response = client.post(
        f"/{conference.slug}/programs/travel-grants/edit/",
        {
            "request_type": "ticket_and_grant",
            "application_type": "general",
            "requested_amount": "600.00",
            "travel_from": "Denver",
            "reason": "Updated reason",
            "experience_level": "intermediate",
            "occupation": "Developer",
            "involvement": "Community work",
            "i_have_read": "on",
            "first_time": "True",
        },
    )
    assert response.status_code == 302
    submitted_grant.refresh_from_db()
    assert submitted_grant.travel_from == "Denver"
    assert submitted_grant.requested_amount == Decimal("600.00")


@pytest.mark.django_db
def test_edit_wrong_status(client: Client, conference: Conference, user: User, offered_grant: TravelGrant):
    client.force_login(user)
    response = client.get(f"/{conference.slug}/programs/travel-grants/edit/")
    assert response.status_code == 302


@pytest.mark.django_db
def test_edit_no_grant_404(client: Client, conference: Conference, user: User):
    client.force_login(user)
    response = client.get(f"/{conference.slug}/programs/travel-grants/edit/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_provide_info_get(client: Client, conference: Conference, user: User):
    grant = TravelGrant.objects.create(
        conference=conference,
        user=user,
        status=TravelGrant.GrantStatus.INFO_NEEDED,
        requested_amount=Decimal("500.00"),
        travel_from="Chicago",
        reason="Need help",
    )
    client.force_login(user)
    response = client.get(f"/{conference.slug}/programs/travel-grants/provide-info/")
    assert response.status_code == 200
    assert "form" in response.context


@pytest.mark.django_db
def test_provide_info_post(client: Client, conference: Conference, user: User):
    grant = TravelGrant.objects.create(
        conference=conference,
        user=user,
        status=TravelGrant.GrantStatus.INFO_NEEDED,
        requested_amount=Decimal("500.00"),
        travel_from="Chicago",
        reason="Need help",
    )
    client.force_login(user)
    response = client.post(
        f"/{conference.slug}/programs/travel-grants/provide-info/",
        {"message": "Here is the additional info you requested."},
    )
    assert response.status_code == 302
    grant.refresh_from_db()
    assert grant.status == TravelGrant.GrantStatus.SUBMITTED
    assert TravelGrantMessage.objects.filter(grant=grant).count() == 1


@pytest.mark.django_db
def test_provide_info_wrong_status(client: Client, conference: Conference, user: User, submitted_grant: TravelGrant):
    client.force_login(user)
    response = client.get(f"/{conference.slug}/programs/travel-grants/provide-info/")
    assert response.status_code == 302


@pytest.mark.django_db
def test_send_message(client: Client, conference: Conference, user: User, submitted_grant: TravelGrant):
    client.force_login(user)
    response = client.post(
        f"/{conference.slug}/programs/travel-grants/message/",
        {"message": "Hello, any updates?"},
    )
    assert response.status_code == 302
    msg = TravelGrantMessage.objects.get(grant=submitted_grant)
    assert msg.message == "Hello, any updates?"
    assert msg.visible is True
    assert msg.user == user


@pytest.mark.django_db
def test_send_message_no_grant_404(client: Client, conference: Conference, user: User):
    client.force_login(user)
    response = client.post(
        f"/{conference.slug}/programs/travel-grants/message/",
        {"message": "Hello"},
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_status_page_shows_messages(client: Client, conference: Conference, user: User, submitted_grant: TravelGrant):
    TravelGrantMessage.objects.create(grant=submitted_grant, user=user, visible=True, message="Test message")
    client.force_login(user)
    response = client.get(f"/{conference.slug}/programs/travel-grants/status/")
    assert response.status_code == 200
    assert len(response.context["grant_messages"]) == 1
    assert response.context["message_form"] is not None


@pytest.mark.django_db
def test_status_page_hides_private_messages(
    client: Client, conference: Conference, user: User, submitted_grant: TravelGrant
):
    TravelGrantMessage.objects.create(grant=submitted_grant, user=user, visible=False, message="Private note")
    client.force_login(user)
    response = client.get(f"/{conference.slug}/programs/travel-grants/status/")
    assert len(response.context["grant_messages"]) == 0


# ---- Receipt Upload/Delete Views ----


@pytest.fixture
def accepted_grant(conference: Conference, user: User) -> TravelGrant:
    return TravelGrant.objects.create(
        conference=conference,
        user=user,
        status=TravelGrant.GrantStatus.ACCEPTED,
        requested_amount=Decimal("500.00"),
        approved_amount=Decimal("400.00"),
        travel_from="Chicago",
        reason="Need help",
    )


@pytest.mark.django_db
def test_receipt_upload_get(client: Client, conference: Conference, user: User, accepted_grant: TravelGrant):
    client.force_login(user)
    response = client.get(f"/{conference.slug}/programs/travel-grants/receipts/")
    assert response.status_code == 200
    assert "form" in response.context


@pytest.mark.django_db
def test_receipt_upload_wrong_status(client: Client, conference: Conference, user: User, submitted_grant: TravelGrant):
    client.force_login(user)
    response = client.get(f"/{conference.slug}/programs/travel-grants/receipts/")
    assert response.status_code == 302


@pytest.mark.django_db
def test_receipt_upload_no_grant_404(client: Client, conference: Conference, user: User):
    client.force_login(user)
    response = client.get(f"/{conference.slug}/programs/travel-grants/receipts/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_receipt_delete(client: Client, conference: Conference, user: User, accepted_grant: TravelGrant):
    receipt = Receipt.objects.create(
        grant=accepted_grant,
        receipt_type=Receipt.ReceiptType.AIRFARE,
        amount=Decimal("250.00"),
        date=date(2027, 6, 15),
        receipt_file="test.pdf",
    )
    client.force_login(user)
    response = client.post(f"/{conference.slug}/programs/travel-grants/receipts/{receipt.pk}/delete/")
    assert response.status_code == 302
    assert not Receipt.objects.filter(pk=receipt.pk).exists()


@pytest.mark.django_db
def test_receipt_delete_approved_blocked(
    client: Client, conference: Conference, user: User, accepted_grant: TravelGrant
):
    receipt = Receipt.objects.create(
        grant=accepted_grant,
        receipt_type=Receipt.ReceiptType.AIRFARE,
        amount=Decimal("250.00"),
        date=date(2027, 6, 15),
        receipt_file="test.pdf",
        approved=True,
    )
    client.force_login(user)
    response = client.post(f"/{conference.slug}/programs/travel-grants/receipts/{receipt.pk}/delete/")
    assert response.status_code == 302
    assert Receipt.objects.filter(pk=receipt.pk).exists()


# ---- Payment Info Views ----


@pytest.mark.django_db
def test_payment_info_get(client: Client, conference: Conference, user: User, accepted_grant: TravelGrant):
    client.force_login(user)
    response = client.get(f"/{conference.slug}/programs/travel-grants/payment-info/")
    assert response.status_code == 200
    assert "form" in response.context


@pytest.mark.django_db
def test_payment_info_post(client: Client, conference: Conference, user: User, accepted_grant: TravelGrant):
    client.force_login(user)
    response = client.post(
        f"/{conference.slug}/programs/travel-grants/payment-info/",
        {
            "payment_method": "paypal",
            "legal_name": "Jane Doe",
            "address_street": "123 Main St",
            "address_city": "Chicago",
            "address_state": "IL",
            "address_zip": "60601",
            "address_country": "US",
            "paypal_email": "jane@example.com",
        },
    )
    assert response.status_code == 302
    info = PaymentInfo.objects.get(grant=accepted_grant)
    assert info.payment_method == "paypal"
    assert info.legal_name == "Jane Doe"


@pytest.mark.django_db
def test_payment_info_update(client: Client, conference: Conference, user: User, accepted_grant: TravelGrant):
    PaymentInfo.objects.create(
        grant=accepted_grant,
        payment_method=PaymentInfo.PaymentMethod.PAYPAL,
        legal_name="Jane Doe",
        address_street="123 Main St",
        address_city="Chicago",
        address_zip="60601",
        address_country="US",
        paypal_email="old@example.com",
    )
    client.force_login(user)
    response = client.post(
        f"/{conference.slug}/programs/travel-grants/payment-info/",
        {
            "payment_method": "paypal",
            "legal_name": "Jane Doe Updated",
            "address_street": "456 Oak Ave",
            "address_city": "Chicago",
            "address_state": "IL",
            "address_zip": "60601",
            "address_country": "US",
            "paypal_email": "new@example.com",
        },
    )
    assert response.status_code == 302
    info = PaymentInfo.objects.get(grant=accepted_grant)
    assert info.legal_name == "Jane Doe Updated"


@pytest.mark.django_db
def test_payment_info_wrong_status(client: Client, conference: Conference, user: User, submitted_grant: TravelGrant):
    client.force_login(user)
    response = client.get(f"/{conference.slug}/programs/travel-grants/payment-info/")
    assert response.status_code == 302


# ---- TravelGrantEditView POST coverage ----


@pytest.mark.django_db
def test_edit_post_wrong_status_redirects(
    client: Client, conference: Conference, user: User, offered_grant: TravelGrant
):
    """Lines 354-355: POST to edit when grant is not editable redirects with error."""
    client.force_login(user)
    response = client.post(
        f"/{conference.slug}/programs/travel-grants/edit/",
        {
            "request_type": "ticket_and_grant",
            "application_type": "general",
            "requested_amount": "600.00",
            "travel_from": "Denver",
            "reason": "Updated reason",
            "experience_level": "intermediate",
            "occupation": "Developer",
            "involvement": "Community work",
            "first_time": "True",
        },
    )
    assert response.status_code == 302
    offered_grant.refresh_from_db()
    assert offered_grant.status == TravelGrant.GrantStatus.OFFERED


@pytest.mark.django_db
def test_edit_post_invalid_form_rerenders(
    client: Client, conference: Conference, user: User, submitted_grant: TravelGrant
):
    """Line 358: POST to edit with invalid form data re-renders form with errors."""
    client.force_login(user)
    response = client.post(
        f"/{conference.slug}/programs/travel-grants/edit/",
        {
            "request_type": "ticket_and_grant",
            "application_type": "general",
            "requested_amount": "",
            "travel_from": "",
            "reason": "",
        },
    )
    assert response.status_code == 200
    assert "form" in response.context
    assert response.context.get("is_edit") is True


# ---- TravelGrantProvideInfoView POST coverage ----


@pytest.mark.django_db
def test_provide_info_post_wrong_status_redirects(
    client: Client, conference: Conference, user: User, submitted_grant: TravelGrant
):
    """Lines 382-383: POST to provide-info when not info_needed redirects."""
    client.force_login(user)
    response = client.post(
        f"/{conference.slug}/programs/travel-grants/provide-info/",
        {"message": "Some info"},
    )
    assert response.status_code == 302


@pytest.mark.django_db
def test_provide_info_post_invalid_form_rerenders(client: Client, conference: Conference, user: User):
    """Line 386: POST to provide-info with empty message re-renders form."""
    TravelGrant.objects.create(
        conference=conference,
        user=user,
        status=TravelGrant.GrantStatus.INFO_NEEDED,
        requested_amount=Decimal("500.00"),
        travel_from="Chicago",
        reason="Need help",
    )
    client.force_login(user)
    response = client.post(
        f"/{conference.slug}/programs/travel-grants/provide-info/",
        {"message": ""},
    )
    assert response.status_code == 200
    assert "form" in response.context


# ---- ReceiptUploadView POST coverage ----


@pytest.mark.django_db
def test_receipt_upload_post_valid(client: Client, conference: Conference, user: User, accepted_grant: TravelGrant):
    """Lines 443-453: POST valid receipt uploads successfully."""
    receipt_file = SimpleUploadedFile("receipt.pdf", b"%PDF-1.4 content", content_type="application/pdf")
    client.force_login(user)
    response = client.post(
        f"/{conference.slug}/programs/travel-grants/receipts/",
        {
            "receipt_type": "airfare",
            "date": "2027-06-15",
            "amount": "250.00",
            "description": "Flight receipt",
            "receipt_file": receipt_file,
        },
    )
    assert response.status_code == 302
    assert Receipt.objects.filter(grant=accepted_grant).exists()


@pytest.mark.django_db
def test_receipt_upload_post_invalid_rerenders(
    client: Client, conference: Conference, user: User, accepted_grant: TravelGrant
):
    """Lines 454-455: POST invalid receipt re-renders form with existing receipts."""
    client.force_login(user)
    response = client.post(
        f"/{conference.slug}/programs/travel-grants/receipts/",
        {
            "receipt_type": "airfare",
            "date": "",
            "amount": "",
        },
    )
    assert response.status_code == 200
    assert "form" in response.context
    assert "receipts" in response.context


@pytest.mark.django_db
def test_receipt_upload_post_wrong_status_redirects(
    client: Client, conference: Conference, user: User, submitted_grant: TravelGrant
):
    """Lines 443-446: POST receipt when grant is not accepted redirects."""
    receipt_file = SimpleUploadedFile("receipt.pdf", b"%PDF-1.4 content", content_type="application/pdf")
    client.force_login(user)
    response = client.post(
        f"/{conference.slug}/programs/travel-grants/receipts/",
        {
            "receipt_type": "airfare",
            "date": "2027-06-15",
            "amount": "250.00",
            "description": "Flight",
            "receipt_file": receipt_file,
        },
    )
    assert response.status_code == 302


# ---- PaymentInfoView GET with existing payment info (line 496) ----


@pytest.mark.django_db
def test_payment_info_get_with_existing_info(
    client: Client, conference: Conference, user: User, accepted_grant: TravelGrant
):
    """Line 496: GET payment-info loads form pre-filled with existing PaymentInfo."""
    PaymentInfo.objects.create(
        grant=accepted_grant,
        payment_method=PaymentInfo.PaymentMethod.PAYPAL,
        legal_name="Jane Doe",
        address_street="123 Main St",
        address_city="Chicago",
        address_zip="60601",
        address_country="US",
        paypal_email="jane@example.com",
    )
    client.force_login(user)
    response = client.get(f"/{conference.slug}/programs/travel-grants/payment-info/")
    assert response.status_code == 200
    assert "form" in response.context
    assert response.context["form"].instance.pk is not None


# ---- PaymentInfoView POST wrong status (lines 513-514) ----


@pytest.mark.django_db
def test_payment_info_post_wrong_status_redirects(
    client: Client, conference: Conference, user: User, submitted_grant: TravelGrant
):
    """Lines 513-514: POST payment-info when grant is not accepted redirects."""
    client.force_login(user)
    response = client.post(
        f"/{conference.slug}/programs/travel-grants/payment-info/",
        {
            "payment_method": "paypal",
            "legal_name": "Jane Doe",
            "address_street": "123 Main St",
            "address_city": "Chicago",
            "address_state": "IL",
            "address_zip": "60601",
            "address_country": "US",
            "paypal_email": "jane@example.com",
        },
    )
    assert response.status_code == 302


# ---- PaymentInfoView POST invalid form (line 526) ----


@pytest.mark.django_db
def test_payment_info_post_invalid_rerenders(
    client: Client, conference: Conference, user: User, accepted_grant: TravelGrant
):
    """Line 526: POST payment-info with invalid data re-renders form."""
    client.force_login(user)
    response = client.post(
        f"/{conference.slug}/programs/travel-grants/payment-info/",
        {
            "payment_method": "paypal",
            "legal_name": "",
            "address_street": "",
            "address_city": "",
            "address_zip": "",
            "address_country": "",
        },
    )
    assert response.status_code == 200
    assert "form" in response.context
