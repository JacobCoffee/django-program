"""Tests for the StripeClient wrapper in django_program.registration.stripe_client."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model

from django_program.conference.models import Conference
from django_program.registration.models import Order, StripeCustomer
from django_program.registration.stripe_client import StripeClient
from django_program.settings import get_config

User = get_user_model()


# -- Fixtures -----------------------------------------------------------------


@pytest.fixture
def conference(db):
    return Conference.objects.create(
        name="TestCon",
        slug="testcon-stripe",
        start_date="2027-06-01",
        end_date="2027-06-03",
        timezone="UTC",
        stripe_secret_key="sk_test_abc123",
        stripe_publishable_key="pk_test_xyz789",
    )


@pytest.fixture
def conference_no_key(db):
    return Conference.objects.create(
        name="NoKeyCon",
        slug="nokeycon",
        start_date="2027-06-01",
        end_date="2027-06-03",
        timezone="UTC",
    )


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="stripeuser",
        email="stripeuser@example.com",
        password="testpass123",
    )


@pytest.fixture
def order(conference, user):
    return Order.objects.create(
        conference=conference,
        user=user,
        status=Order.Status.PENDING,
        subtotal=Decimal("10.00"),
        total=Decimal("10.00"),
        reference="ORD-ABCD1234",
    )


@pytest.fixture
def mock_stripe_client_cls():
    with patch("django_program.registration.stripe_client.stripe.StripeClient") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        yield mock_cls, mock_instance.v1


# =============================================================================
# TestInit
# =============================================================================


@pytest.mark.unit
class TestInit:
    def test_init_raises_on_missing_stripe_key(self, conference_no_key):
        with pytest.raises(ValueError, match="does not have a Stripe secret key"):
            StripeClient(conference_no_key)

    def test_init_with_valid_key(self, conference, mock_stripe_client_cls):
        mock_cls, _ = mock_stripe_client_cls

        client = StripeClient(conference)

        assert client.conference == conference
        mock_cls.assert_called_once_with(
            "sk_test_abc123",
            stripe_version=get_config().stripe.api_version,
        )


# =============================================================================
# TestGetOrCreateCustomer
# =============================================================================


@pytest.mark.unit
@pytest.mark.django_db
class TestGetOrCreateCustomer:
    def test_get_existing_customer(self, conference, user, mock_stripe_client_cls):
        _, mock_instance = mock_stripe_client_cls
        existing = StripeCustomer.objects.create(
            user=user,
            conference=conference,
            stripe_customer_id="cus_existing_123",
        )

        client = StripeClient(conference)
        result = client.get_or_create_customer(user)

        assert result.pk == existing.pk
        assert result.stripe_customer_id == "cus_existing_123"
        mock_instance.customers.create.assert_not_called()

    def test_create_new_customer(self, conference, user, mock_stripe_client_cls):
        _, mock_instance = mock_stripe_client_cls
        mock_instance.customers.create.return_value = MagicMock(id="cus_new_456")

        client = StripeClient(conference)
        result = client.get_or_create_customer(user)

        assert result.stripe_customer_id == "cus_new_456"
        assert result.user == user
        assert result.conference == conference
        mock_instance.customers.create.assert_called_once()

    def test_create_customer_handles_race_condition(self, conference, user, mock_stripe_client_cls):
        _, mock_instance = mock_stripe_client_cls
        mock_instance.customers.create.return_value = MagicMock(id="cus_race_loser")

        existing = StripeCustomer.objects.create(
            user=user,
            conference=conference,
            stripe_customer_id="cus_race_winner",
        )

        with patch.object(
            StripeCustomer.objects,
            "filter",
            return_value=StripeCustomer.objects.none(),
        ):
            client = StripeClient(conference)
            result = client.get_or_create_customer(user)

        assert result.pk == existing.pk
        assert result.stripe_customer_id == "cus_race_winner"

    def test_create_customer_stores_stripe_id(self, conference, user, mock_stripe_client_cls):
        _, mock_instance = mock_stripe_client_cls
        mock_instance.customers.create.return_value = MagicMock(id="cus_persisted_789")

        client = StripeClient(conference)
        client.get_or_create_customer(user)

        stored = StripeCustomer.objects.get(user=user, conference=conference)
        assert stored.stripe_customer_id == "cus_persisted_789"


# =============================================================================
# TestCreatePaymentIntent
# =============================================================================


@pytest.mark.unit
@pytest.mark.django_db
class TestCreatePaymentIntent:
    def test_create_payment_intent_returns_client_secret(self, conference, order, mock_stripe_client_cls):
        _, mock_instance = mock_stripe_client_cls
        mock_instance.payment_intents.create.return_value = MagicMock(client_secret="pi_secret_abc123")

        client = StripeClient(conference)
        secret = client.create_payment_intent(order, "cus_123")

        assert secret == "pi_secret_abc123"

    def test_create_payment_intent_converts_amount(self, conference, order, mock_stripe_client_cls):
        _, mock_instance = mock_stripe_client_cls
        mock_instance.payment_intents.create.return_value = MagicMock(client_secret="pi_secret_xyz")

        client = StripeClient(conference)
        client.create_payment_intent(order, "cus_123")

        call_kwargs = mock_instance.payment_intents.create.call_args
        params = call_kwargs.kwargs["params"]
        assert params["amount"] == 1000  # Decimal("10.00") -> 1000 cents

    def test_create_payment_intent_uses_order_reference_as_idempotency_key(
        self, conference, order, mock_stripe_client_cls
    ):
        _, mock_instance = mock_stripe_client_cls
        mock_instance.payment_intents.create.return_value = MagicMock(client_secret="pi_secret_idem")

        client = StripeClient(conference)
        client.create_payment_intent(order, "cus_123")

        call_kwargs = mock_instance.payment_intents.create.call_args
        options = call_kwargs.kwargs["options"]
        assert options["idempotency_key"] == "ORD-ABCD1234"


# =============================================================================
# TestCapturePaymentIntent
# =============================================================================


@pytest.mark.unit
class TestCapturePaymentIntent:
    def test_capture_payment_intent(self, conference, mock_stripe_client_cls):
        _, mock_instance = mock_stripe_client_cls
        mock_captured = MagicMock(id="pi_captured_001", status="succeeded")
        mock_instance.payment_intents.capture.return_value = mock_captured

        client = StripeClient(conference)
        result = client.capture_payment_intent("pi_captured_001")

        mock_instance.payment_intents.capture.assert_called_once_with("pi_captured_001")
        assert result.id == "pi_captured_001"


# =============================================================================
# TestCreateRefund
# =============================================================================


@pytest.mark.unit
class TestCreateRefund:
    def test_create_refund_without_amount(self, conference, mock_stripe_client_cls):
        _, mock_instance = mock_stripe_client_cls
        mock_refund = MagicMock(id="re_full_001")
        mock_instance.refunds.create.return_value = mock_refund

        client = StripeClient(conference)
        result = client.create_refund("pi_abc123")

        call_kwargs = mock_instance.refunds.create.call_args
        params = call_kwargs.kwargs["params"]
        assert params["payment_intent"] == "pi_abc123"
        assert params["reason"] == "requested_by_customer"
        assert "amount" not in params
        assert result.id == "re_full_001"

    def test_create_refund_with_amount(self, conference, mock_stripe_client_cls):
        _, mock_instance = mock_stripe_client_cls
        mock_refund = MagicMock(id="re_partial_002")
        mock_instance.refunds.create.return_value = mock_refund

        client = StripeClient(conference)
        result = client.create_refund("pi_abc123", amount=Decimal("5.50"))

        call_kwargs = mock_instance.refunds.create.call_args
        params = call_kwargs.kwargs["params"]
        assert params["amount"] == 550  # Decimal("5.50") -> 550 cents
        assert result.id == "re_partial_002"

    def test_create_refund_with_custom_reason(self, conference, mock_stripe_client_cls):
        _, mock_instance = mock_stripe_client_cls
        mock_instance.refunds.create.return_value = MagicMock(id="re_dup_003")

        client = StripeClient(conference)
        client.create_refund("pi_abc123", reason="duplicate")

        call_kwargs = mock_instance.refunds.create.call_args
        params = call_kwargs.kwargs["params"]
        assert params["reason"] == "duplicate"
