"""Tests for Stripe Terminal POS payments and on-site registration views."""

import json
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

from django_program.conference.models import Conference
from django_program.registration.models import AddOn, Order, Payment, TicketType
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


def _make_order(*, conference: Conference, user: object, status: str = Order.Status.PAID) -> Order:
    return Order.objects.create(
        conference=conference,
        user=user,
        status=status,
        subtotal=Decimal("100.00"),
        total=Decimal("100.00"),
        reference=f"ORD-{uuid4().hex[:8].upper()}",
    )


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


def _make_attendee(*, conference: Conference, user: object, order: Order | None = None) -> object:
    from django_program.registration.attendee import Attendee

    return Attendee.objects.create(user=user, conference=conference, order=order)


# -- Model Tests --------------------------------------------------------------


@pytest.mark.unit
class TestTerminalPaymentModel:
    """Tests for the TerminalPayment model."""

    def test_terminal_payment_creation(self) -> None:
        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        payment = _make_payment(order=order)

        terminal_payment = TerminalPayment.objects.create(
            payment=payment,
            conference=conf,
            payment_intent_id=f"pi_{uuid4().hex[:16]}",
            terminal_id="tml_test123",
            reader_id="tmr_test456",
            card_brand="visa",
            card_last4="4242",
        )

        assert terminal_payment.pk is not None
        assert terminal_payment.payment == payment
        assert terminal_payment.conference == conf
        assert terminal_payment.terminal_id == "tml_test123"
        assert terminal_payment.reader_id == "tmr_test456"
        assert terminal_payment.card_brand == "visa"
        assert terminal_payment.card_last4 == "4242"
        assert terminal_payment.captured_at is None
        assert terminal_payment.cancelled_at is None

    def test_terminal_payment_str(self) -> None:
        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        payment = _make_payment(order=order)

        terminal_payment = TerminalPayment.objects.create(
            payment=payment,
            conference=conf,
            payment_intent_id="pi_abc123",
        )

        result = str(terminal_payment)
        assert "pi_abc123" in result
        assert "authorized" in result.lower()

    def test_terminal_payment_default_capture_status_is_authorized(self) -> None:
        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        payment = _make_payment(order=order)

        terminal_payment = TerminalPayment.objects.create(
            payment=payment,
            conference=conf,
            payment_intent_id="pi_defaultstatus",
        )

        assert terminal_payment.capture_status == TerminalPayment.CaptureStatus.AUTHORIZED

    def test_capture_status_choices_exist(self) -> None:
        assert TerminalPayment.CaptureStatus.AUTHORIZED == "authorized"
        assert TerminalPayment.CaptureStatus.CAPTURED == "captured"
        assert TerminalPayment.CaptureStatus.CANCELLED == "cancelled"
        assert TerminalPayment.CaptureStatus.FAILED == "failed"


@pytest.mark.unit
class TestPaymentMethodTerminal:
    """Tests for Payment.Method.TERMINAL."""

    def test_terminal_method_exists(self) -> None:
        assert Payment.Method.TERMINAL == "terminal"

    def test_terminal_payment_with_method(self) -> None:
        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        payment = _make_payment(order=order, method=Payment.Method.TERMINAL)

        assert payment.method == "terminal"
        assert payment.get_method_display() == "Terminal"


# -- View Tests: Terminal API Endpoints ----------------------------------------


@pytest.mark.integration
class TestConnectionTokenView:
    """Tests for the terminal connection token endpoint."""

    def _url(self, conference: Conference) -> str:
        return reverse("registration:terminal-connection-token", args=[conference.slug])

    def test_returns_401_for_anonymous(self) -> None:
        conf = _make_conference()
        client = Client()
        response = client.post(
            self._url(conf),
            content_type="application/json",
        )
        assert response.status_code == 401

    def test_returns_403_for_non_permitted_user(self) -> None:
        conf = _make_conference()
        user = _make_user(password="testpass123")
        client = Client()
        client.force_login(user)
        response = client.post(
            self._url(conf),
            content_type="application/json",
        )
        assert response.status_code == 403

    @patch("django_program.registration.views_terminal.StripeClient")
    def test_returns_connection_token(self, mock_client_cls: MagicMock) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        mock_client = MagicMock()
        mock_client.create_connection_token.return_value = "pst_test_secret_abc"
        mock_client_cls.return_value = mock_client

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["secret"] == "pst_test_secret_abc"


@pytest.mark.integration
class TestFetchAttendeeView:
    """Tests for the terminal attendee lookup endpoint."""

    def _url(self, conference: Conference, access_code: str) -> str:
        return reverse("registration:terminal-attendee", args=[conference.slug, access_code])

    def test_returns_attendee_data(self) -> None:
        conf = _make_conference()
        user = _make_user(first_name="Alice", last_name="Smith")
        order = _make_order(conference=conf, user=user)
        attendee = _make_attendee(conference=conf, user=user, order=order)
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.get(self._url(conf, attendee.access_code))

        assert response.status_code == 200
        data = response.json()
        assert data["attendee"]["access_code"] == str(attendee.access_code)

    def test_returns_404_for_unknown_code(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.get(self._url(conf, "NOTFOUND"))

        assert response.status_code == 404


@pytest.mark.integration
class TestFetchInventoryView:
    """Tests for the terminal inventory endpoint."""

    def _url(self, conference: Conference) -> str:
        return reverse("registration:terminal-inventory", args=[conference.slug])

    def test_returns_available_items(self) -> None:
        conf = _make_conference()
        _make_ticket_type(conference=conf, name="GA", slug="ga")
        _make_addon(conference=conf, name="Swag Bag", slug="swag-bag")
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.get(self._url(conf))

        assert response.status_code == 200
        data = response.json()
        assert "tickets" in data or "ticket_types" in data or "items" in data


@pytest.mark.integration
class TestListReadersView:
    """Tests for the terminal readers list endpoint."""

    def _url(self, conference: Conference) -> str:
        return reverse("registration:terminal-readers", args=[conference.slug])

    @patch("django_program.registration.views_terminal.StripeClient")
    def test_returns_readers(self, mock_client_cls: MagicMock) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        mock_reader = MagicMock()
        mock_reader.id = "tmr_abc123"
        mock_reader.label = "Front Desk Reader"
        mock_reader.status = "online"
        mock_reader.device_type = "bbpos_wisepos_e"
        mock_reader.location = "tml_location_1"
        mock_reader.serial_number = "SN12345"

        mock_client = MagicMock()
        mock_client.list_readers.return_value = [mock_reader]
        mock_client_cls.return_value = mock_client

        client = Client()
        client.force_login(staff)
        response = client.get(self._url(conf))

        assert response.status_code == 200
        data = response.json()
        assert "readers" in data


@pytest.mark.integration
class TestCreatePaymentIntentView:
    """Tests for the terminal create payment intent endpoint."""

    def _url(self, conference: Conference) -> str:
        return reverse("registration:terminal-create-intent", args=[conference.slug])

    @patch("django_program.registration.views_terminal.StripeClient")
    def test_creates_payment_intent(self, mock_client_cls: MagicMock) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        mock_intent = MagicMock()
        mock_intent.id = "pi_terminal_test_123"
        mock_intent.status = "requires_payment_method"
        mock_intent.client_secret = "pi_terminal_test_123_secret_abc"

        mock_reader_result = MagicMock()
        mock_reader_result.action = None

        mock_client = MagicMock()
        mock_client.create_terminal_payment_intent.return_value = mock_intent
        mock_client.process_terminal_payment.return_value = mock_reader_result
        mock_client_cls.return_value = mock_client

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"amount": "100.00", "currency": "usd", "reader_id": "tmr_test123"}),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["payment_intent_id"] == "pi_terminal_test_123"
        assert data["status"] == "processing"


@pytest.mark.integration
class TestCapturePaymentView:
    """Tests for the terminal capture payment endpoint."""

    def _url(self, conference: Conference) -> str:
        return reverse("registration:terminal-capture", args=[conference.slug])

    @patch("django_program.registration.views_terminal.StripeClient")
    def test_captures_payment(self, mock_client_cls: MagicMock) -> None:
        conf = _make_conference()
        staff = _make_staff_user()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        payment = _make_payment(order=order)
        TerminalPayment.objects.create(
            payment=payment,
            conference=conf,
            payment_intent_id="pi_to_capture",
            capture_status=TerminalPayment.CaptureStatus.AUTHORIZED,
        )

        mock_intent = MagicMock()
        mock_intent.id = "pi_to_capture"
        mock_intent.status = "succeeded"

        mock_client = MagicMock()
        mock_client.capture_payment_intent.return_value = mock_intent
        mock_client_cls.return_value = mock_client

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"payment_intent_id": "pi_to_capture"}),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "captured"


@pytest.mark.integration
class TestCancelPaymentView:
    """Tests for the terminal cancel payment endpoint."""

    def _url(self, conference: Conference) -> str:
        return reverse("registration:terminal-cancel", args=[conference.slug])

    @patch("django_program.registration.views_terminal.StripeClient")
    def test_cancels_payment(self, mock_client_cls: MagicMock) -> None:
        conf = _make_conference()
        staff = _make_staff_user()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        payment = _make_payment(order=order)
        TerminalPayment.objects.create(
            payment=payment,
            conference=conf,
            payment_intent_id="pi_to_cancel",
            capture_status=TerminalPayment.CaptureStatus.AUTHORIZED,
        )

        mock_intent = MagicMock()
        mock_intent.id = "pi_to_cancel"
        mock_intent.status = "canceled"

        mock_client = MagicMock()
        mock_client.cancel_payment_intent.return_value = mock_intent
        mock_client_cls.return_value = mock_client

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"payment_intent_id": "pi_to_cancel"}),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cancelled"


@pytest.mark.integration
class TestCartOperationsView:
    """Tests for the terminal cart operations endpoint."""

    def _url(self, conference: Conference) -> str:
        return reverse("registration:terminal-cart", args=[conference.slug])

    @patch("django_program.registration.views_terminal.StripeClient")
    def test_create_cart(self, mock_client_cls: MagicMock) -> None:
        conf = _make_conference()
        ticket = _make_ticket_type(conference=conf, name="Day Pass", slug="day-pass")
        staff = _make_staff_user()

        mock_client_cls.return_value = MagicMock()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps(
                {
                    "action": "update",
                    "items": [{"ticket_type_id": ticket.pk, "quantity": 1}],
                }
            ),
            content_type="application/json",
        )

        assert response.status_code in (200, 201)

    @patch("django_program.registration.views_terminal.StripeClient")
    def test_cart_checkout(self, mock_client_cls: MagicMock) -> None:
        conf = _make_conference()
        ticket = _make_ticket_type(conference=conf, name="Day Pass", slug="day-pass-co")
        staff = _make_staff_user()

        mock_client_cls.return_value = MagicMock()

        client = Client()
        client.force_login(staff)

        # First create a cart with items via the update action
        response = client.post(
            self._url(conf),
            data=json.dumps(
                {
                    "action": "update",
                    "items": [{"ticket_type_id": ticket.pk, "quantity": 1}],
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 200

        # Now checkout the cart
        response = client.post(
            self._url(conf),
            data=json.dumps(
                {
                    "action": "checkout",
                }
            ),
            content_type="application/json",
        )

        assert response.status_code in (200, 201)


# -- Manage View Tests: Terminal POS ------------------------------------------


@pytest.mark.integration
class TestTerminalPOSView:
    """Tests for the manage terminal POS page."""

    def _url(self, conference: Conference) -> str:
        return reverse("manage:terminal-pos", args=[conference.slug])

    def test_anonymous_redirected(self) -> None:
        conf = _make_conference()
        client = Client()
        response = client.get(self._url(conf))
        assert response.status_code == 302

    def test_non_permitted_user_denied(self) -> None:
        conf = _make_conference()
        user = _make_user(password="testpass123")
        client = Client()
        client.force_login(user)
        response = client.get(self._url(conf))
        assert response.status_code == 403

    def test_staff_with_permission_gets_200(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()
        client = Client()
        client.force_login(staff)
        response = client.get(self._url(conf))
        assert response.status_code == 200

    def test_context_has_active_nav(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()
        client = Client()
        client.force_login(staff)
        response = client.get(self._url(conf))
        assert response.context["active_nav"] == "terminal"
