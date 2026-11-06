"""Coverage backfill tests for Terminal-related methods on StripeClient."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from django_program.conference.models import Conference
from django_program.registration.stripe_client import StripeClient

# -- Fixtures -----------------------------------------------------------------


@pytest.fixture
def conference(db):
    return Conference.objects.create(
        name="TestCon",
        slug="testcon-stripe-terminal",
        start_date="2027-06-01",
        end_date="2027-06-03",
        timezone="UTC",
        stripe_secret_key="sk_test_abc123",
        stripe_publishable_key="pk_test_xyz789",
    )


@pytest.fixture
def mock_stripe_client_cls():
    with patch("django_program.registration.stripe_client.stripe.StripeClient") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        yield mock_cls, mock_instance.v1


# =============================================================================
# TestCreateConnectionToken
# =============================================================================


@pytest.mark.unit
class TestCreateConnectionToken:
    def test_returns_token_secret(self, conference, mock_stripe_client_cls):
        _, mock_instance = mock_stripe_client_cls
        mock_token = MagicMock(secret="pst_test_secret_xyz")
        mock_instance.terminal.connection_tokens.create.return_value = mock_token

        client = StripeClient(conference)
        secret = client.create_connection_token()

        mock_instance.terminal.connection_tokens.create.assert_called_once_with()
        assert secret == "pst_test_secret_xyz"


# =============================================================================
# TestListReaders
# =============================================================================


@pytest.mark.unit
class TestListReaders:
    def test_list_readers_without_location(self, conference, mock_stripe_client_cls):
        _, mock_instance = mock_stripe_client_cls
        mock_reader = MagicMock(id="tmr_1")
        mock_instance.terminal.readers.list.return_value = MagicMock(data=[mock_reader])

        client = StripeClient(conference)
        readers = client.list_readers()

        call_kwargs = mock_instance.terminal.readers.list.call_args
        params = call_kwargs.kwargs["params"]
        assert params == {"limit": 100}
        assert readers == [mock_reader]

    def test_list_readers_with_location(self, conference, mock_stripe_client_cls):
        _, mock_instance = mock_stripe_client_cls
        mock_reader = MagicMock(id="tmr_2")
        mock_instance.terminal.readers.list.return_value = MagicMock(data=[mock_reader])

        client = StripeClient(conference)
        readers = client.list_readers(location="tml_location_1")

        call_kwargs = mock_instance.terminal.readers.list.call_args
        params = call_kwargs.kwargs["params"]
        assert params == {"limit": 100, "location": "tml_location_1"}
        assert readers == [mock_reader]


# =============================================================================
# TestCreateTerminalPaymentIntent
# =============================================================================


@pytest.mark.unit
class TestCreateTerminalPaymentIntent:
    def test_minimal_params(self, conference, mock_stripe_client_cls):
        _, mock_instance = mock_stripe_client_cls
        mock_intent = MagicMock(id="pi_terminal_min")
        mock_instance.payment_intents.create.return_value = mock_intent

        client = StripeClient(conference)
        result = client.create_terminal_payment_intent(amount=Decimal("10.00"), currency="usd")

        call_kwargs = mock_instance.payment_intents.create.call_args
        params = call_kwargs.kwargs["params"]
        assert params["amount"] == 1000
        assert params["currency"] == "usd"
        assert params["capture_method"] == "manual"
        assert params["payment_method_types"] == ["card_present"]
        assert "customer" not in params
        assert "metadata" not in params
        assert "description" not in params
        assert result.id == "pi_terminal_min"

    def test_full_params(self, conference, mock_stripe_client_cls):
        _, mock_instance = mock_stripe_client_cls
        mock_intent = MagicMock(id="pi_terminal_full")
        mock_instance.payment_intents.create.return_value = mock_intent

        client = StripeClient(conference)
        result = client.create_terminal_payment_intent(
            amount=Decimal("25.50"),
            currency="usd",
            customer_id="cus_abc123",
            metadata={"order_id": "42"},
            description="Terminal payment for TestCon",
        )

        call_kwargs = mock_instance.payment_intents.create.call_args
        params = call_kwargs.kwargs["params"]
        assert params["amount"] == 2550
        assert params["customer"] == "cus_abc123"
        assert params["metadata"] == {"order_id": "42"}
        assert params["description"] == "Terminal payment for TestCon"
        assert result.id == "pi_terminal_full"


# =============================================================================
# TestProcessTerminalPayment
# =============================================================================


@pytest.mark.unit
class TestProcessTerminalPayment:
    def test_dispatches_payment_intent_to_reader(self, conference, mock_stripe_client_cls):
        _, mock_instance = mock_stripe_client_cls
        mock_reader = MagicMock(id="tmr_proc")
        mock_instance.terminal.readers.process_payment_intent.return_value = mock_reader

        client = StripeClient(conference)
        result = client.process_terminal_payment(reader_id="tmr_proc", payment_intent_id="pi_abc")

        mock_instance.terminal.readers.process_payment_intent.assert_called_once_with(
            "tmr_proc",
            params={"payment_intent": "pi_abc"},
        )
        assert result is mock_reader


# =============================================================================
# TestCancelReaderAction
# =============================================================================


@pytest.mark.unit
class TestCancelReaderAction:
    def test_cancels_reader_action(self, conference, mock_stripe_client_cls):
        _, mock_instance = mock_stripe_client_cls
        mock_reader = MagicMock(id="tmr_cancel")
        mock_instance.terminal.readers.cancel_action.return_value = mock_reader

        client = StripeClient(conference)
        result = client.cancel_reader_action("tmr_cancel")

        mock_instance.terminal.readers.cancel_action.assert_called_once_with("tmr_cancel")
        assert result is mock_reader
