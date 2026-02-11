"""Tests for Stripe webhook handling in django_program.registration.webhooks."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
import stripe as _stripe
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.utils import timezone

from django_program.conference.models import Conference
from django_program.registration.models import (
    EventProcessingException,
    Order,
    Payment,
    StripeEvent,
)
from django_program.registration.signals import order_paid
from django_program.registration.urls import app_name as registration_app_name
from django_program.registration.urls import urlpatterns as registration_urlpatterns
from django_program.registration.webhooks import (
    ChargeDisputeCreatedWebhook,
    ChargeRefundedWebhook,
    PaymentIntentPaymentFailedWebhook,
    PaymentIntentSucceededWebhook,
    Webhook,
    WebhookRegistry,
    _event_data_object,
    registry,
    stripe_webhook,
)

User = get_user_model()


# -- Fixtures -----------------------------------------------------------------


@pytest.fixture
def conference(db):
    return Conference.objects.create(
        name="TestCon",
        slug="testcon-wh",
        start_date="2027-06-01",
        end_date="2027-06-03",
        timezone="UTC",
        is_active=True,
        stripe_secret_key="sk_test_abc123",
        stripe_publishable_key="pk_test_xyz789",
        stripe_webhook_secret="whsec_test_secret",
    )


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="whuser",
        email="wh@example.com",
        password="testpass123",
    )


@pytest.fixture
def order(conference, user):
    return Order.objects.create(
        conference=conference,
        user=user,
        status=Order.Status.PENDING,
        subtotal=Decimal("100.00"),
        total=Decimal("100.00"),
        reference="ORD-WH001",
    )


@pytest.fixture
def paid_order(conference, user):
    return Order.objects.create(
        conference=conference,
        user=user,
        status=Order.Status.PAID,
        subtotal=Decimal("100.00"),
        total=Decimal("100.00"),
        reference="ORD-WH002",
    )


@pytest.fixture
def stripe_event(db):
    return StripeEvent.objects.create(
        stripe_id="evt_test_base_001",
        kind="test.event",
        livemode=False,
        payload={"data": {"object": {"id": "test_obj_001"}}},
    )


@pytest.fixture
def payment_intent_payload():
    """Return a valid payment_intent.succeeded payload structure."""
    return {
        "data": {
            "object": {
                "id": "pi_test_intent_001",
                "amount": 10000,
                "metadata": {"order_id": None},  # caller sets this
                "latest_charge": "ch_test_charge_001",
                "customer": "cus_test_123",
            },
        },
    }


@pytest.fixture
def request_factory():
    return RequestFactory()


# =============================================================================
# TestWebhookRegistry
# =============================================================================


@pytest.mark.unit
class TestWebhookRegistry:
    def test_register_and_get(self):
        reg = WebhookRegistry()

        class FakeHandler(Webhook):
            name = "fake.event"

        reg.register("fake.event", FakeHandler)
        assert reg.get("fake.event") is FakeHandler

    def test_get_missing_returns_none(self):
        reg = WebhookRegistry()
        assert reg.get("nonexistent.event") is None

    def test_keys_returns_registered_kinds(self):
        reg = WebhookRegistry()

        class HandlerA(Webhook):
            name = "kind.a"

        class HandlerB(Webhook):
            name = "kind.b"

        reg.register("kind.a", HandlerA)
        reg.register("kind.b", HandlerB)

        keys = reg.keys()
        assert "kind.a" in keys
        assert "kind.b" in keys
        assert len(keys) == 2

    def test_keys_empty_registry(self):
        reg = WebhookRegistry()
        assert reg.keys() == []

    def test_module_registry_has_expected_handlers(self):
        expected = {
            "payment_intent.succeeded",
            "payment_intent.payment_failed",
            "charge.refunded",
            "charge.dispute.created",
        }
        assert set(registry.keys()) == expected


# =============================================================================
# TestWebhookBaseProcess
# =============================================================================


@pytest.mark.unit
@pytest.mark.django_db
class TestWebhookBaseProcess:
    def test_already_processed_event_is_skipped(self, stripe_event):
        stripe_event.processed = True
        stripe_event.save(update_fields=["processed"])

        class TestHandler(Webhook):
            name = "test.handler"
            was_called = False

            def process_webhook(self):
                TestHandler.was_called = True

        handler = TestHandler(stripe_event)
        handler.process()

        assert not TestHandler.was_called

    def test_successful_processing_marks_event_processed(self, stripe_event):
        class TestHandler(Webhook):
            name = "test.handler"

            def process_webhook(self):
                pass

        handler = TestHandler(stripe_event)
        handler.process()

        stripe_event.refresh_from_db()
        assert stripe_event.processed is True

    def test_send_signal_called_after_process_webhook(self, stripe_event):
        call_order = []

        class TestHandler(Webhook):
            name = "test.handler"

            def process_webhook(self):
                call_order.append("process_webhook")

            def send_signal(self):
                call_order.append("send_signal")

        handler = TestHandler(stripe_event)
        handler.process()

        assert call_order == ["process_webhook", "send_signal"]

    def test_exception_creates_processing_exception_record(self, stripe_event):
        class FailingHandler(Webhook):
            name = "test.failing"

            def process_webhook(self):
                msg = "deliberate test failure"
                raise RuntimeError(msg)

        handler = FailingHandler(stripe_event)
        with pytest.raises(RuntimeError, match="deliberate test failure"):
            handler.process()

        assert EventProcessingException.objects.filter(event=stripe_event).count() == 1
        exc = EventProcessingException.objects.get(event=stripe_event)
        assert "deliberate test failure" in exc.traceback
        assert len(exc.message) <= 500

    def test_exception_does_not_mark_event_processed(self, stripe_event):
        class FailingHandler(Webhook):
            name = "test.failing"

            def process_webhook(self):
                msg = "fail"
                raise ValueError(msg)

        handler = FailingHandler(stripe_event)
        with pytest.raises(ValueError, match="fail"):
            handler.process()

        stripe_event.refresh_from_db()
        assert stripe_event.processed is False

    def test_base_process_webhook_raises_not_implemented(self, stripe_event):
        handler = Webhook(stripe_event)
        with pytest.raises(NotImplementedError):
            handler.process_webhook()

    def test_base_send_signal_is_noop(self, stripe_event):
        handler = Webhook(stripe_event)
        handler.send_signal()  # should not raise


# =============================================================================
# TestEventDataObject
# =============================================================================


@pytest.mark.unit
@pytest.mark.django_db
class TestEventDataObject:
    def test_valid_nested_payload(self, db):
        event = StripeEvent.objects.create(
            stripe_id="evt_data_obj_001",
            kind="test.event",
            payload={"data": {"object": {"id": "obj_123", "amount": 5000}}},
        )
        result = _event_data_object(event)
        assert result == {"id": "obj_123", "amount": 5000}

    def test_missing_data_key_returns_empty_dict(self, db):
        event = StripeEvent.objects.create(
            stripe_id="evt_data_obj_002",
            kind="test.event",
            payload={"other": "stuff"},
        )
        result = _event_data_object(event)
        assert result == {}

    def test_missing_object_key_returns_empty_dict(self, db):
        event = StripeEvent.objects.create(
            stripe_id="evt_data_obj_003",
            kind="test.event",
            payload={"data": {"not_object": True}},
        )
        result = _event_data_object(event)
        assert result == {}

    def test_non_dict_payload_returns_empty_dict(self, db):
        event = StripeEvent.objects.create(
            stripe_id="evt_data_obj_004",
            kind="test.event",
            payload="not a dict",
        )
        result = _event_data_object(event)
        assert result == {}

    def test_non_dict_data_returns_empty_dict(self, db):
        event = StripeEvent.objects.create(
            stripe_id="evt_data_obj_005",
            kind="test.event",
            payload={"data": "not a dict"},
        )
        result = _event_data_object(event)
        assert result == {}

    def test_non_dict_object_returns_empty_dict(self, db):
        event = StripeEvent.objects.create(
            stripe_id="evt_data_obj_006",
            kind="test.event",
            payload={"data": {"object": "string_not_dict"}},
        )
        result = _event_data_object(event)
        assert result == {}

    def test_empty_payload_returns_empty_dict(self, db):
        event = StripeEvent.objects.create(
            stripe_id="evt_data_obj_007",
            kind="test.event",
            payload={},
        )
        result = _event_data_object(event)
        assert result == {}


# =============================================================================
# TestPaymentIntentSucceededWebhook
# =============================================================================


@pytest.mark.unit
@pytest.mark.django_db
class TestPaymentIntentSucceededWebhook:
    def _make_event(self, order, intent_id="pi_test_001", amount=10000, latest_charge="ch_test_001"):
        payload = {
            "data": {
                "object": {
                    "id": intent_id,
                    "amount": amount,
                    "metadata": {"order_id": str(order.pk)},
                    "latest_charge": latest_charge,
                },
            },
        }
        return StripeEvent.objects.create(
            stripe_id=f"evt_pi_succ_{order.pk}_{intent_id}",
            kind="payment_intent.succeeded",
            payload=payload,
        )

    @patch("django_program.registration.webhooks.get_config")
    def test_updates_existing_pending_payment(self, mock_get_config, order):
        mock_config = MagicMock()
        mock_config.currency = "USD"
        mock_get_config.return_value = mock_config

        existing_payment = Payment.objects.create(
            order=order,
            method=Payment.Method.STRIPE,
            status=Payment.Status.PENDING,
            stripe_payment_intent_id="pi_test_001",
            amount=Decimal("0.00"),
        )

        event = self._make_event(order)
        handler = PaymentIntentSucceededWebhook(event)
        handler.process_webhook()

        existing_payment.refresh_from_db()
        assert existing_payment.status == Payment.Status.SUCCEEDED
        assert existing_payment.amount == Decimal(100)
        assert existing_payment.stripe_charge_id == "ch_test_001"
        assert Payment.objects.filter(order=order).count() == 1

    @patch("django_program.registration.webhooks.get_config")
    def test_creates_new_payment_when_no_pending_exists(self, mock_get_config, order):
        mock_config = MagicMock()
        mock_config.currency = "USD"
        mock_get_config.return_value = mock_config

        event = self._make_event(order)
        handler = PaymentIntentSucceededWebhook(event)
        handler.process_webhook()

        payment = Payment.objects.get(order=order)
        assert payment.method == Payment.Method.STRIPE
        assert payment.status == Payment.Status.SUCCEEDED
        assert payment.stripe_payment_intent_id == "pi_test_001"
        assert payment.amount == Decimal(100)
        assert payment.stripe_charge_id == "ch_test_001"

    @patch("django_program.registration.webhooks.get_config")
    def test_stores_latest_charge_on_existing_payment(self, mock_get_config, order):
        mock_config = MagicMock()
        mock_config.currency = "USD"
        mock_get_config.return_value = mock_config

        payment = Payment.objects.create(
            order=order,
            method=Payment.Method.STRIPE,
            status=Payment.Status.PENDING,
            stripe_payment_intent_id="pi_test_001",
            amount=Decimal("0.00"),
        )

        event = self._make_event(order, latest_charge="ch_charge_xyz")
        handler = PaymentIntentSucceededWebhook(event)
        handler.process_webhook()

        payment.refresh_from_db()
        assert payment.stripe_charge_id == "ch_charge_xyz"

    @patch("django_program.registration.webhooks.get_config")
    def test_creates_payment_without_latest_charge(self, mock_get_config, order):
        mock_config = MagicMock()
        mock_config.currency = "USD"
        mock_get_config.return_value = mock_config

        event = self._make_event(order, latest_charge=None)
        handler = PaymentIntentSucceededWebhook(event)
        handler.process_webhook()

        payment = Payment.objects.get(order=order)
        assert payment.stripe_charge_id == ""

    @patch("django_program.registration.webhooks.get_config")
    def test_marks_order_paid(self, mock_get_config, order):
        mock_config = MagicMock()
        mock_config.currency = "USD"
        mock_get_config.return_value = mock_config

        event = self._make_event(order)
        handler = PaymentIntentSucceededWebhook(event)
        handler.process_webhook()

        order.refresh_from_db()
        assert order.status == Order.Status.PAID

    @patch("django_program.registration.webhooks.get_config")
    def test_clears_hold_expires_at(self, mock_get_config, order):
        mock_config = MagicMock()
        mock_config.currency = "USD"
        mock_get_config.return_value = mock_config

        order.hold_expires_at = timezone.now()
        order.save(update_fields=["hold_expires_at"])

        event = self._make_event(order)
        handler = PaymentIntentSucceededWebhook(event)
        handler.process_webhook()

        order.refresh_from_db()
        assert order.hold_expires_at is None

    @patch("django_program.registration.webhooks.get_config")
    def test_send_signal_fires_order_paid(self, mock_get_config, order):
        mock_config = MagicMock()
        mock_config.currency = "USD"
        mock_get_config.return_value = mock_config

        event = self._make_event(order)
        handler = PaymentIntentSucceededWebhook(event)
        handler.process_webhook()

        signal_received = []

        def signal_handler(sender, order, user, **kwargs):
            signal_received.append((sender, order.pk, user.pk))

        order_paid.connect(signal_handler)
        try:
            handler.send_signal()
            assert len(signal_received) == 1
            assert signal_received[0][0] is Order
            assert signal_received[0][1] == order.pk
            assert signal_received[0][2] == order.user.pk
        finally:
            order_paid.disconnect(signal_handler)

    @patch("django_program.registration.webhooks.get_config")
    def test_updates_existing_payment_without_charge(self, mock_get_config, order):
        mock_config = MagicMock()
        mock_config.currency = "USD"
        mock_get_config.return_value = mock_config

        payment = Payment.objects.create(
            order=order,
            method=Payment.Method.STRIPE,
            status=Payment.Status.PENDING,
            stripe_payment_intent_id="pi_test_001",
            amount=Decimal("0.00"),
        )

        event = self._make_event(order, latest_charge=None)
        handler = PaymentIntentSucceededWebhook(event)
        handler.process_webhook()

        payment.refresh_from_db()
        assert payment.status == Payment.Status.SUCCEEDED
        assert payment.stripe_charge_id == ""


# =============================================================================
# TestPaymentIntentPaymentFailedWebhook
# =============================================================================


@pytest.mark.unit
@pytest.mark.django_db
class TestPaymentIntentPaymentFailedWebhook:
    def _make_event(self, order, intent_id="pi_fail_001", error=None):
        obj = {
            "id": intent_id,
            "metadata": {"order_id": str(order.pk)},
        }
        if error is not None:
            obj["last_payment_error"] = error
        return StripeEvent.objects.create(
            stripe_id=f"evt_pi_fail_{order.pk}_{intent_id}",
            kind="payment_intent.payment_failed",
            payload={"data": {"object": obj}},
        )

    def test_marks_pending_payment_failed(self, order):
        payment = Payment.objects.create(
            order=order,
            method=Payment.Method.STRIPE,
            status=Payment.Status.PENDING,
            stripe_payment_intent_id="pi_fail_001",
            amount=Decimal("100.00"),
        )

        event = self._make_event(order)
        handler = PaymentIntentPaymentFailedWebhook(event)
        handler.process_webhook()

        payment.refresh_from_db()
        assert payment.status == Payment.Status.FAILED

    def test_marks_processing_payment_failed(self, order):
        payment = Payment.objects.create(
            order=order,
            method=Payment.Method.STRIPE,
            status=Payment.Status.PROCESSING,
            stripe_payment_intent_id="pi_fail_001",
            amount=Decimal("100.00"),
        )

        event = self._make_event(order)
        handler = PaymentIntentPaymentFailedWebhook(event)
        handler.process_webhook()

        payment.refresh_from_db()
        assert payment.status == Payment.Status.FAILED

    def test_handles_missing_payment_gracefully(self, order):
        event = self._make_event(order)
        handler = PaymentIntentPaymentFailedWebhook(event)
        handler.process_webhook()  # should not raise

    def test_does_not_affect_succeeded_payment(self, order):
        payment = Payment.objects.create(
            order=order,
            method=Payment.Method.STRIPE,
            status=Payment.Status.SUCCEEDED,
            stripe_payment_intent_id="pi_fail_001",
            amount=Decimal("100.00"),
        )

        event = self._make_event(order)
        handler = PaymentIntentPaymentFailedWebhook(event)
        handler.process_webhook()

        payment.refresh_from_db()
        assert payment.status == Payment.Status.SUCCEEDED

    def test_parses_error_message(self, order):
        payment = Payment.objects.create(
            order=order,
            method=Payment.Method.STRIPE,
            status=Payment.Status.PENDING,
            stripe_payment_intent_id="pi_fail_001",
            amount=Decimal("100.00"),
        )

        error = {"message": "Your card was declined."}
        event = self._make_event(order, error=error)
        handler = PaymentIntentPaymentFailedWebhook(event)
        handler.process_webhook()

        payment.refresh_from_db()
        assert payment.status == Payment.Status.FAILED

    def test_handles_error_without_message_key(self, order):
        payment = Payment.objects.create(
            order=order,
            method=Payment.Method.STRIPE,
            status=Payment.Status.PENDING,
            stripe_payment_intent_id="pi_fail_001",
            amount=Decimal("100.00"),
        )

        error = {"code": "card_declined"}
        event = self._make_event(order, error=error)
        handler = PaymentIntentPaymentFailedWebhook(event)
        handler.process_webhook()

        payment.refresh_from_db()
        assert payment.status == Payment.Status.FAILED


# =============================================================================
# TestChargeRefundedWebhook
# =============================================================================


@pytest.mark.unit
@pytest.mark.django_db
class TestChargeRefundedWebhook:
    def _make_event(self, intent_id="pi_refund_001", amount=10000, amount_refunded=10000):
        payload = {
            "data": {
                "object": {
                    "payment_intent": intent_id,
                    "amount": amount,
                    "amount_refunded": amount_refunded,
                },
            },
        }
        return StripeEvent.objects.create(
            stripe_id=f"evt_ch_refund_{intent_id}_{amount_refunded}",
            kind="charge.refunded",
            payload=payload,
        )

    @patch("django_program.registration.webhooks.get_config")
    def test_full_refund(self, mock_get_config, order):
        mock_config = MagicMock()
        mock_config.currency = "USD"
        mock_get_config.return_value = mock_config

        payment = Payment.objects.create(
            order=order,
            method=Payment.Method.STRIPE,
            status=Payment.Status.SUCCEEDED,
            stripe_payment_intent_id="pi_refund_001",
            amount=Decimal("100.00"),
        )

        event = self._make_event(
            intent_id="pi_refund_001",
            amount=10000,
            amount_refunded=10000,
        )
        handler = ChargeRefundedWebhook(event)
        handler.process_webhook()

        payment.refresh_from_db()
        assert payment.status == Payment.Status.REFUNDED

        order.refresh_from_db()
        assert order.status == Order.Status.REFUNDED

    @patch("django_program.registration.webhooks.get_config")
    def test_partial_refund(self, mock_get_config, order):
        mock_config = MagicMock()
        mock_config.currency = "USD"
        mock_get_config.return_value = mock_config

        payment = Payment.objects.create(
            order=order,
            method=Payment.Method.STRIPE,
            status=Payment.Status.SUCCEEDED,
            stripe_payment_intent_id="pi_refund_001",
            amount=Decimal("100.00"),
        )

        event = self._make_event(
            intent_id="pi_refund_001",
            amount=10000,
            amount_refunded=5000,
        )
        handler = ChargeRefundedWebhook(event)
        handler.process_webhook()

        payment.refresh_from_db()
        assert payment.status == Payment.Status.SUCCEEDED  # not changed for partial

        order.refresh_from_db()
        assert order.status == Order.Status.PARTIALLY_REFUNDED

    @patch("django_program.registration.webhooks.get_config")
    def test_missing_payment_returns_early(self, mock_get_config, order):
        mock_config = MagicMock()
        mock_config.currency = "USD"
        mock_get_config.return_value = mock_config

        event = self._make_event(intent_id="pi_nonexistent")
        handler = ChargeRefundedWebhook(event)
        handler.process_webhook()  # should not raise

        order.refresh_from_db()
        assert order.status == Order.Status.PENDING

    @patch("django_program.registration.webhooks.get_config")
    def test_refund_equal_to_total_is_full_refund(self, mock_get_config, order):
        mock_config = MagicMock()
        mock_config.currency = "USD"
        mock_get_config.return_value = mock_config

        Payment.objects.create(
            order=order,
            method=Payment.Method.STRIPE,
            status=Payment.Status.SUCCEEDED,
            stripe_payment_intent_id="pi_refund_001",
            amount=Decimal("50.00"),
        )

        event = self._make_event(
            intent_id="pi_refund_001",
            amount=5000,
            amount_refunded=5000,
        )
        handler = ChargeRefundedWebhook(event)
        handler.process_webhook()

        order.refresh_from_db()
        assert order.status == Order.Status.REFUNDED


# =============================================================================
# TestChargeDisputeCreatedWebhook
# =============================================================================


@pytest.mark.unit
@pytest.mark.django_db
class TestChargeDisputeCreatedWebhook:
    def test_logs_dispute_without_error(self, db):
        payload = {
            "data": {
                "object": {
                    "id": "dp_test_001",
                    "charge": "ch_test_001",
                    "amount": 10000,
                    "reason": "fraudulent",
                },
            },
        }
        event = StripeEvent.objects.create(
            stripe_id="evt_dispute_001",
            kind="charge.dispute.created",
            payload=payload,
        )
        handler = ChargeDisputeCreatedWebhook(event)
        handler.process_webhook()  # should not raise

    def test_handles_empty_dispute_data(self, db):
        event = StripeEvent.objects.create(
            stripe_id="evt_dispute_002",
            kind="charge.dispute.created",
            payload={"data": {"object": {}}},
        )
        handler = ChargeDisputeCreatedWebhook(event)
        handler.process_webhook()  # should not raise

    def test_full_process_marks_event_processed(self, db):
        event = StripeEvent.objects.create(
            stripe_id="evt_dispute_003",
            kind="charge.dispute.created",
            payload={"data": {"object": {"id": "dp_test_003"}}},
        )
        handler = ChargeDisputeCreatedWebhook(event)
        handler.process()

        event.refresh_from_db()
        assert event.processed is True


# =============================================================================
# TestStripeWebhookView
# =============================================================================


@pytest.mark.unit
@pytest.mark.django_db
class TestStripeWebhookView:
    def _make_request(self, factory, body=b"{}", sig="t=123,v1=abc"):
        request = factory.post(
            "/webhook/",
            data=body,
            content_type="application/json",
        )
        request.META["HTTP_STRIPE_SIGNATURE"] = sig
        return request

    def _mock_event(
        self,
        event_id="evt_test_123",
        kind="payment_intent.succeeded",
        order_id="1",
        customer="cus_test_123",
    ):
        return {
            "id": event_id,
            "type": kind,
            "livemode": False,
            "data": {
                "object": {
                    "id": "pi_test_001",
                    "amount": 10000,
                    "metadata": {"order_id": order_id},
                    "customer": customer,
                },
            },
            "api_version": "2024-12-18.acacia",
        }

    def test_unknown_conference_returns_200(self, request_factory):
        request = self._make_request(request_factory)
        response = stripe_webhook(request, conference_slug="nonexistent-slug")
        assert response.status_code == 200

    def test_inactive_conference_returns_200(self, request_factory, db):
        Conference.objects.create(
            name="Inactive",
            slug="inactive-con",
            start_date="2027-06-01",
            end_date="2027-06-03",
            timezone="UTC",
            is_active=False,
            stripe_webhook_secret="whsec_test",
        )
        request = self._make_request(request_factory)
        response = stripe_webhook(request, conference_slug="inactive-con")
        assert response.status_code == 200

    def test_no_webhook_secret_returns_200(self, request_factory, db):
        Conference.objects.create(
            name="NoSecret",
            slug="nosecret-con",
            start_date="2027-06-01",
            end_date="2027-06-03",
            timezone="UTC",
            is_active=True,
            stripe_webhook_secret=None,
        )
        request = self._make_request(request_factory)
        response = stripe_webhook(request, conference_slug="nosecret-con")
        assert response.status_code == 200

    @patch("django_program.registration.webhooks.stripe.Webhook.construct_event")
    def test_duplicate_event_returns_200(self, mock_construct, request_factory, conference):
        StripeEvent.objects.create(
            stripe_id="evt_duplicate_001",
            kind="payment_intent.succeeded",
        )

        mock_construct.return_value = self._mock_event(event_id="evt_duplicate_001")

        request = self._make_request(request_factory)
        response = stripe_webhook(request, conference_slug="testcon-wh")
        assert response.status_code == 200
        assert StripeEvent.objects.filter(stripe_id="evt_duplicate_001").count() == 1

    @patch("django_program.registration.webhooks.stripe.Webhook.construct_event")
    def test_unregistered_event_kind_returns_200(self, mock_construct, request_factory, conference):
        mock_construct.return_value = self._mock_event(
            event_id="evt_unregistered_001",
            kind="some.unknown.event",
        )

        request = self._make_request(request_factory)
        response = stripe_webhook(request, conference_slug="testcon-wh")
        assert response.status_code == 200
        assert StripeEvent.objects.filter(stripe_id="evt_unregistered_001").exists()

    @patch("django_program.registration.webhooks.stripe.Webhook.construct_event")
    @patch("django_program.registration.webhooks.get_config")
    def test_successful_dispatch_returns_200(self, mock_get_config, mock_construct, request_factory, conference, order):
        mock_config = MagicMock()
        mock_config.currency = "USD"
        mock_config.stripe.webhook_tolerance = 300
        mock_get_config.return_value = mock_config

        mock_construct.return_value = self._mock_event(
            event_id="evt_success_001",
            kind="payment_intent.succeeded",
            order_id=str(order.pk),
        )

        request = self._make_request(request_factory)
        response = stripe_webhook(request, conference_slug="testcon-wh")
        assert response.status_code == 200

        stripe_event = StripeEvent.objects.get(stripe_id="evt_success_001")
        assert stripe_event.processed is True

        order.refresh_from_db()
        assert order.status == Order.Status.PAID

    @patch("django_program.registration.webhooks.stripe.Webhook.construct_event")
    def test_handler_exception_still_returns_200(self, mock_construct, request_factory, conference):
        mock_construct.return_value = self._mock_event(
            event_id="evt_error_001",
            kind="payment_intent.succeeded",
            order_id="99999999",  # nonexistent order triggers exception
        )

        request = self._make_request(request_factory)
        response = stripe_webhook(request, conference_slug="testcon-wh")
        assert response.status_code == 200

    @patch("django_program.registration.webhooks.stripe.Webhook.construct_event")
    def test_creates_stripe_event_record(self, mock_construct, request_factory, conference):
        mock_construct.return_value = self._mock_event(
            event_id="evt_record_001",
            kind="charge.dispute.created",
            customer="cus_stored_123",
        )

        request = self._make_request(request_factory)
        stripe_webhook(request, conference_slug="testcon-wh")

        evt = StripeEvent.objects.get(stripe_id="evt_record_001")
        assert evt.kind == "charge.dispute.created"
        assert evt.livemode is False
        assert evt.customer_id == "cus_stored_123"
        assert evt.api_version == "2024-12-18.acacia"

    @patch("django_program.registration.webhooks.stripe.Webhook.construct_event")
    def test_customer_id_defaults_to_empty_string(self, mock_construct, request_factory, conference):
        event_dict = self._mock_event(event_id="evt_no_customer_001")
        event_dict["data"]["object"].pop("customer", None)
        mock_construct.return_value = event_dict

        request = self._make_request(request_factory)
        stripe_webhook(request, conference_slug="testcon-wh")

        evt = StripeEvent.objects.get(stripe_id="evt_no_customer_001")
        assert evt.customer_id == ""

    @patch("django_program.registration.webhooks.stripe.Webhook.construct_event")
    def test_construct_event_called_with_correct_args(self, mock_construct, request_factory, conference):
        mock_construct.return_value = self._mock_event(event_id="evt_args_001")

        body = b'{"test": "payload"}'
        request = self._make_request(request_factory, body=body, sig="t=999,v1=sig_value")
        stripe_webhook(request, conference_slug="testcon-wh")

        mock_construct.assert_called_once()
        call_args = mock_construct.call_args
        assert call_args[0][0] == body
        assert call_args[0][1] == "t=999,v1=sig_value"
        assert call_args[0][2] == str(conference.stripe_webhook_secret)

    @patch("django_program.registration.webhooks.stripe.Webhook.construct_event")
    def test_empty_signature_header_passed_through(self, mock_construct, request_factory, conference):
        mock_construct.return_value = self._mock_event(event_id="evt_nosig_001")

        request = request_factory.post("/webhook/", data=b"{}", content_type="application/json")
        # do not set HTTP_STRIPE_SIGNATURE
        stripe_webhook(request, conference_slug="testcon-wh")

        call_args = mock_construct.call_args
        assert call_args[0][1] == ""

    @patch("django_program.registration.webhooks.stripe.Webhook.construct_event")
    def test_invalid_signature_returns_200(self, mock_construct, request_factory, conference):
        mock_construct.side_effect = _stripe.SignatureVerificationError("bad sig", "sig_header")

        request = self._make_request(request_factory)
        response = stripe_webhook(request, conference_slug="testcon-wh")
        assert response.status_code == 200
        assert StripeEvent.objects.count() == 0

    @patch("django_program.registration.webhooks.stripe.Webhook.construct_event")
    def test_invalid_payload_returns_200(self, mock_construct, request_factory, conference):
        mock_construct.side_effect = ValueError("bad payload")

        request = self._make_request(request_factory)
        response = stripe_webhook(request, conference_slug="testcon-wh")
        assert response.status_code == 200
        assert StripeEvent.objects.count() == 0


# ---------------------------------------------------------------------------
# URL conf coverage
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUrlConf:
    def test_urls_importable(self):
        assert registration_app_name == "registration"
        assert len(registration_urlpatterns) >= 1
