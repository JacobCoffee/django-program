"""Tests for the RefundService in django_program.registration.services.refund."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from django_program.conference.models import Conference
from django_program.registration.models import Credit, Order, Payment
from django_program.registration.services.refund import RefundService
from django_program.registration.signals import order_paid

User = get_user_model()


# -- Helpers ------------------------------------------------------------------


def _make_order(*, conference, user, status, total=Decimal("100.00"), reference=None):
    return Order.objects.create(
        conference=conference,
        user=user,
        status=status,
        subtotal=total,
        total=total,
        reference=reference or f"ORD-{uuid4().hex[:8].upper()}",
    )


def _make_stripe_payment(order, *, amount=None, intent_id="pi_test_123"):
    return Payment.objects.create(
        order=order,
        method=Payment.Method.STRIPE,
        status=Payment.Status.SUCCEEDED,
        amount=amount if amount is not None else order.total,
        stripe_payment_intent_id=intent_id,
    )


# -- Fixtures -----------------------------------------------------------------


@pytest.fixture
def conference():
    return Conference.objects.create(
        name="TestCon",
        slug="testcon-refund",
        start_date=date(2027, 6, 1),
        end_date=date(2027, 6, 3),
        timezone="UTC",
        stripe_secret_key="sk_test_abc123",
        stripe_publishable_key="pk_test_xyz789",
    )


@pytest.fixture
def other_conference():
    return Conference.objects.create(
        name="OtherCon",
        slug="othercon-refund",
        start_date=date(2027, 7, 1),
        end_date=date(2027, 7, 3),
        timezone="UTC",
        stripe_secret_key="sk_test_other",
        stripe_publishable_key="pk_test_other",
    )


@pytest.fixture
def user():
    return User.objects.create_user(
        username="refunduser",
        email="refund@example.com",
        password="testpass123",
    )


@pytest.fixture
def other_user():
    return User.objects.create_user(
        username="otherrefunduser",
        email="otherrefund@example.com",
        password="testpass123",
    )


@pytest.fixture
def staff_user():
    return User.objects.create_user(
        username="staffuser",
        email="staff@example.com",
        password="testpass123",
        is_staff=True,
    )


@pytest.fixture
def paid_order(conference, user):
    order = _make_order(conference=conference, user=user, status=Order.Status.PAID)
    _make_stripe_payment(order)
    return order


# =============================================================================
# TestCreateRefund
# =============================================================================


@pytest.mark.unit
@pytest.mark.django_db
class TestCreateRefund:
    @patch("django_program.registration.services.refund.StripeClient")
    def test_full_refund_sets_status_to_refunded(self, mock_stripe_cls, paid_order):
        mock_client = MagicMock()
        mock_stripe_cls.return_value = mock_client

        credit = RefundService.create_refund(paid_order, amount=Decimal("100.00"))

        assert credit.amount == Decimal("100.00")
        assert credit.remaining_amount == Decimal("100.00")
        assert credit.status == Credit.Status.AVAILABLE
        assert credit.source_order == paid_order
        assert credit.user == paid_order.user
        assert credit.conference == paid_order.conference

        paid_order.refresh_from_db()
        assert paid_order.status == Order.Status.REFUNDED

        mock_stripe_cls.assert_called_once_with(paid_order.conference)
        mock_client.create_refund.assert_called_once_with(
            "pi_test_123",
            Decimal("100.00"),
            "requested_by_customer",
        )

    @patch("django_program.registration.services.refund.StripeClient")
    def test_partial_refund_sets_status_to_partially_refunded(self, mock_stripe_cls, paid_order):
        mock_stripe_cls.return_value = MagicMock()

        credit = RefundService.create_refund(paid_order, amount=Decimal("30.00"))

        assert credit.amount == Decimal("30.00")

        paid_order.refresh_from_db()
        assert paid_order.status == Order.Status.PARTIALLY_REFUNDED

    @patch("django_program.registration.services.refund.StripeClient")
    def test_second_partial_refund_on_partially_refunded_order(self, mock_stripe_cls, paid_order):
        mock_stripe_cls.return_value = MagicMock()

        RefundService.create_refund(paid_order, amount=Decimal("40.00"))
        paid_order.refresh_from_db()
        assert paid_order.status == Order.Status.PARTIALLY_REFUNDED

        credit2 = RefundService.create_refund(paid_order, amount=Decimal("60.00"))
        assert credit2.amount == Decimal("60.00")

        paid_order.refresh_from_db()
        assert paid_order.status == Order.Status.REFUNDED

    def test_rejects_pending_order(self, conference, user):
        order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)
        _make_stripe_payment(order)

        with pytest.raises(ValidationError, match="Only paid or partially refunded"):
            RefundService.create_refund(order, amount=Decimal("50.00"))

    def test_rejects_cancelled_order(self, conference, user):
        order = _make_order(conference=conference, user=user, status=Order.Status.CANCELLED)
        _make_stripe_payment(order)

        with pytest.raises(ValidationError, match="Only paid or partially refunded"):
            RefundService.create_refund(order, amount=Decimal("50.00"))

    def test_rejects_fully_refunded_order(self, conference, user):
        order = _make_order(conference=conference, user=user, status=Order.Status.REFUNDED)
        _make_stripe_payment(order)

        with pytest.raises(ValidationError, match="Only paid or partially refunded"):
            RefundService.create_refund(order, amount=Decimal("50.00"))

    def test_rejects_zero_amount(self, paid_order):
        with pytest.raises(ValidationError, match="greater than zero"):
            RefundService.create_refund(paid_order, amount=Decimal("0.00"))

    def test_rejects_negative_amount(self, paid_order):
        with pytest.raises(ValidationError, match="greater than zero"):
            RefundService.create_refund(paid_order, amount=Decimal("-10.00"))

    def test_rejects_when_no_stripe_payment(self, conference, user):
        order = _make_order(conference=conference, user=user, status=Order.Status.PAID)
        # No stripe payment created

        with pytest.raises(ValidationError, match="No succeeded Stripe payment"):
            RefundService.create_refund(order, amount=Decimal("50.00"))

    def test_rejects_when_only_failed_stripe_payment(self, conference, user):
        order = _make_order(conference=conference, user=user, status=Order.Status.PAID)
        Payment.objects.create(
            order=order,
            method=Payment.Method.STRIPE,
            status=Payment.Status.FAILED,
            amount=Decimal("100.00"),
            stripe_payment_intent_id="pi_failed",
        )

        with pytest.raises(ValidationError, match="No succeeded Stripe payment"):
            RefundService.create_refund(order, amount=Decimal("50.00"))

    @patch("django_program.registration.services.refund.StripeClient")
    def test_rejects_amount_exceeding_refundable_balance(self, mock_stripe_cls, paid_order):
        mock_stripe_cls.return_value = MagicMock()

        with pytest.raises(ValidationError, match="exceeds the refundable balance"):
            RefundService.create_refund(paid_order, amount=Decimal("150.00"))

    @patch("django_program.registration.services.refund.StripeClient")
    def test_rejects_amount_exceeding_remaining_after_prior_refund(self, mock_stripe_cls, paid_order):
        mock_stripe_cls.return_value = MagicMock()

        RefundService.create_refund(paid_order, amount=Decimal("70.00"))

        with pytest.raises(ValidationError, match="exceeds the refundable balance"):
            RefundService.create_refund(paid_order, amount=Decimal("50.00"))

    @patch("django_program.registration.services.refund.StripeClient")
    def test_staff_user_label_in_note(self, mock_stripe_cls, paid_order, staff_user):
        mock_stripe_cls.return_value = MagicMock()

        credit = RefundService.create_refund(
            paid_order,
            amount=Decimal("25.00"),
            staff_user=staff_user,
        )

        assert f"by {staff_user}" in credit.note
        assert f"Refund for order {paid_order.reference}" in credit.note

    @patch("django_program.registration.services.refund.StripeClient")
    def test_no_staff_user_omits_label_from_note(self, mock_stripe_cls, paid_order):
        mock_stripe_cls.return_value = MagicMock()

        credit = RefundService.create_refund(paid_order, amount=Decimal("25.00"))

        assert " by " not in credit.note
        assert "requested_by_customer" in credit.note

    @patch("django_program.registration.services.refund.StripeClient")
    def test_custom_reason_in_note_and_stripe_call(self, mock_stripe_cls, paid_order):
        mock_client = MagicMock()
        mock_stripe_cls.return_value = mock_client

        credit = RefundService.create_refund(
            paid_order,
            amount=Decimal("50.00"),
            reason="duplicate",
        )

        assert "duplicate" in credit.note
        mock_client.create_refund.assert_called_once_with(
            "pi_test_123",
            Decimal("50.00"),
            "duplicate",
        )

    @patch("django_program.registration.services.refund.StripeClient")
    def test_only_counts_stripe_payments_in_refundable_balance(self, mock_stripe_cls, conference, user):
        """Manual succeeded payments should not contribute to the refundable balance."""
        mock_stripe_cls.return_value = MagicMock()

        order = _make_order(
            conference=conference,
            user=user,
            status=Order.Status.PAID,
            total=Decimal("150.00"),
        )
        # $100 Stripe payment
        _make_stripe_payment(order, amount=Decimal("100.00"))
        # $50 manual payment (should be excluded from refundable calculation)
        Payment.objects.create(
            order=order,
            method=Payment.Method.MANUAL,
            status=Payment.Status.SUCCEEDED,
            amount=Decimal("50.00"),
        )

        # Refundable balance should be $100 (only Stripe), not $150
        with pytest.raises(ValidationError, match="exceeds the refundable balance"):
            RefundService.create_refund(order, amount=Decimal("110.00"))

        # But $100 should succeed (exactly the Stripe balance)
        credit = RefundService.create_refund(order, amount=Decimal("100.00"))
        assert credit.amount == Decimal("100.00")

    @patch("django_program.registration.services.refund.StripeClient")
    def test_uses_first_succeeded_stripe_payment_intent_id(self, mock_stripe_cls, conference, user):
        """When multiple Stripe payments exist, the first succeeded one is used for the refund."""
        mock_client = MagicMock()
        mock_stripe_cls.return_value = mock_client

        order = _make_order(
            conference=conference,
            user=user,
            status=Order.Status.PAID,
            total=Decimal("200.00"),
        )
        _make_stripe_payment(order, amount=Decimal("100.00"), intent_id="pi_first")
        _make_stripe_payment(order, amount=Decimal("100.00"), intent_id="pi_second")

        RefundService.create_refund(order, amount=Decimal("50.00"))

        called_intent_id = mock_client.create_refund.call_args[0][0]
        assert called_intent_id in ("pi_first", "pi_second")


# =============================================================================
# TestApplyCreditAsRefund
# =============================================================================


@pytest.mark.unit
@pytest.mark.django_db
class TestApplyCreditAsRefund:
    def test_happy_path_credit_fully_consumed_order_becomes_paid(self, conference, user):
        source_order = _make_order(conference=conference, user=user, status=Order.Status.PAID)
        target_order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)

        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("100.00"),
            status=Credit.Status.AVAILABLE,
            source_order=source_order,
        )

        payment = RefundService.apply_credit_as_refund(credit, target_order)

        assert payment.method == Payment.Method.CREDIT
        assert payment.status == Payment.Status.SUCCEEDED
        assert payment.amount == Decimal("100.00")
        assert payment.order == target_order

        credit.refresh_from_db()
        assert credit.status == Credit.Status.APPLIED
        assert credit.remaining_amount == Decimal("0.00")
        assert credit.applied_to_order == target_order

        target_order.refresh_from_db()
        assert target_order.status == Order.Status.PAID

    def test_partial_credit_larger_than_order_balance(self, conference, user):
        """Credit has more remaining than the order needs; only the order balance is consumed."""
        target_order = _make_order(
            conference=conference,
            user=user,
            status=Order.Status.PENDING,
            total=Decimal("50.00"),
        )
        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("200.00"),
            status=Credit.Status.AVAILABLE,
        )

        payment = RefundService.apply_credit_as_refund(credit, target_order)

        assert payment.amount == Decimal("50.00")

        credit.refresh_from_db()
        assert credit.status == Credit.Status.AVAILABLE
        assert credit.remaining_amount == Decimal("150.00")

        target_order.refresh_from_db()
        assert target_order.status == Order.Status.PAID

    def test_partial_credit_smaller_than_order_balance(self, conference, user):
        """Credit is smaller than the order total; order stays pending."""
        target_order = _make_order(
            conference=conference,
            user=user,
            status=Order.Status.PENDING,
            total=Decimal("200.00"),
        )
        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("50.00"),
            status=Credit.Status.AVAILABLE,
        )

        payment = RefundService.apply_credit_as_refund(credit, target_order)

        assert payment.amount == Decimal("50.00")

        credit.refresh_from_db()
        assert credit.status == Credit.Status.APPLIED
        assert credit.remaining_amount == Decimal("0.00")

        target_order.refresh_from_db()
        assert target_order.status == Order.Status.PENDING

    def test_rejects_non_available_credit(self, conference, user):
        target_order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)

        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("50.00"),
            status=Credit.Status.APPLIED,
        )

        with pytest.raises(ValidationError, match="Only available credits"):
            RefundService.apply_credit_as_refund(credit, target_order)

    def test_rejects_expired_credit(self, conference, user):
        target_order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)

        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("50.00"),
            status=Credit.Status.EXPIRED,
        )

        with pytest.raises(ValidationError, match="Only available credits"):
            RefundService.apply_credit_as_refund(credit, target_order)

    def test_rejects_zero_remaining_amount(self, conference, user):
        target_order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)

        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("50.00"),
            status=Credit.Status.AVAILABLE,
        )
        # Bypass the save() auto-init by updating directly in DB
        Credit.objects.filter(pk=credit.pk).update(remaining_amount=Decimal("0.00"))
        credit.refresh_from_db()

        with pytest.raises(ValidationError, match="no remaining balance"):
            RefundService.apply_credit_as_refund(credit, target_order)

    def test_rejects_non_pending_order(self, conference, user):
        target_order = _make_order(conference=conference, user=user, status=Order.Status.PAID)

        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("50.00"),
            status=Credit.Status.AVAILABLE,
        )

        with pytest.raises(ValidationError, match="pending orders"):
            RefundService.apply_credit_as_refund(credit, target_order)

    def test_rejects_cancelled_order(self, conference, user):
        target_order = _make_order(conference=conference, user=user, status=Order.Status.CANCELLED)

        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("50.00"),
            status=Credit.Status.AVAILABLE,
        )

        with pytest.raises(ValidationError, match="pending orders"):
            RefundService.apply_credit_as_refund(credit, target_order)

    def test_rejects_different_user(self, conference, user, other_user):
        target_order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)

        credit = Credit.objects.create(
            user=other_user,
            conference=conference,
            amount=Decimal("50.00"),
            status=Credit.Status.AVAILABLE,
        )

        with pytest.raises(ValidationError, match="same user"):
            RefundService.apply_credit_as_refund(credit, target_order)

    def test_rejects_different_conference(self, conference, other_conference, user):
        target_order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)

        credit = Credit.objects.create(
            user=user,
            conference=other_conference,
            amount=Decimal("50.00"),
            status=Credit.Status.AVAILABLE,
        )

        with pytest.raises(ValidationError, match="same conference"):
            RefundService.apply_credit_as_refund(credit, target_order)

    def test_rejects_already_fully_paid_order(self, conference, user):
        target_order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)

        Payment.objects.create(
            order=target_order,
            method=Payment.Method.STRIPE,
            status=Payment.Status.SUCCEEDED,
            amount=target_order.total,
        )

        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("50.00"),
            status=Credit.Status.AVAILABLE,
        )

        with pytest.raises(ValidationError, match="already fully paid"):
            RefundService.apply_credit_as_refund(credit, target_order)

    def test_fires_order_paid_signal_when_order_becomes_paid(self, conference, user):
        target_order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)

        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("100.00"),
            status=Credit.Status.AVAILABLE,
        )

        signal_received = []

        def handler(sender, order, user, **kwargs):
            signal_received.append((order.pk, user.pk))

        order_paid.connect(handler)
        try:
            RefundService.apply_credit_as_refund(credit, target_order)
            assert len(signal_received) == 1
            assert signal_received[0] == (target_order.pk, user.pk)
        finally:
            order_paid.disconnect(handler)

    def test_does_not_fire_signal_when_order_remains_pending(self, conference, user):
        target_order = _make_order(
            conference=conference,
            user=user,
            status=Order.Status.PENDING,
            total=Decimal("200.00"),
        )

        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("50.00"),
            status=Credit.Status.AVAILABLE,
        )

        signal_received = []

        def handler(sender, order, user, **kwargs):
            signal_received.append(True)

        order_paid.connect(handler)
        try:
            RefundService.apply_credit_as_refund(credit, target_order)
            assert len(signal_received) == 0
        finally:
            order_paid.disconnect(handler)

    def test_hold_expires_at_cleared_when_order_becomes_paid(self, conference, user):
        target_order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)
        target_order.hold_expires_at = timezone.now()
        target_order.save(update_fields=["hold_expires_at", "updated_at"])

        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("100.00"),
            status=Credit.Status.AVAILABLE,
        )

        RefundService.apply_credit_as_refund(credit, target_order)

        target_order.refresh_from_db()
        assert target_order.status == Order.Status.PAID
        assert target_order.hold_expires_at is None

    def test_credit_applied_to_order_set_on_partial_application(self, conference, user):
        """Even when the credit is not fully consumed, applied_to_order is set."""
        target_order = _make_order(
            conference=conference,
            user=user,
            status=Order.Status.PENDING,
            total=Decimal("30.00"),
        )

        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("100.00"),
            status=Credit.Status.AVAILABLE,
        )

        RefundService.apply_credit_as_refund(credit, target_order)

        credit.refresh_from_db()
        assert credit.applied_to_order == target_order
        # Credit still has remaining balance, stays AVAILABLE
        assert credit.status == Credit.Status.AVAILABLE
        assert credit.remaining_amount == Decimal("70.00")

    def test_existing_partial_payment_plus_credit_completes_order(self, conference, user):
        """Order with existing partial Stripe payment is completed by credit."""
        target_order = _make_order(
            conference=conference,
            user=user,
            status=Order.Status.PENDING,
            total=Decimal("100.00"),
        )
        Payment.objects.create(
            order=target_order,
            method=Payment.Method.STRIPE,
            status=Payment.Status.SUCCEEDED,
            amount=Decimal("60.00"),
        )

        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("50.00"),
            status=Credit.Status.AVAILABLE,
        )

        payment = RefundService.apply_credit_as_refund(credit, target_order)

        # Only $40 remaining on the order, so only $40 of the $50 credit is used
        assert payment.amount == Decimal("40.00")

        credit.refresh_from_db()
        assert credit.remaining_amount == Decimal("10.00")
        assert credit.status == Credit.Status.AVAILABLE

        target_order.refresh_from_db()
        assert target_order.status == Order.Status.PAID
