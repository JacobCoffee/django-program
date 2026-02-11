"""Tests for the PaymentService in django_program.registration.services.payment."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from django_program.conference.models import Conference
from django_program.registration.models import Order, Payment
from django_program.registration.services.payment import (
    PaymentService,
    _extract_payment_intent_id,
    _mark_order_paid,
)
from django_program.registration.signals import order_paid

User = get_user_model()


# -- Fixtures -----------------------------------------------------------------


@pytest.fixture
def conference(db):
    return Conference.objects.create(
        name="TestCon",
        slug="testcon-pay",
        start_date="2027-06-01",
        end_date="2027-06-03",
        timezone="UTC",
        stripe_secret_key="sk_test_abc123",
        stripe_publishable_key="pk_test_xyz789",
    )


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="payuser",
        email="pay@example.com",
        password="testpass123",
    )


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username="staffuser",
        email="staff@example.com",
        password="testpass123",
        is_staff=True,
    )


@pytest.fixture
def order(conference, user):
    return Order.objects.create(
        conference=conference,
        user=user,
        status=Order.Status.PENDING,
        subtotal=Decimal("100.00"),
        total=Decimal("100.00"),
        reference="ORD-PAY001",
    )


@pytest.fixture
def zero_total_order(conference, user):
    return Order.objects.create(
        conference=conference,
        user=user,
        status=Order.Status.PENDING,
        subtotal=Decimal("0.00"),
        total=Decimal("0.00"),
        reference="ORD-PAY002",
    )


@pytest.fixture
def paid_order(conference, user):
    return Order.objects.create(
        conference=conference,
        user=user,
        status=Order.Status.PAID,
        subtotal=Decimal("100.00"),
        total=Decimal("100.00"),
        reference="ORD-PAY003",
    )


# =============================================================================
# TestExtractPaymentIntentId
# =============================================================================


@pytest.mark.unit
class TestExtractPaymentIntentId:
    def test_extracts_intent_id_from_valid_client_secret(self):
        result = _extract_payment_intent_id("pi_abc123_secret_xyz789")
        assert result == "pi_abc123"

    def test_extracts_intent_id_with_underscores_in_prefix(self):
        result = _extract_payment_intent_id("pi_3Qs_test_abc_secret_def456")
        assert result == "pi_3Qs_test_abc"

    def test_raises_on_missing_delimiter(self):
        with pytest.raises(ValueError, match="missing '_secret_' delimiter"):
            _extract_payment_intent_id("pi_abc123_no_delimiter")

    def test_raises_on_empty_string(self):
        with pytest.raises(ValueError, match="missing '_secret_' delimiter"):
            _extract_payment_intent_id("")


# =============================================================================
# TestMarkOrderPaid
# =============================================================================


@pytest.mark.unit
@pytest.mark.django_db
class TestMarkOrderPaid:
    def test_sets_status_to_paid(self, order):
        _mark_order_paid(order)

        order.refresh_from_db()
        assert order.status == Order.Status.PAID

    def test_clears_hold_expires_at(self, order):
        order.hold_expires_at = timezone.now()
        order.save(update_fields=["hold_expires_at"])

        _mark_order_paid(order)

        order.refresh_from_db()
        assert order.hold_expires_at is None

    def test_sends_order_paid_signal(self, order):
        signal_received = []

        def handler(sender, order, user, **kwargs):
            signal_received.append((order.pk, user.pk))

        order_paid.connect(handler)
        try:
            _mark_order_paid(order)
            assert len(signal_received) == 1
            assert signal_received[0] == (order.pk, order.user.pk)
        finally:
            order_paid.disconnect(handler)

    def test_signal_sender_is_order_class(self, order):
        signal_sender = []

        def handler(sender, **kwargs):
            signal_sender.append(sender)

        order_paid.connect(handler)
        try:
            _mark_order_paid(order)
            assert signal_sender[0] is Order
        finally:
            order_paid.disconnect(handler)

    def test_without_hold_expires_at_field(self, order):
        with patch(
            "django_program.registration.services.payment._order_has_hold_expires_at",
            return_value=False,
        ):
            _mark_order_paid(order)

        order.refresh_from_db()
        assert order.status == Order.Status.PAID


# =============================================================================
# TestInitiatePayment
# =============================================================================


@pytest.mark.unit
@pytest.mark.django_db
class TestInitiatePayment:
    @patch("django_program.registration.services.payment.StripeClient")
    def test_returns_client_secret(self, mock_stripe_cls, order):
        mock_client = MagicMock()
        mock_stripe_cls.return_value = mock_client
        mock_customer = MagicMock()
        mock_customer.stripe_customer_id = "cus_test_123"
        mock_client.get_or_create_customer.return_value = mock_customer
        mock_client.create_payment_intent.return_value = "pi_intent123_secret_abc789"

        result = PaymentService.initiate_payment(order)

        assert result == "pi_intent123_secret_abc789"

    @patch("django_program.registration.services.payment.StripeClient")
    def test_creates_stripe_client_with_conference(self, mock_stripe_cls, order):
        mock_client = MagicMock()
        mock_stripe_cls.return_value = mock_client
        mock_customer = MagicMock()
        mock_customer.stripe_customer_id = "cus_test_123"
        mock_client.get_or_create_customer.return_value = mock_customer
        mock_client.create_payment_intent.return_value = "pi_intent123_secret_abc789"

        PaymentService.initiate_payment(order)

        mock_stripe_cls.assert_called_once_with(order.conference)

    @patch("django_program.registration.services.payment.StripeClient")
    def test_creates_pending_payment_record(self, mock_stripe_cls, order):
        mock_client = MagicMock()
        mock_stripe_cls.return_value = mock_client
        mock_customer = MagicMock()
        mock_customer.stripe_customer_id = "cus_test_123"
        mock_client.get_or_create_customer.return_value = mock_customer
        mock_client.create_payment_intent.return_value = "pi_intent123_secret_abc789"

        PaymentService.initiate_payment(order)

        payment = Payment.objects.get(order=order)
        assert payment.method == Payment.Method.STRIPE
        assert payment.status == Payment.Status.PENDING
        assert payment.amount == Decimal("100.00")
        assert payment.stripe_payment_intent_id == "pi_intent123"

    @patch("django_program.registration.services.payment.StripeClient")
    def test_calls_get_or_create_customer(self, mock_stripe_cls, order):
        mock_client = MagicMock()
        mock_stripe_cls.return_value = mock_client
        mock_customer = MagicMock()
        mock_customer.stripe_customer_id = "cus_test_123"
        mock_client.get_or_create_customer.return_value = mock_customer
        mock_client.create_payment_intent.return_value = "pi_intent123_secret_abc789"

        PaymentService.initiate_payment(order)

        mock_client.get_or_create_customer.assert_called_once_with(order.user)

    @patch("django_program.registration.services.payment.StripeClient")
    def test_calls_create_payment_intent_with_order_and_customer(self, mock_stripe_cls, order):
        mock_client = MagicMock()
        mock_stripe_cls.return_value = mock_client
        mock_customer = MagicMock()
        mock_customer.stripe_customer_id = "cus_test_123"
        mock_client.get_or_create_customer.return_value = mock_customer
        mock_client.create_payment_intent.return_value = "pi_intent123_secret_abc789"

        PaymentService.initiate_payment(order)

        mock_client.create_payment_intent.assert_called_once_with(order, "cus_test_123")

    def test_raises_for_non_pending_order(self, paid_order):
        with pytest.raises(ValidationError, match="Payment can only be initiated for pending orders"):
            PaymentService.initiate_payment(paid_order)

    def test_raises_for_cancelled_order(self, conference, user):
        cancelled_order = Order.objects.create(
            conference=conference,
            user=user,
            status=Order.Status.CANCELLED,
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
            reference="ORD-PAY-CANCEL",
        )
        with pytest.raises(ValidationError, match="Payment can only be initiated for pending orders"):
            PaymentService.initiate_payment(cancelled_order)

    @patch("django_program.registration.services.payment.StripeClient")
    def test_no_payment_created_for_non_pending_order(self, mock_stripe_cls, paid_order):
        with pytest.raises(ValidationError):
            PaymentService.initiate_payment(paid_order)

        assert Payment.objects.filter(order=paid_order).count() == 0


# =============================================================================
# TestRecordComp
# =============================================================================


@pytest.mark.unit
@pytest.mark.django_db
class TestRecordComp:
    def test_creates_succeeded_comp_payment(self, zero_total_order):
        payment = PaymentService.record_comp(zero_total_order)

        assert payment.method == Payment.Method.COMP
        assert payment.status == Payment.Status.SUCCEEDED
        assert payment.amount == Decimal("0.00")
        assert payment.order == zero_total_order

    def test_marks_order_as_paid(self, zero_total_order):
        PaymentService.record_comp(zero_total_order)

        zero_total_order.refresh_from_db()
        assert zero_total_order.status == Order.Status.PAID

    def test_clears_hold_expires_at(self, zero_total_order):
        zero_total_order.hold_expires_at = timezone.now()
        zero_total_order.save(update_fields=["hold_expires_at"])

        PaymentService.record_comp(zero_total_order)

        zero_total_order.refresh_from_db()
        assert zero_total_order.hold_expires_at is None

    def test_sends_order_paid_signal(self, zero_total_order):
        signal_received = []

        def handler(sender, order, user, **kwargs):
            signal_received.append((order.pk, user.pk))

        order_paid.connect(handler)
        try:
            PaymentService.record_comp(zero_total_order)
            assert len(signal_received) == 1
            assert signal_received[0] == (zero_total_order.pk, zero_total_order.user.pk)
        finally:
            order_paid.disconnect(handler)

    def test_raises_for_non_pending_order(self, paid_order):
        with pytest.raises(ValidationError, match="Comp payments can only be recorded for pending orders"):
            PaymentService.record_comp(paid_order)

    def test_raises_for_non_zero_total(self, order):
        with pytest.raises(ValidationError, match="Comp payments are only valid for orders with a zero total"):
            PaymentService.record_comp(order)

    def test_raises_for_cancelled_order_with_zero_total(self, conference, user):
        cancelled_order = Order.objects.create(
            conference=conference,
            user=user,
            status=Order.Status.CANCELLED,
            subtotal=Decimal("0.00"),
            total=Decimal("0.00"),
            reference="ORD-PAY-COMPCANCEL",
        )
        with pytest.raises(ValidationError, match="Comp payments can only be recorded for pending orders"):
            PaymentService.record_comp(cancelled_order)

    def test_no_payment_created_for_non_pending_order(self, paid_order):
        with pytest.raises(ValidationError):
            PaymentService.record_comp(paid_order)

        assert Payment.objects.filter(order=paid_order).count() == 0

    def test_no_payment_created_for_non_zero_total(self, order):
        with pytest.raises(ValidationError):
            PaymentService.record_comp(order)

        assert Payment.objects.filter(order=order).count() == 0


# =============================================================================
# TestRecordManual
# =============================================================================


@pytest.mark.unit
@pytest.mark.django_db
class TestRecordManual:
    def test_creates_succeeded_manual_payment(self, order):
        payment = PaymentService.record_manual(order, amount=Decimal("100.00"))

        assert payment.method == Payment.Method.MANUAL
        assert payment.status == Payment.Status.SUCCEEDED
        assert payment.amount == Decimal("100.00")
        assert payment.order == order

    def test_marks_order_paid_when_fully_covered(self, order):
        PaymentService.record_manual(order, amount=Decimal("100.00"))

        order.refresh_from_db()
        assert order.status == Order.Status.PAID

    def test_marks_order_paid_when_overpaid(self, order):
        PaymentService.record_manual(order, amount=Decimal("150.00"))

        order.refresh_from_db()
        assert order.status == Order.Status.PAID

    def test_does_not_mark_paid_for_partial_payment(self, order):
        PaymentService.record_manual(order, amount=Decimal("50.00"))

        order.refresh_from_db()
        assert order.status == Order.Status.PENDING

    def test_multiple_partial_payments_mark_paid(self, order):
        PaymentService.record_manual(order, amount=Decimal("60.00"))
        order.refresh_from_db()
        assert order.status == Order.Status.PENDING

        PaymentService.record_manual(order, amount=Decimal("40.00"))
        order.refresh_from_db()
        assert order.status == Order.Status.PAID

    def test_stores_reference(self, order):
        payment = PaymentService.record_manual(
            order,
            amount=Decimal("100.00"),
            reference="RECEIPT-12345",
        )

        assert payment.reference == "RECEIPT-12345"

    def test_stores_note(self, order):
        payment = PaymentService.record_manual(
            order,
            amount=Decimal("100.00"),
            note="Cash payment at door",
        )

        assert payment.note == "Cash payment at door"

    def test_stores_staff_user(self, order, staff_user):
        payment = PaymentService.record_manual(
            order,
            amount=Decimal("100.00"),
            staff_user=staff_user,
        )

        assert payment.created_by == staff_user

    def test_staff_user_defaults_to_none(self, order):
        payment = PaymentService.record_manual(order, amount=Decimal("100.00"))

        assert payment.created_by is None

    def test_reference_defaults_to_empty_string(self, order):
        payment = PaymentService.record_manual(order, amount=Decimal("100.00"))

        assert payment.reference == ""

    def test_note_defaults_to_empty_string(self, order):
        payment = PaymentService.record_manual(order, amount=Decimal("100.00"))

        assert payment.note == ""

    def test_raises_for_non_pending_order(self, paid_order):
        with pytest.raises(ValidationError, match="Manual payments can only be recorded for pending orders"):
            PaymentService.record_manual(paid_order, amount=Decimal("100.00"))

    def test_raises_for_zero_amount(self, order):
        with pytest.raises(ValidationError, match="Payment amount must be greater than zero"):
            PaymentService.record_manual(order, amount=Decimal("0.00"))

    def test_raises_for_negative_amount(self, order):
        with pytest.raises(ValidationError, match="Payment amount must be greater than zero"):
            PaymentService.record_manual(order, amount=Decimal("-10.00"))

    def test_no_payment_created_for_non_pending_order(self, paid_order):
        with pytest.raises(ValidationError):
            PaymentService.record_manual(paid_order, amount=Decimal("100.00"))

        assert Payment.objects.filter(order=paid_order).count() == 0

    def test_no_payment_created_for_zero_amount(self, order):
        with pytest.raises(ValidationError):
            PaymentService.record_manual(order, amount=Decimal("0.00"))

        assert Payment.objects.filter(order=order).count() == 0

    def test_sends_signal_when_fully_paid(self, order):
        signal_received = []

        def handler(sender, order, user, **kwargs):
            signal_received.append((order.pk, user.pk))

        order_paid.connect(handler)
        try:
            PaymentService.record_manual(order, amount=Decimal("100.00"))
            assert len(signal_received) == 1
            assert signal_received[0] == (order.pk, order.user.pk)
        finally:
            order_paid.disconnect(handler)

    def test_does_not_send_signal_for_partial_payment(self, order):
        signal_received = []

        def handler(sender, order, user, **kwargs):
            signal_received.append((order.pk, user.pk))

        order_paid.connect(handler)
        try:
            PaymentService.record_manual(order, amount=Decimal("50.00"))
            assert len(signal_received) == 0
        finally:
            order_paid.disconnect(handler)

    def test_clears_hold_expires_at_when_fully_paid(self, order):
        order.hold_expires_at = timezone.now()
        order.save(update_fields=["hold_expires_at"])

        PaymentService.record_manual(order, amount=Decimal("100.00"))

        order.refresh_from_db()
        assert order.hold_expires_at is None

    def test_does_not_clear_hold_for_partial_payment(self, order):
        hold_time = timezone.now()
        order.hold_expires_at = hold_time
        order.save(update_fields=["hold_expires_at"])

        PaymentService.record_manual(order, amount=Decimal("50.00"))

        order.refresh_from_db()
        assert order.hold_expires_at is not None

    def test_raises_for_refunded_order(self, conference, user):
        refunded_order = Order.objects.create(
            conference=conference,
            user=user,
            status=Order.Status.REFUNDED,
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
            reference="ORD-PAY-REFUND",
        )
        with pytest.raises(ValidationError, match="Manual payments can only be recorded for pending orders"):
            PaymentService.record_manual(refunded_order, amount=Decimal("50.00"))
