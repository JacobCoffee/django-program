"""Coverage backfill tests for django_program.registration.views_terminal.

Exercises error branches, exception handling, and secondary code paths
not covered by the existing ``tests/test_registration/test_terminal.py``.
"""

import json
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import stripe
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

from django_program.conference.models import Conference
from django_program.registration.attendee import Attendee
from django_program.registration.models import AddOn, Cart, CartItem, Order, Payment, TicketType
from django_program.registration.terminal import TerminalPayment

User = get_user_model()

pytestmark = pytest.mark.django_db


# -- Helpers ------------------------------------------------------------------


def _make_conference(**kwargs: object) -> Conference:
    defaults: dict[str, object] = {
        "name": "TestCon",
        "slug": f"testcon-{uuid4().hex[:6]}",
        "start_date": date(2026, 7, 1),
        "end_date": date(2026, 7, 5),
        "stripe_secret_key": "sk_test_fake123",
    }
    defaults.update(kwargs)
    return Conference.objects.create(**defaults)


def _make_user(**kwargs: object) -> object:
    defaults: dict[str, object] = {
        "username": f"user-{uuid4().hex[:8]}",
        "email": f"{uuid4().hex[:8]}@test.com",
    }
    defaults.update(kwargs)
    return User.objects.create_user(**defaults)


def _make_staff_user(**kwargs: object) -> object:
    """Create a staff user with the change_conference permission required by terminal API."""
    defaults: dict[str, object] = {
        "username": f"staff-{uuid4().hex[:8]}",
        "email": f"{uuid4().hex[:8]}@test.com",
        "is_staff": True,
        "password": "testpass123",
    }
    defaults.update(kwargs)
    user = User.objects.create_user(**defaults)
    perm = Permission.objects.get(content_type__app_label="program_conference", codename="change_conference")
    user.user_permissions.add(perm)
    return user


def _make_order(*, conference: Conference, user: object, status: str = Order.Status.PAID, **kwargs: object) -> Order:
    defaults: dict[str, object] = {
        "conference": conference,
        "user": user,
        "status": status,
        "subtotal": Decimal("100.00"),
        "total": Decimal("100.00"),
        "reference": f"ORD-{uuid4().hex[:8].upper()}",
    }
    defaults.update(kwargs)
    return Order.objects.create(**defaults)


def _make_payment(*, order: Order, method: str = Payment.Method.TERMINAL, **kwargs: object) -> Payment:
    defaults: dict[str, object] = {
        "order": order,
        "method": method,
        "amount": order.total,
        "stripe_payment_intent_id": f"pi_{uuid4().hex[:16]}",
    }
    defaults.update(kwargs)
    return Payment.objects.create(**defaults)


def _make_ticket_type(*, conference: Conference, **kwargs: object) -> TicketType:
    defaults: dict[str, object] = {
        "name": "General Admission",
        "slug": f"general-{uuid4().hex[:6]}",
        "price": Decimal("100.00"),
        "is_active": True,
    }
    defaults.update(kwargs)
    return TicketType.objects.create(conference=conference, **defaults)


def _make_addon(*, conference: Conference, **kwargs: object) -> AddOn:
    defaults: dict[str, object] = {
        "name": "Workshop",
        "slug": f"workshop-{uuid4().hex[:6]}",
        "price": Decimal("50.00"),
        "is_active": True,
    }
    defaults.update(kwargs)
    return AddOn.objects.create(conference=conference, **defaults)


def _make_attendee(*, conference: Conference, user: object, order: Order | None = None) -> Attendee:
    return Attendee.objects.create(user=user, conference=conference, order=order)


def _stripe_error() -> stripe.StripeError:
    return stripe.StripeError("something went wrong")


# =============================================================================
# ConnectionTokenView
# =============================================================================


@pytest.mark.integration
class TestConnectionTokenViewCoverage:
    def _url(self, conference: Conference) -> str:
        return reverse("registration:terminal-connection-token", args=[conference.slug])

    def test_returns_400_when_stripe_client_init_fails(self) -> None:
        conf = _make_conference(stripe_secret_key="")
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(self._url(conf), content_type="application/json")

        assert response.status_code == 400
        assert "error" in response.json()

    @patch("django_program.registration.views_terminal.StripeClient")
    def test_returns_502_on_stripe_error(self, mock_client_cls: MagicMock) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        mock_client = MagicMock()
        mock_client.create_connection_token.side_effect = _stripe_error()
        mock_client_cls.return_value = mock_client

        client = Client()
        client.force_login(staff)
        response = client.post(self._url(conf), content_type="application/json")

        assert response.status_code == 502
        assert "error" in response.json()


# =============================================================================
# CreatePaymentIntentView
# =============================================================================


@pytest.mark.integration
class TestCreatePaymentIntentViewCoverage:
    def _url(self, conference: Conference) -> str:
        return reverse("registration:terminal-create-intent", args=[conference.slug])

    def test_invalid_json_body(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(self._url(conf), data="not json", content_type="application/json")

        assert response.status_code == 400

    def test_json_body_not_an_object(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(self._url(conf), data=json.dumps([1, 2, 3]), content_type="application/json")

        assert response.status_code == 400

    def test_missing_reader_id(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"amount": "10.00"}),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "reader_id" in response.json()["error"]

    def test_missing_order_id_and_amount(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"reader_id": "tmr_1"}),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "order_id or amount" in response.json()["error"]

    def test_order_id_not_found(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"reader_id": "tmr_1", "order_id": 999999}),
            content_type="application/json",
        )

        assert response.status_code == 404

    def test_order_id_not_an_int(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"reader_id": "tmr_1", "order_id": "not-an-int"}),
            content_type="application/json",
        )

        assert response.status_code == 404

    def test_order_not_pending(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()
        user = _make_user()
        order = _make_order(conference=conf, user=user, status=Order.Status.PAID)

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"reader_id": "tmr_1", "order_id": order.pk}),
            content_type="application/json",
        )

        assert response.status_code == 409
        assert "not pending" in response.json()["error"]

    def test_order_already_fully_paid(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()
        user = _make_user()
        order = _make_order(
            conference=conf,
            user=user,
            status=Order.Status.PENDING,
            subtotal=Decimal("50.00"),
            total=Decimal("50.00"),
        )
        _make_payment(order=order, status=Payment.Status.SUCCEEDED, amount=Decimal("50.00"))

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"reader_id": "tmr_1", "order_id": order.pk}),
            content_type="application/json",
        )

        assert response.status_code == 409
        assert "fully paid" in response.json()["error"]

    @patch("django_program.registration.views_terminal.StripeClient")
    def test_order_id_with_remaining_balance_succeeds(self, mock_client_cls: MagicMock) -> None:
        conf = _make_conference()
        staff = _make_staff_user()
        user = _make_user()
        order = _make_order(
            conference=conf,
            user=user,
            status=Order.Status.PENDING,
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
        )

        mock_intent = MagicMock(id="pi_order_remaining", client_secret="secret_abc")
        mock_client = MagicMock()
        mock_client.create_terminal_payment_intent.return_value = mock_intent
        mock_client_cls.return_value = mock_client

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"reader_id": "tmr_1", "order_id": order.pk}),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["order_id"] == order.pk
        assert data["order_reference"] == str(order.reference)

    def test_amount_not_positive(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"reader_id": "tmr_1", "amount": "0"}),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "positive" in response.json()["error"]

    def test_amount_invalid(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"reader_id": "tmr_1", "amount": "not-a-number"}),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "Invalid amount" in response.json()["error"]

    def test_stripe_client_init_failure_returns_400(self) -> None:
        conf = _make_conference(stripe_secret_key="")
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"reader_id": "tmr_1", "amount": "10.00"}),
            content_type="application/json",
        )

        assert response.status_code == 400

    @patch("django_program.registration.views_terminal.StripeClient")
    def test_create_terminal_payment_intent_value_error(self, mock_client_cls: MagicMock) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        mock_client = MagicMock()
        mock_client.create_terminal_payment_intent.side_effect = ValueError("bad amount")
        mock_client_cls.return_value = mock_client

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"reader_id": "tmr_1", "amount": "10.00"}),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "Invalid payment amount" in response.json()["error"]

    @patch("django_program.registration.views_terminal.StripeClient")
    def test_create_terminal_payment_intent_stripe_error(self, mock_client_cls: MagicMock) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        mock_client = MagicMock()
        mock_client.create_terminal_payment_intent.side_effect = _stripe_error()
        mock_client_cls.return_value = mock_client

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"reader_id": "tmr_1", "amount": "10.00"}),
            content_type="application/json",
        )

        assert response.status_code == 502

    @patch("django_program.registration.views_terminal.StripeClient")
    def test_walkup_sale_with_valid_attendee_access_code(self, mock_client_cls: MagicMock) -> None:
        conf = _make_conference()
        staff = _make_staff_user()
        user = _make_user(first_name="Attendee", last_name="One")
        attendee = _make_attendee(conference=conf, user=user)

        mock_intent = MagicMock(id="pi_walkup_attendee", client_secret="secret_attendee")
        mock_client = MagicMock()
        mock_client.create_terminal_payment_intent.return_value = mock_intent
        mock_client_cls.return_value = mock_client

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps(
                {
                    "reader_id": "tmr_1",
                    "amount": "15.00",
                    "attendee_access_code": attendee.access_code,
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        order = Order.objects.get(pk=data["order_id"])
        assert order.user_id == user.pk

    @patch("django_program.registration.views_terminal.StripeClient")
    def test_walkup_sale_with_unknown_attendee_access_code(self, mock_client_cls: MagicMock) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        mock_intent = MagicMock(id="pi_walkup_unknown", client_secret="secret_unknown")
        mock_client = MagicMock()
        mock_client.create_terminal_payment_intent.return_value = mock_intent
        mock_client_cls.return_value = mock_client

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps(
                {
                    "reader_id": "tmr_1",
                    "amount": "15.00",
                    "attendee_access_code": "NOPE12345",
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 404
        assert "Attendee not found" in response.json()["error"]


# =============================================================================
# CapturePaymentView
# =============================================================================


@pytest.mark.integration
class TestCapturePaymentViewCoverage:
    def _url(self, conference: Conference) -> str:
        return reverse("registration:terminal-capture", args=[conference.slug])

    def test_invalid_json_body(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(self._url(conf), data="nope", content_type="application/json")

        assert response.status_code == 400

    def test_missing_payment_intent_id(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(self._url(conf), data=json.dumps({}), content_type="application/json")

        assert response.status_code == 400

    def test_terminal_payment_not_found(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"payment_intent_id": "pi_missing"}),
            content_type="application/json",
        )

        assert response.status_code == 404

    def test_stripe_client_init_failure(self) -> None:
        conf = _make_conference(stripe_secret_key="")
        staff = _make_staff_user()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        payment = _make_payment(order=order)
        TerminalPayment.objects.create(
            payment=payment,
            conference=conf,
            payment_intent_id="pi_no_key",
            capture_status=TerminalPayment.CaptureStatus.AUTHORIZED,
        )

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"payment_intent_id": "pi_no_key"}),
            content_type="application/json",
        )

        assert response.status_code == 400

    @patch("django_program.registration.views_terminal.StripeClient")
    def test_capture_stripe_error(self, mock_client_cls: MagicMock) -> None:
        conf = _make_conference()
        staff = _make_staff_user()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        payment = _make_payment(order=order)
        TerminalPayment.objects.create(
            payment=payment,
            conference=conf,
            payment_intent_id="pi_capture_err",
            capture_status=TerminalPayment.CaptureStatus.AUTHORIZED,
        )

        mock_client = MagicMock()
        mock_client.capture_payment_intent.side_effect = _stripe_error()
        mock_client_cls.return_value = mock_client

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"payment_intent_id": "pi_capture_err"}),
            content_type="application/json",
        )

        assert response.status_code == 502

    @patch("django_program.registration.views_terminal.StripeClient")
    def test_capture_marks_pending_order_paid(self, mock_client_cls: MagicMock) -> None:
        conf = _make_conference()
        staff = _make_staff_user()
        user = _make_user()
        order = _make_order(conference=conf, user=user, status=Order.Status.PENDING)
        payment = _make_payment(order=order)
        TerminalPayment.objects.create(
            payment=payment,
            conference=conf,
            payment_intent_id="pi_capture_pending",
            capture_status=TerminalPayment.CaptureStatus.AUTHORIZED,
        )

        mock_client = MagicMock()
        mock_client.capture_payment_intent.return_value = MagicMock(id="pi_capture_pending")
        mock_client_cls.return_value = mock_client

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"payment_intent_id": "pi_capture_pending"}),
            content_type="application/json",
        )

        assert response.status_code == 200
        order.refresh_from_db()
        assert order.status == Order.Status.PAID


# =============================================================================
# CancelPaymentView
# =============================================================================


@pytest.mark.integration
class TestCancelPaymentViewCoverage:
    def _url(self, conference: Conference) -> str:
        return reverse("registration:terminal-cancel", args=[conference.slug])

    def test_invalid_json_body(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(self._url(conf), data="nope", content_type="application/json")

        assert response.status_code == 400

    def test_missing_payment_intent_id(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(self._url(conf), data=json.dumps({}), content_type="application/json")

        assert response.status_code == 400

    def test_terminal_payment_not_found(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"payment_intent_id": "pi_missing_cancel"}),
            content_type="application/json",
        )

        assert response.status_code == 404

    def test_stripe_client_init_failure(self) -> None:
        conf = _make_conference(stripe_secret_key="")
        staff = _make_staff_user()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        payment = _make_payment(order=order)
        TerminalPayment.objects.create(
            payment=payment,
            conference=conf,
            payment_intent_id="pi_cancel_no_key",
            capture_status=TerminalPayment.CaptureStatus.AUTHORIZED,
        )

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"payment_intent_id": "pi_cancel_no_key"}),
            content_type="application/json",
        )

        assert response.status_code == 400

    @patch("django_program.registration.views_terminal.StripeClient")
    def test_cancel_with_reader_id_dispatches_cancel_reader_action(self, mock_client_cls: MagicMock) -> None:
        conf = _make_conference()
        staff = _make_staff_user()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        payment = _make_payment(order=order)
        TerminalPayment.objects.create(
            payment=payment,
            conference=conf,
            payment_intent_id="pi_cancel_reader",
            reader_id="tmr_reader_1",
            capture_status=TerminalPayment.CaptureStatus.AUTHORIZED,
        )

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"payment_intent_id": "pi_cancel_reader"}),
            content_type="application/json",
        )

        assert response.status_code == 200
        mock_client.cancel_reader_action.assert_called_once_with("tmr_reader_1")

    @patch("django_program.registration.views_terminal.StripeClient")
    def test_cancel_stripe_error(self, mock_client_cls: MagicMock) -> None:
        conf = _make_conference()
        staff = _make_staff_user()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        payment = _make_payment(order=order)
        TerminalPayment.objects.create(
            payment=payment,
            conference=conf,
            payment_intent_id="pi_cancel_err",
            reader_id="tmr_err",
            capture_status=TerminalPayment.CaptureStatus.AUTHORIZED,
        )

        mock_client = MagicMock()
        mock_client.cancel_reader_action.side_effect = _stripe_error()
        mock_client_cls.return_value = mock_client

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"payment_intent_id": "pi_cancel_err"}),
            content_type="application/json",
        )

        assert response.status_code == 502


# =============================================================================
# CartOperationsView
# =============================================================================


@pytest.mark.integration
class TestCartOperationsViewCoverage:
    def _url(self, conference: Conference) -> str:
        return reverse("registration:terminal-cart", args=[conference.slug])

    def test_invalid_json_body(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(self._url(conf), data="nope", content_type="application/json")

        assert response.status_code == 400

    def test_invalid_action(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"action": "destroy"}),
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_update_items_not_a_list(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"action": "update", "items": "not-a-list"}),
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_update_with_unknown_attendee_access_code(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps(
                {
                    "action": "update",
                    "attendee_access_code": "NOTFOUND99",
                    "items": [],
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 404

    def test_update_with_valid_attendee_access_code(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()
        user = _make_user()
        attendee = _make_attendee(conference=conf, user=user)
        ticket = _make_ticket_type(conference=conf)

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps(
                {
                    "action": "update",
                    "attendee_access_code": attendee.access_code,
                    "items": [{"ticket_type_id": ticket.pk, "quantity": 2}],
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 200
        cart = Cart.objects.get(user=user, conference=conf)
        assert cart.items.count() == 1

    def test_update_item_data_not_a_dict(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"action": "update", "items": ["not-a-dict"]}),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []

    def test_update_item_invalid_quantity(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()
        ticket = _make_ticket_type(conference=conf)

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps(
                {
                    "action": "update",
                    "items": [{"ticket_type_id": ticket.pk, "quantity": "not-a-number"}],
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "quantity" in response.json()["error"]

    def test_update_item_without_ticket_or_addon_id(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"action": "update", "items": [{"quantity": 1}]}),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []

    def test_update_item_with_unknown_ticket_type_id(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"action": "update", "items": [{"ticket_type_id": 9999999, "quantity": 1}]}),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []

    def test_update_item_with_addon_id_adds_addon(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()
        addon = _make_addon(conference=conf)

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"action": "update", "items": [{"addon_id": addon.pk, "quantity": 3}]}),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["addon_id"] == addon.pk
        assert data["items"][0]["quantity"] == 3
        assert data["total"] == str(addon.price * 3)

    def test_update_item_with_unknown_addon_id(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"action": "update", "items": [{"addon_id": 9999999, "quantity": 1}]}),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []

    def test_checkout_with_unknown_attendee_access_code(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"action": "checkout", "attendee_access_code": "NOTFOUND88"}),
            content_type="application/json",
        )

        assert response.status_code == 404

    def test_checkout_with_valid_attendee_access_code_but_no_cart(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()
        user = _make_user()
        attendee = _make_attendee(conference=conf, user=user)

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"action": "checkout", "attendee_access_code": attendee.access_code}),
            content_type="application/json",
        )

        assert response.status_code == 404
        assert "No open cart" in response.json()["error"]

    def test_checkout_no_open_cart(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"action": "checkout"}),
            content_type="application/json",
        )

        assert response.status_code == 404
        assert "No open cart" in response.json()["error"]

    def test_checkout_empty_cart(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()
        Cart.objects.create(user=staff, conference=conf, status=Cart.Status.OPEN)

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"action": "checkout"}),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "Cart is empty" in response.json()["error"]

    def test_checkout_success_with_billing_info(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()
        ticket = _make_ticket_type(conference=conf)
        cart = Cart.objects.create(user=staff, conference=conf, status=Cart.Status.OPEN)
        CartItem.objects.create(cart=cart, ticket_type=ticket, quantity=1)

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps(
                {
                    "action": "checkout",
                    "billing_name": "Jane Doe",
                    "billing_email": "jane@example.com",
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        order = Order.objects.get(pk=data["order_id"])
        assert order.billing_name == "Jane Doe"
        assert order.billing_email == "jane@example.com"
        cart.refresh_from_db()
        assert cart.status == Cart.Status.CHECKED_OUT


# =============================================================================
# ListReadersView
# =============================================================================


@pytest.mark.integration
class TestListReadersViewCoverage:
    def _url(self, conference: Conference) -> str:
        return reverse("registration:terminal-readers", args=[conference.slug])

    def test_stripe_client_init_failure_returns_400(self) -> None:
        conf = _make_conference(stripe_secret_key="")
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.get(self._url(conf))

        assert response.status_code == 400

    @patch("django_program.registration.views_terminal.StripeClient")
    def test_list_readers_stripe_error(self, mock_client_cls: MagicMock) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        mock_client = MagicMock()
        mock_client.list_readers.side_effect = _stripe_error()
        mock_client_cls.return_value = mock_client

        client = Client()
        client.force_login(staff)
        response = client.get(self._url(conf))

        assert response.status_code == 502
