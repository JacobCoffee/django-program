"""Coverage-focused tests for django_program.sponsors.services."""

import datetime
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model

from django_program.conference.models import Conference
from django_program.registration.models import AddOn, TicketType, Voucher
from django_program.sponsors.models import BulkPurchase, BulkPurchaseVoucher, Sponsor, SponsorLevel
from django_program.sponsors.services import (
    BulkPurchaseError,
    BulkPurchaseService,
    _parse_datetime,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conference() -> Conference:
    return Conference.objects.create(
        name="ServiceCon",
        slug="servicecon",
        start_date=date(2027, 6, 1),
        end_date=date(2027, 6, 3),
        timezone="UTC",
        stripe_secret_key="sk_test_abc123",
    )


@pytest.fixture
def level(conference: Conference) -> SponsorLevel:
    return SponsorLevel.objects.create(
        conference=conference,
        name="Gold",
        cost=Decimal("5000.00"),
    )


@pytest.fixture
def sponsor(conference: Conference, level: SponsorLevel) -> Sponsor:
    return Sponsor.objects.create(
        conference=conference,
        level=level,
        name="Acme Corp",
    )


@pytest.fixture
def ticket_type(conference: Conference) -> TicketType:
    return TicketType.objects.create(
        conference=conference,
        name="Regular",
        slug="regular",
        price=Decimal("349.00"),
        bulk_enabled=True,
    )


@pytest.fixture
def addon(conference: Conference) -> AddOn:
    return AddOn.objects.create(
        conference=conference,
        name="T-Shirt",
        slug="tshirt",
        price=Decimal("35.00"),
        bulk_enabled=True,
    )


@pytest.fixture
def user() -> object:
    return User.objects.create_user(
        username="requester",
        email="requester@example.com",
        password="testpass123",
    )


def make_bp(conference, sponsor, **overrides) -> BulkPurchase:
    defaults: dict[str, object] = {
        "conference": conference,
        "sponsor": sponsor,
        "quantity": 3,
        "unit_price": Decimal("100.00"),
        "total_amount": Decimal("300.00"),
        "payment_status": BulkPurchase.PaymentStatus.PENDING,
        "voucher_config": {},
    }
    defaults.update(overrides)
    return BulkPurchase.objects.create(**defaults)


# ---------------------------------------------------------------------------
# _parse_datetime (lines 45-51)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestParseDatetime:
    def test_none_returns_none(self):
        assert _parse_datetime(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_datetime("") is None

    def test_datetime_instance_passthrough(self):
        dt = datetime.datetime(2027, 6, 1, 12, 0, tzinfo=datetime.UTC)
        assert _parse_datetime(dt) is dt

    def test_iso_string_is_parsed(self):
        result = _parse_datetime("2027-06-01T12:00:00+00:00")
        assert result == datetime.datetime(2027, 6, 1, 12, 0, tzinfo=datetime.UTC)

    def test_unsupported_type_returns_none(self):
        assert _parse_datetime(12345) is None


# ---------------------------------------------------------------------------
# create_bulk_purchase (lines 94-122)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCreateBulkPurchase:
    def test_quantity_below_one_raises(self, sponsor):
        with pytest.raises(BulkPurchaseError, match="Quantity must be at least 1"):
            BulkPurchaseService.create_bulk_purchase(
                sponsor=sponsor,
                quantity=0,
                ticket_type=None,
                unit_price=Decimal("10.00"),
            )

    def test_negative_unit_price_raises(self, sponsor):
        with pytest.raises(BulkPurchaseError, match="Unit price cannot be negative"):
            BulkPurchaseService.create_bulk_purchase(
                sponsor=sponsor,
                quantity=5,
                ticket_type=None,
                unit_price=Decimal("-1.00"),
            )

    def test_creates_pending_purchase_with_ticket_type(self, sponsor, ticket_type, user):
        bp = BulkPurchaseService.create_bulk_purchase(
            sponsor=sponsor,
            quantity=4,
            ticket_type=ticket_type,
            unit_price=Decimal("50.00"),
            requested_by=user,
            voucher_config={"voucher_type": "comp"},
        )
        assert bp.pk is not None
        assert bp.payment_status == BulkPurchase.PaymentStatus.PENDING
        assert bp.total_amount == Decimal("200.00")
        assert bp.product_description == "4x Regular voucher codes"
        assert bp.requested_by == user
        assert bp.voucher_config == {"voucher_type": "comp"}

    def test_creates_purchase_without_ticket_type(self, sponsor):
        bp = BulkPurchaseService.create_bulk_purchase(
            sponsor=sponsor,
            quantity=2,
            ticket_type=None,
            unit_price=Decimal("25.00"),
            voucher_config={"voucher_type": "comp"},
        )
        assert bp.product_description == ""
        assert bp.voucher_config == {"voucher_type": "comp"}


# ---------------------------------------------------------------------------
# create_checkout_session (lines 149-211)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCreateCheckoutSession:
    def test_raises_when_not_pending(self, conference, sponsor):
        bp = make_bp(conference, sponsor, payment_status=BulkPurchase.PaymentStatus.PAID)
        with pytest.raises(BulkPurchaseError, match="Cannot create checkout"):
            BulkPurchaseService.create_checkout_session(bp, "https://ok", "https://cancel")

    def test_raises_for_zero_total(self, conference, sponsor):
        bp = make_bp(conference, sponsor, total_amount=Decimal("0.00"), unit_price=Decimal("0.00"))
        with pytest.raises(BulkPurchaseError, match="zero-amount"):
            BulkPurchaseService.create_checkout_session(bp, "https://ok", "https://cancel")

    @patch("django_program.sponsors.services.StripeClient")
    def test_creates_session_and_updates_purchase(self, mock_stripe_cls, conference, sponsor, ticket_type):
        bp = make_bp(
            conference,
            sponsor,
            ticket_type=ticket_type,
            product_description="3x Regular voucher codes",
        )
        mock_client = MagicMock()
        mock_stripe_cls.return_value = mock_client
        mock_session = MagicMock()
        mock_session.id = "cs_test_123"
        mock_session.url = "https://checkout.stripe.com/pay/cs_test_123"
        mock_client.client.v1.checkout.sessions.create.return_value = mock_session

        url = BulkPurchaseService.create_checkout_session(bp, "https://success", "https://cancel")

        assert url == "https://checkout.stripe.com/pay/cs_test_123"
        mock_stripe_cls.assert_called_once_with(conference)
        bp.refresh_from_db()
        assert bp.stripe_checkout_session_id == "cs_test_123"
        assert bp.payment_status == BulkPurchase.PaymentStatus.PROCESSING

    @patch("django_program.sponsors.services.StripeClient")
    def test_uses_default_description_when_blank(self, mock_stripe_cls, conference, sponsor):
        bp = make_bp(conference, sponsor, product_description="")
        mock_client = MagicMock()
        mock_stripe_cls.return_value = mock_client
        mock_session = MagicMock()
        mock_session.id = "cs_test_456"
        mock_session.url = "https://checkout.stripe.com/pay/cs_test_456"
        mock_client.client.v1.checkout.sessions.create.return_value = mock_session

        BulkPurchaseService.create_checkout_session(bp, "https://success", "https://cancel")

        call_kwargs = mock_client.client.v1.checkout.sessions.create.call_args.kwargs
        product_name = call_kwargs["params"]["line_items"][0]["price_data"]["product_data"]["name"]
        assert product_name == "Bulk voucher purchase (3 codes)"


# ---------------------------------------------------------------------------
# fulfill_bulk_purchase (lines 234-312)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFulfillBulkPurchase:
    def test_already_fulfilled_returns_empty_list(self, conference, sponsor):
        bp = make_bp(
            conference,
            sponsor,
            quantity=1,
            payment_status=BulkPurchase.PaymentStatus.PAID,
            voucher_config={"voucher_type": "comp", "discount_value": 100},
        )
        voucher = Voucher.objects.create(conference=conference, code="EXIST1", voucher_type="comp")
        BulkPurchaseVoucher.objects.create(bulk_purchase=bp, voucher=voucher)

        result = BulkPurchaseService.fulfill_bulk_purchase(bp)
        assert result == []

    def test_raises_for_disallowed_state(self, conference, sponsor):
        bp = make_bp(conference, sponsor, payment_status=BulkPurchase.PaymentStatus.PENDING)
        with pytest.raises(BulkPurchaseError, match="Cannot fulfill"):
            BulkPurchaseService.fulfill_bulk_purchase(bp)

    def test_raises_for_approved_with_nonzero_total(self, conference, sponsor):
        bp = make_bp(
            conference,
            sponsor,
            payment_status=BulkPurchase.PaymentStatus.APPROVED,
            total_amount=Decimal("300.00"),
        )
        with pytest.raises(BulkPurchaseError, match="payment must be completed"):
            BulkPurchaseService.fulfill_bulk_purchase(bp)

    def test_raises_for_missing_voucher_config(self, conference, sponsor):
        bp = make_bp(
            conference,
            sponsor,
            payment_status=BulkPurchase.PaymentStatus.PAID,
            voucher_config={},
        )
        with pytest.raises(BulkPurchaseError, match="voucher_config is missing"):
            BulkPurchaseService.fulfill_bulk_purchase(bp)

    def test_fulfills_comp_from_approved_zero_total(self, conference, sponsor, ticket_type, addon):
        bp = make_bp(
            conference,
            sponsor,
            quantity=2,
            total_amount=Decimal("0.00"),
            unit_price=Decimal("0.00"),
            ticket_type=ticket_type,
            addon=addon,
            payment_status=BulkPurchase.PaymentStatus.APPROVED,
            voucher_config={
                "voucher_type": "comp",
                "discount_value": 100,
                "max_uses": 2,
                "prefix": "ACME-",
                "valid_from": "2027-06-01T00:00:00+00:00",
                "valid_until": "2027-06-03T00:00:00+00:00",
                "unlocks_hidden_tickets": True,
            },
        )

        vouchers = BulkPurchaseService.fulfill_bulk_purchase(bp)

        assert len(vouchers) == 2
        for v in vouchers:
            assert v.code.startswith("ACME-")
            assert v.max_uses == 2
            assert v.unlocks_hidden_tickets is True

        bp.refresh_from_db()
        assert bp.payment_status == BulkPurchase.PaymentStatus.PAID
        assert BulkPurchaseVoucher.objects.filter(bulk_purchase=bp).count() == 2

    def test_fulfills_without_sponsor_or_ticket_addon(self, conference):
        bp = BulkPurchase.objects.create(
            conference=conference,
            sponsor=None,
            quantity=1,
            unit_price=Decimal("10.00"),
            total_amount=Decimal("10.00"),
            payment_status=BulkPurchase.PaymentStatus.PAID,
            voucher_config={"voucher_type": "comp", "discount_value": 100},
        )

        vouchers = BulkPurchaseService.fulfill_bulk_purchase(bp)

        assert len(vouchers) == 1
        assert vouchers[0].code.startswith("BULK-")


# ---------------------------------------------------------------------------
# handle_checkout_webhook (lines 329-363)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestHandleCheckoutWebhook:
    def test_returns_none_when_no_matching_purchase(self):
        result = BulkPurchaseService.handle_checkout_webhook("cs_does_not_exist")
        assert result is None

    def test_returns_existing_when_already_fulfilled(self, conference, sponsor):
        bp = make_bp(
            conference,
            sponsor,
            quantity=1,
            payment_status=BulkPurchase.PaymentStatus.PAID,
            stripe_checkout_session_id="cs_already_done",
        )
        voucher = Voucher.objects.create(conference=conference, code="WEBHOOKDONE", voucher_type="comp")
        BulkPurchaseVoucher.objects.create(bulk_purchase=bp, voucher=voucher)
        result = BulkPurchaseService.handle_checkout_webhook("cs_already_done")
        assert result == bp

    def test_marks_failed_on_fulfillment_error(self, conference, sponsor):
        bp = make_bp(
            conference,
            sponsor,
            payment_status=BulkPurchase.PaymentStatus.PROCESSING,
            stripe_checkout_session_id="cs_bad_config",
            voucher_config={},
        )
        result = BulkPurchaseService.handle_checkout_webhook("cs_bad_config")
        assert result is None
        bp.refresh_from_db()
        assert bp.payment_status == BulkPurchase.PaymentStatus.FAILED

    def test_fulfills_and_returns_purchase(self, conference, sponsor):
        bp = make_bp(
            conference,
            sponsor,
            quantity=1,
            payment_status=BulkPurchase.PaymentStatus.PROCESSING,
            stripe_checkout_session_id="cs_good",
            voucher_config={"voucher_type": "comp", "discount_value": 100},
        )
        result = BulkPurchaseService.handle_checkout_webhook("cs_good")
        assert result is not None
        assert result.payment_status == BulkPurchase.PaymentStatus.PAID


# ---------------------------------------------------------------------------
# refund_bulk_purchase (lines 377-391)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRefundBulkPurchase:
    def test_refunds_and_deactivates_vouchers(self, conference, sponsor):
        bp = make_bp(conference, sponsor, payment_status=BulkPurchase.PaymentStatus.PAID)
        voucher = Voucher.objects.create(conference=conference, code="REFUND1", voucher_type="comp", is_active=True)
        BulkPurchaseVoucher.objects.create(bulk_purchase=bp, voucher=voucher)

        BulkPurchaseService.refund_bulk_purchase(bp)

        bp.refresh_from_db()
        voucher.refresh_from_db()
        assert bp.payment_status == BulkPurchase.PaymentStatus.REFUNDED
        assert voucher.is_active is False

    def test_refund_with_no_vouchers(self, conference, sponsor):
        bp = make_bp(conference, sponsor, payment_status=BulkPurchase.PaymentStatus.PAID)

        BulkPurchaseService.refund_bulk_purchase(bp)

        bp.refresh_from_db()
        assert bp.payment_status == BulkPurchase.PaymentStatus.REFUNDED


# ---------------------------------------------------------------------------
# mark_failed (lines 404-419)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMarkFailed:
    def test_marks_pending_as_failed(self, conference, sponsor):
        bp = make_bp(conference, sponsor, payment_status=BulkPurchase.PaymentStatus.PENDING)

        BulkPurchaseService.mark_failed(bp)

        bp.refresh_from_db()
        assert bp.payment_status == BulkPurchase.PaymentStatus.FAILED

    def test_skips_already_paid_purchase(self, conference, sponsor):
        bp = make_bp(conference, sponsor, payment_status=BulkPurchase.PaymentStatus.PAID)

        BulkPurchaseService.mark_failed(bp)

        bp.refresh_from_db()
        assert bp.payment_status == BulkPurchase.PaymentStatus.PAID
