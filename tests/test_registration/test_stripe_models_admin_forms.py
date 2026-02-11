"""Tests for Stripe models, read-only admin classes, registration forms, and stripe_tags."""

from datetime import date
from types import SimpleNamespace

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.http import HttpRequest

from django_program.conference.models import Conference
from django_program.registration.admin import (
    EventProcessingExceptionAdmin,
    StripeCustomerAdmin,
    StripeEventAdmin,
)
from django_program.registration.forms import (
    CartItemForm,
    CheckoutForm,
    RefundForm,
    VoucherApplyForm,
)
from django_program.registration.models import (
    EventProcessingException,
    Payment,
    StripeCustomer,
    StripeEvent,
)
from django_program.registration.templatetags.stripe_tags import stripe_public_key

User = get_user_model()


@pytest.fixture
def conference() -> Conference:
    return Conference.objects.create(
        name="StripeCon",
        slug="stripecon",
        start_date=date(2027, 5, 1),
        end_date=date(2027, 5, 3),
        timezone="UTC",
    )


@pytest.fixture
def user():
    return User.objects.create_user(username="stripe-user", email="stripe@example.com", password="testpass123")


@pytest.fixture
def site() -> AdminSite:
    return AdminSite()


@pytest.fixture
def request_obj() -> HttpRequest:
    return HttpRequest()


# ---------------------------------------------------------------------------
# StripeCustomer model
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_stripe_customer_str(conference: Conference, user):
    sc = StripeCustomer.objects.create(
        user=user,
        conference=conference,
        stripe_customer_id="cus_abc123",
    )
    assert str(sc) == f"{user} \u2192 cus_abc123"


@pytest.mark.django_db
def test_stripe_customer_unique_together(conference: Conference, user):
    StripeCustomer.objects.create(
        user=user,
        conference=conference,
        stripe_customer_id="cus_first",
    )
    with pytest.raises(IntegrityError):
        StripeCustomer.objects.create(
            user=user,
            conference=conference,
            stripe_customer_id="cus_second",
        )


# ---------------------------------------------------------------------------
# StripeEvent model
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_stripe_event_str_processed():
    evt = StripeEvent.objects.create(
        stripe_id="evt_processed_001",
        kind="payment_intent.succeeded",
        processed=True,
    )
    assert str(evt) == "payment_intent.succeeded (processed)"


@pytest.mark.django_db
def test_stripe_event_str_pending():
    evt = StripeEvent.objects.create(
        stripe_id="evt_pending_001",
        kind="charge.failed",
        processed=False,
    )
    assert str(evt) == "charge.failed (pending)"


@pytest.mark.django_db
def test_stripe_event_stripe_id_unique():
    StripeEvent.objects.create(stripe_id="evt_unique_001", kind="invoice.paid")
    with pytest.raises(IntegrityError):
        StripeEvent.objects.create(stripe_id="evt_unique_001", kind="invoice.paid")


# ---------------------------------------------------------------------------
# EventProcessingException model
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_event_processing_exception_str_short():
    exc = EventProcessingException.objects.create(message="Short error")
    assert str(exc) == "Short error"


@pytest.mark.django_db
def test_event_processing_exception_str_long():
    long_msg = "A" * 120
    exc = EventProcessingException.objects.create(message=long_msg)
    assert str(exc) == "A" * 80


@pytest.mark.django_db
def test_event_processing_exception_str_exactly_80():
    msg_80 = "B" * 80
    exc = EventProcessingException.objects.create(message=msg_80)
    assert str(exc) == msg_80


# ---------------------------------------------------------------------------
# Payment.Status choices
# ---------------------------------------------------------------------------


def test_payment_status_has_expected_choices():
    values = {choice.value for choice in Payment.Status}
    assert values == {"pending", "processing", "succeeded", "failed", "refunded"}


def test_payment_status_labels():
    assert Payment.Status.PENDING.label == "Pending"
    assert Payment.Status.PROCESSING.label == "Processing"
    assert Payment.Status.SUCCEEDED.label == "Succeeded"
    assert Payment.Status.FAILED.label == "Failed"
    assert Payment.Status.REFUNDED.label == "Refunded"


# ---------------------------------------------------------------------------
# Admin: read-only permission tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_stripe_customer_admin_has_no_add_permission(site, request_obj):
    admin_cls = StripeCustomerAdmin(StripeCustomer, site)
    assert admin_cls.has_add_permission(request_obj) is False


@pytest.mark.django_db
def test_stripe_customer_admin_has_no_change_permission(site, request_obj):
    admin_cls = StripeCustomerAdmin(StripeCustomer, site)
    assert admin_cls.has_change_permission(request_obj) is False
    assert admin_cls.has_change_permission(request_obj, obj=None) is False


@pytest.mark.django_db
def test_stripe_event_admin_has_no_add_permission(site, request_obj):
    admin_cls = StripeEventAdmin(StripeEvent, site)
    assert admin_cls.has_add_permission(request_obj) is False


@pytest.mark.django_db
def test_stripe_event_admin_has_no_change_permission(site, request_obj):
    admin_cls = StripeEventAdmin(StripeEvent, site)
    assert admin_cls.has_change_permission(request_obj) is False
    assert admin_cls.has_change_permission(request_obj, obj=None) is False


@pytest.mark.django_db
def test_event_processing_exception_admin_has_no_add_permission(site, request_obj):
    admin_cls = EventProcessingExceptionAdmin(EventProcessingException, site)
    assert admin_cls.has_add_permission(request_obj) is False


@pytest.mark.django_db
def test_event_processing_exception_admin_has_no_change_permission(site, request_obj):
    admin_cls = EventProcessingExceptionAdmin(EventProcessingException, site)
    assert admin_cls.has_change_permission(request_obj) is False
    assert admin_cls.has_change_permission(request_obj, obj=None) is False


# ---------------------------------------------------------------------------
# CartItemForm
# ---------------------------------------------------------------------------


def test_cart_item_form_valid_with_ticket_type_only():
    form = CartItemForm(data={"ticket_type_id": 1, "quantity": 1})
    assert form.is_valid()


def test_cart_item_form_valid_with_addon_only():
    form = CartItemForm(data={"addon_id": 5, "quantity": 2})
    assert form.is_valid()


def test_cart_item_form_invalid_with_both():
    form = CartItemForm(data={"ticket_type_id": 1, "addon_id": 5, "quantity": 1})
    assert not form.is_valid()
    assert "__all__" in form.errors


def test_cart_item_form_invalid_with_neither():
    form = CartItemForm(data={"quantity": 1})
    assert not form.is_valid()
    assert "__all__" in form.errors


# ---------------------------------------------------------------------------
# VoucherApplyForm
# ---------------------------------------------------------------------------


def test_voucher_apply_form_valid():
    form = VoucherApplyForm(data={"code": "SAVE50"})
    assert form.is_valid()


def test_voucher_apply_form_invalid_empty():
    form = VoucherApplyForm(data={"code": ""})
    assert not form.is_valid()


# ---------------------------------------------------------------------------
# CheckoutForm
# ---------------------------------------------------------------------------


def test_checkout_form_valid_with_required_fields():
    form = CheckoutForm(
        data={
            "billing_name": "Jane Doe",
            "billing_email": "jane@example.com",
        }
    )
    assert form.is_valid()


def test_checkout_form_valid_with_optional_company():
    form = CheckoutForm(
        data={
            "billing_name": "Jane Doe",
            "billing_email": "jane@example.com",
            "billing_company": "Acme Corp",
        }
    )
    assert form.is_valid()


def test_checkout_form_invalid_without_name():
    form = CheckoutForm(
        data={
            "billing_email": "jane@example.com",
        }
    )
    assert not form.is_valid()
    assert "billing_name" in form.errors


def test_checkout_form_invalid_without_email():
    form = CheckoutForm(
        data={
            "billing_name": "Jane Doe",
        }
    )
    assert not form.is_valid()
    assert "billing_email" in form.errors


# ---------------------------------------------------------------------------
# RefundForm
# ---------------------------------------------------------------------------


def test_refund_form_valid_with_positive_amount():
    form = RefundForm(data={"amount": "50.00"})
    assert form.is_valid()


def test_refund_form_invalid_with_zero_amount():
    form = RefundForm(data={"amount": "0.00"})
    assert not form.is_valid()
    assert "amount" in form.errors


def test_refund_form_invalid_with_negative_amount():
    form = RefundForm(data={"amount": "-10.00"})
    assert not form.is_valid()
    assert "amount" in form.errors


def test_refund_form_reason_is_optional():
    form = RefundForm(data={"amount": "25.00"})
    assert form.is_valid()


# ---------------------------------------------------------------------------
# Template tag: stripe_public_key
# ---------------------------------------------------------------------------


def test_stripe_public_key_returns_key_when_set():
    conf = SimpleNamespace(stripe_publishable_key="pk_test_abc123")
    assert stripe_public_key(conf) == "pk_test_abc123"


def test_stripe_public_key_returns_empty_when_none():
    conf = SimpleNamespace(stripe_publishable_key=None)
    assert stripe_public_key(conf) == ""


def test_stripe_public_key_returns_empty_when_attr_missing():
    conf = SimpleNamespace()
    assert stripe_public_key(conf) == ""
