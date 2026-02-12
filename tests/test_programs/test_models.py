"""Tests for programs models."""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError

from django_program.conference.models import Conference
from django_program.pretalx.models import Room, Talk
from django_program.programs.models import Activity, ActivitySignup, PaymentInfo, Receipt, TravelGrant


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
    assert str(grant) == "Travel grant: attendee (submitted)"


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


@pytest.mark.django_db
def test_activity_summit_type(conference: Conference):
    activity = Activity.objects.create(
        conference=conference,
        name="Language Summit",
        slug="language-summit",
        activity_type=Activity.ActivityType.SUMMIT,
    )
    assert activity.get_activity_type_display() == "Summit"


@pytest.mark.django_db
def test_activity_pretalx_submission_type(conference: Conference):
    activity = Activity.objects.create(
        conference=conference,
        name="Tutorials",
        slug="tutorials",
        activity_type=Activity.ActivityType.TUTORIAL,
        pretalx_submission_type="Tutorial",
    )
    assert activity.pretalx_submission_type == "Tutorial"


@pytest.mark.django_db
def test_activity_room_fk(conference: Conference):
    room = Room.objects.create(conference=conference, pretalx_id=1, name="Main Hall")
    activity = Activity.objects.create(
        conference=conference,
        name="Workshop Day",
        slug="workshop-day",
        activity_type=Activity.ActivityType.WORKSHOP,
        room=room,
    )
    assert activity.room == room
    assert activity.room.name == "Main Hall"


@pytest.mark.django_db
def test_activity_talks_m2m(conference: Conference):
    activity = Activity.objects.create(
        conference=conference,
        name="Tutorials",
        slug="tutorials",
        activity_type=Activity.ActivityType.TUTORIAL,
        pretalx_submission_type="Tutorial",
    )
    talk = Talk.objects.create(
        conference=conference,
        pretalx_code="ABC123",
        title="Intro to Django",
        submission_type="Tutorial",
    )
    activity.talks.add(talk)
    assert talk in activity.talks.all()
    assert activity in talk.activities.all()


# ---- TravelGrant button visibility properties ----


@pytest.mark.django_db
def test_grant_button_visibility_offered(conference: Conference, user: User):
    grant = TravelGrant.objects.create(
        conference=conference,
        user=user,
        status=TravelGrant.GrantStatus.OFFERED,
        requested_amount=Decimal("500.00"),
        travel_from="Chicago",
        reason="Need help",
    )
    assert grant.show_accept_button is True
    assert grant.show_decline_button is True
    assert grant.show_withdraw_button is False
    assert grant.show_edit_button is False
    assert grant.show_provide_info_button is False


@pytest.mark.django_db
def test_grant_button_visibility_submitted(conference: Conference, user: User):
    grant = TravelGrant.objects.create(
        conference=conference,
        user=user,
        status=TravelGrant.GrantStatus.SUBMITTED,
        requested_amount=Decimal("500.00"),
        travel_from="Chicago",
        reason="Need help",
    )
    assert grant.show_accept_button is False
    assert grant.show_decline_button is False
    assert grant.show_withdraw_button is True
    assert grant.show_edit_button is True
    assert grant.show_provide_info_button is False


@pytest.mark.django_db
def test_grant_button_visibility_info_needed(conference: Conference, user: User):
    grant = TravelGrant.objects.create(
        conference=conference,
        user=user,
        status=TravelGrant.GrantStatus.INFO_NEEDED,
        requested_amount=Decimal("500.00"),
        travel_from="Chicago",
        reason="Need help",
    )
    assert grant.show_accept_button is False
    assert grant.show_withdraw_button is True
    assert grant.show_edit_button is True
    assert grant.show_provide_info_button is True


@pytest.mark.django_db
def test_grant_button_visibility_accepted(conference: Conference, user: User):
    grant = TravelGrant.objects.create(
        conference=conference,
        user=user,
        status=TravelGrant.GrantStatus.ACCEPTED,
        requested_amount=Decimal("500.00"),
        travel_from="Chicago",
        reason="Need help",
    )
    assert grant.show_accept_button is False
    assert grant.show_decline_button is False
    assert grant.show_withdraw_button is False
    assert grant.show_edit_button is False


# ---- Receipt model tests ----


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
def test_receipt_str(accepted_grant: TravelGrant):
    receipt = Receipt.objects.create(
        grant=accepted_grant,
        receipt_type=Receipt.ReceiptType.AIRFARE,
        amount=Decimal("250.00"),
        date=date(2027, 6, 15),
        receipt_file="test.pdf",
    )
    assert str(receipt) == "Airfare receipt - $250.00"


@pytest.mark.django_db
def test_receipt_status_pending(accepted_grant: TravelGrant):
    receipt = Receipt.objects.create(
        grant=accepted_grant,
        receipt_type=Receipt.ReceiptType.LODGING,
        amount=Decimal("150.00"),
        date=date(2027, 6, 15),
        receipt_file="test.jpg",
    )
    assert receipt.status == "pending"
    assert receipt.can_delete is True


@pytest.mark.django_db
def test_receipt_status_approved(accepted_grant: TravelGrant, user: User):
    receipt = Receipt.objects.create(
        grant=accepted_grant,
        receipt_type=Receipt.ReceiptType.AIRFARE,
        amount=Decimal("250.00"),
        date=date(2027, 6, 15),
        receipt_file="test.pdf",
        approved=True,
        approved_by=user,
    )
    assert receipt.status == "approved"
    assert receipt.can_delete is False


@pytest.mark.django_db
def test_receipt_status_flagged(accepted_grant: TravelGrant, user: User):
    receipt = Receipt.objects.create(
        grant=accepted_grant,
        receipt_type=Receipt.ReceiptType.LODGING,
        amount=Decimal("50.00"),
        date=date(2027, 6, 15),
        receipt_file="test.png",
        flagged=True,
        flagged_reason="Blurry image",
        flagged_by=user,
    )
    assert receipt.status == "flagged"
    assert receipt.can_delete is False


# ---- PaymentInfo model tests ----


@pytest.mark.django_db
def test_payment_info_str(accepted_grant: TravelGrant):
    info = PaymentInfo.objects.create(
        grant=accepted_grant,
        payment_method=PaymentInfo.PaymentMethod.PAYPAL,
        legal_name="Jane Doe",
        address_street="123 Main St",
        address_city="Chicago",
        address_zip="60601",
        address_country="US",
        paypal_email="jane@example.com",
    )
    assert str(info) == "Payment info for attendee (PayPal)"


@pytest.mark.django_db
def test_payment_info_one_to_one(accepted_grant: TravelGrant):
    PaymentInfo.objects.create(
        grant=accepted_grant,
        payment_method=PaymentInfo.PaymentMethod.ZELLE,
        legal_name="Jane Doe",
        address_street="123 Main St",
        address_city="Chicago",
        address_zip="60601",
        address_country="US",
    )
    with pytest.raises(IntegrityError):
        PaymentInfo.objects.create(
            grant=accepted_grant,
            payment_method=PaymentInfo.PaymentMethod.PAYPAL,
            legal_name="Jane Doe",
            address_street="123 Main St",
            address_city="Chicago",
            address_zip="60601",
            address_country="US",
        )


# ---- is_ready_for_disbursement property tests ----


@pytest.mark.django_db
def test_is_ready_for_disbursement_wrong_status(conference: Conference, user: User):
    """Grant that is not accepted should never be ready for disbursement."""
    grant = TravelGrant.objects.create(
        conference=conference,
        user=user,
        status=TravelGrant.GrantStatus.SUBMITTED,
        requested_amount=Decimal("500.00"),
        travel_from="Chicago",
        reason="Need help",
    )
    assert grant.is_ready_for_disbursement is False


@pytest.mark.django_db
def test_is_ready_for_disbursement_accepted_no_payment_info(accepted_grant: TravelGrant):
    """Accepted grant without payment info is not ready for disbursement."""
    assert accepted_grant.is_ready_for_disbursement is False


@pytest.mark.django_db
def test_is_ready_for_disbursement_accepted_payment_info_no_approved_receipts(accepted_grant: TravelGrant):
    """Accepted grant with payment info but no approved receipts is not ready."""
    PaymentInfo.objects.create(
        grant=accepted_grant,
        payment_method="zelle",
        legal_name="Test User",
        address_street="123 Main St",
        address_city="Pittsburgh",
        address_zip="15213",
        address_country="US",
    )
    # Add a receipt that is NOT approved
    Receipt.objects.create(
        grant=accepted_grant,
        receipt_type="airfare",
        amount=Decimal("500.00"),
        date=date.today(),
        receipt_file=SimpleUploadedFile("test.pdf", b"fake", content_type="application/pdf"),
        approved=False,
    )
    assert accepted_grant.is_ready_for_disbursement is False


@pytest.mark.django_db
def test_is_ready_for_disbursement_all_conditions_met(accepted_grant: TravelGrant):
    """Accepted grant with payment info and approved receipt is ready."""
    PaymentInfo.objects.create(
        grant=accepted_grant,
        payment_method="zelle",
        legal_name="Test User",
        address_street="123 Main St",
        address_city="Pittsburgh",
        address_zip="15213",
        address_country="US",
    )
    Receipt.objects.create(
        grant=accepted_grant,
        receipt_type="airfare",
        amount=Decimal("500.00"),
        date=date.today(),
        receipt_file=SimpleUploadedFile("test.pdf", b"fake", content_type="application/pdf"),
        approved=True,
    )
    assert accepted_grant.is_ready_for_disbursement is True
