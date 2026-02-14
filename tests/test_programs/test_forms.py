"""Tests for programs forms."""

import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

from django_program.conference.models import Conference, Section
from django_program.pretalx.models import Room, ScheduleSlot, Talk
from django_program.programs.forms import (
    PaymentInfoForm,
    ReceiptForm,
    TravelGrantApplicationForm,
)
from django_program.programs.models import TravelGrant


@pytest.fixture
def conference() -> Conference:
    return Conference.objects.create(
        name="FormCon",
        slug="formcon",
        start_date=datetime.date(2027, 5, 14),
        end_date=datetime.date(2027, 5, 22),
        timezone="UTC",
    )


@pytest.fixture
def user() -> User:
    return User.objects.create_user(username="formuser", password="testpass123")


# ---------------------------------------------------------------------------
# TravelGrantApplicationForm: days_attending pre-population (line 119)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_days_attending_prepopulated_from_instance(conference: Conference, user: User):
    """Line 119: initial['days_attending'] populated from comma-separated model value."""
    grant = TravelGrant.objects.create(
        conference=conference,
        user=user,
        requested_amount=Decimal("500.00"),
        travel_from="Chicago",
        reason="Need help",
        days_attending="2027-05-14,2027-05-15",
    )
    form = TravelGrantApplicationForm(instance=grant, conference=conference)
    assert form.initial["days_attending"] == ["2027-05-14", "2027-05-15"]


@pytest.mark.django_db
def test_days_attending_not_prepopulated_when_empty(conference: Conference, user: User):
    """When days_attending is empty, initial should not have the key set by our logic."""
    grant = TravelGrant.objects.create(
        conference=conference,
        user=user,
        requested_amount=Decimal("500.00"),
        travel_from="Chicago",
        reason="Need help",
        days_attending="",
    )
    form = TravelGrantApplicationForm(instance=grant, conference=conference)
    assert "days_attending" not in form.initial or form.initial.get("days_attending") in (None, "")


# ---------------------------------------------------------------------------
# TravelGrantApplicationForm.clean: cross-field validation (lines 143, 150, 158, 166)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_clean_ticket_and_grant_amount_less_than_one(conference: Conference):
    """Line 143: amount < 1 for ticket_and_grant triggers error."""
    form = TravelGrantApplicationForm(
        data={
            "request_type": TravelGrant.RequestType.TICKET_AND_GRANT,
            "application_type": "general",
            "requested_amount": "0.50",
            "travel_from": "Chicago",
            "reason": "Need help",
            "experience_level": "intermediate",
            "occupation": "Developer",
            "involvement": "Community work",
            "first_time": "True",
        },
        conference=conference,
    )
    assert not form.is_valid()
    assert "requested_amount" in form.errors


@pytest.mark.django_db
def test_clean_ticket_and_grant_amount_exceeds_max(conference: Conference):
    """Line 150: amount > max_grant_amount triggers error."""
    form = TravelGrantApplicationForm(
        data={
            "request_type": TravelGrant.RequestType.TICKET_AND_GRANT,
            "application_type": "general",
            "requested_amount": "999999.00",
            "travel_from": "Chicago",
            "reason": "Need help",
            "experience_level": "intermediate",
            "occupation": "Developer",
            "involvement": "Community work",
            "first_time": "True",
        },
        conference=conference,
    )
    assert not form.is_valid()
    assert "requested_amount" in form.errors


@pytest.mark.django_db
def test_clean_airfare_amount_without_description(conference: Conference):
    """Line 158: airfare amount set without description triggers error."""
    form = TravelGrantApplicationForm(
        data={
            "request_type": TravelGrant.RequestType.TICKET_AND_GRANT,
            "application_type": "general",
            "requested_amount": "500.00",
            "travel_from": "Chicago",
            "reason": "Need help",
            "experience_level": "intermediate",
            "occupation": "Developer",
            "involvement": "Community work",
            "first_time": "True",
            "travel_plans_airfare_amount": "300.00",
            "travel_plans_airfare_description": "",
        },
        conference=conference,
    )
    assert not form.is_valid()
    assert "travel_plans_airfare_description" in form.errors


@pytest.mark.django_db
def test_clean_lodging_amount_without_description(conference: Conference):
    """Line 166: lodging amount set without description triggers error."""
    form = TravelGrantApplicationForm(
        data={
            "request_type": TravelGrant.RequestType.TICKET_AND_GRANT,
            "application_type": "general",
            "requested_amount": "500.00",
            "travel_from": "Chicago",
            "reason": "Need help",
            "experience_level": "intermediate",
            "occupation": "Developer",
            "involvement": "Community work",
            "first_time": "True",
            "travel_plans_lodging_amount": "200.00",
            "travel_plans_lodging_description": "",
        },
        conference=conference,
    )
    assert not form.is_valid()
    assert "travel_plans_lodging_description" in form.errors


# ---------------------------------------------------------------------------
# TravelGrantApplicationForm._build_day_choices (lines 185-191, 199-200)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_build_day_choices_with_sections(conference: Conference):
    """Lines 185-191, 199-200: sections map dates to labeled choices."""
    Section.objects.create(
        conference=conference,
        name="Tutorials",
        slug="tutorials",
        start_date=datetime.date(2027, 5, 14),
        end_date=datetime.date(2027, 5, 15),
        order=0,
    )
    Section.objects.create(
        conference=conference,
        name="Talks",
        slug="talks",
        start_date=datetime.date(2027, 5, 16),
        end_date=datetime.date(2027, 5, 18),
        order=1,
    )
    form = TravelGrantApplicationForm(conference=conference)
    choices = form.fields["days_attending"].choices

    # Conference runs 2027-05-14 through 2027-05-22 (9 days)
    assert len(choices) == 9

    # First two days should be labeled Tutorials Day 1 / Day 2
    assert "Tutorials Day 1" in choices[0][1]
    assert "Tutorials Day 2" in choices[1][1]

    # Days 3-5 should be Talks
    assert "Talks Day 1" in choices[2][1]
    assert "Talks Day 2" in choices[3][1]
    assert "Talks Day 3" in choices[4][1]

    # Remaining days should get generic "Day N" labels
    assert "Day 6" in choices[5][1]


@pytest.mark.django_db
def test_build_day_choices_without_sections(conference: Conference):
    """All days get generic labels when no sections exist."""
    form = TravelGrantApplicationForm(conference=conference)
    choices = form.fields["days_attending"].choices
    assert len(choices) == 9
    # All should be generic "Day N" labels
    for _value, label in choices:
        assert "Day" in label


# ---------------------------------------------------------------------------
# ReceiptForm.clean_receipt_file (lines 234-238)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_receipt_form_rejects_large_file():
    """Lines 234-238: files over 10 MB are rejected."""
    large_file = SimpleUploadedFile(
        "big.pdf",
        b"x" * (10 * 1024 * 1024 + 1),
        content_type="application/pdf",
    )
    form = ReceiptForm(
        data={
            "receipt_type": "airfare",
            "date": "2027-06-15",
            "amount": "250.00",
            "description": "Flight",
        },
        files={"receipt_file": large_file},
    )
    assert not form.is_valid()
    assert "receipt_file" in form.errors


@pytest.mark.django_db
def test_receipt_form_accepts_small_file():
    """Files under 10 MB pass validation."""
    small_file = SimpleUploadedFile(
        "receipt.pdf",
        b"%PDF-1.4 small file",
        content_type="application/pdf",
    )
    form = ReceiptForm(
        data={
            "receipt_type": "airfare",
            "date": "2027-06-15",
            "amount": "250.00",
            "description": "Flight",
        },
        files={"receipt_file": small_file},
    )
    assert form.is_valid()


# ---------------------------------------------------------------------------
# PaymentInfoForm.clean: method-specific validation (lines 276, 278, 280, 282-287)
# ---------------------------------------------------------------------------

BASE_PAYMENT_DATA = {
    "legal_name": "Jane Doe",
    "address_street": "123 Main St",
    "address_city": "Chicago",
    "address_state": "IL",
    "address_zip": "60601",
    "address_country": "US",
}


def test_payment_form_paypal_requires_email():
    """Line 276: PayPal without paypal_email triggers error."""
    form = PaymentInfoForm(data={**BASE_PAYMENT_DATA, "payment_method": "paypal"})
    assert not form.is_valid()
    assert "paypal_email" in form.errors


def test_payment_form_zelle_requires_email():
    """Line 278: Zelle without zelle_email triggers error."""
    form = PaymentInfoForm(data={**BASE_PAYMENT_DATA, "payment_method": "zelle"})
    assert not form.is_valid()
    assert "zelle_email" in form.errors


def test_payment_form_wise_requires_email():
    """Line 280: Wise without wise_email triggers error."""
    form = PaymentInfoForm(data={**BASE_PAYMENT_DATA, "payment_method": "wise"})
    assert not form.is_valid()
    assert "wise_email" in form.errors


def test_payment_form_ach_requires_bank_fields():
    """Lines 282-287: ACH without bank fields triggers errors."""
    form = PaymentInfoForm(data={**BASE_PAYMENT_DATA, "payment_method": "ach"})
    assert not form.is_valid()
    assert "bank_name" in form.errors
    assert "bank_account_number" in form.errors
    assert "bank_routing_number" in form.errors


def test_payment_form_wire_requires_bank_fields():
    """Lines 282-287: Wire without bank fields triggers errors."""
    form = PaymentInfoForm(data={**BASE_PAYMENT_DATA, "payment_method": "wire"})
    assert not form.is_valid()
    assert "bank_name" in form.errors
    assert "bank_account_number" in form.errors
    assert "bank_routing_number" in form.errors


def test_payment_form_paypal_valid_with_email():
    """PayPal with email passes validation."""
    form = PaymentInfoForm(
        data={**BASE_PAYMENT_DATA, "payment_method": "paypal", "paypal_email": "jane@example.com"},
    )
    assert form.is_valid(), form.errors


def test_payment_form_check_no_extra_fields_required():
    """Check method does not require method-specific fields."""
    form = PaymentInfoForm(data={**BASE_PAYMENT_DATA, "payment_method": "check"})
    assert form.is_valid(), form.errors


# ---------------------------------------------------------------------------
# TravelGrantApplicationForm: schedule-derived day choices (line 118)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_days_attending_uses_schedule_choices_when_available(conference: Conference):
    """When schedule data exists, the form uses schedule-derived day choices."""
    room = Room.objects.create(conference=conference, pretalx_id=1, name="Hall A")
    for i in range(3):
        talk = Talk.objects.create(
            conference=conference,
            pretalx_code=f"SCHED{i}",
            title=f"Scheduled Talk {i}",
            submission_type="Tutorial",
        )
        ScheduleSlot.objects.create(
            conference=conference,
            talk=talk,
            room=Room.objects.create(conference=conference, pretalx_id=100 + i, name=f"Room {i}"),
            start=datetime.datetime(2027, 5, 14, 9 + i, 0, tzinfo=datetime.UTC),
            end=datetime.datetime(2027, 5, 14, 10 + i, 0, tzinfo=datetime.UTC),
            slot_type=ScheduleSlot.SlotType.TALK,
        )

    form = TravelGrantApplicationForm(conference=conference)
    choices = form.fields["days_attending"].choices

    # Schedule-derived choices should have ISO date keys and type-labeled values
    assert len(choices) == 1
    iso_date, label = choices[0]
    assert iso_date == "2027-05-14"
    assert "(Tutorial)" in label
