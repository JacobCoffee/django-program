"""Tests for Stripe invoicing integration with purchase orders."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model

from django_program.conference.models import Conference
from django_program.registration.models import TicketType
from django_program.registration.purchase_order import PurchaseOrder
from django_program.registration.services.purchase_orders import create_purchase_order
from django_program.registration.services.stripe_invoicing import (
    _get_stripe_client,
    create_stripe_invoice,
    handle_invoice_paid_webhook,
    sync_stripe_invoice_status,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conference(db) -> Conference:
    return Conference.objects.create(
        name="Stripe Inv Conf",
        slug="stripe-inv-conf",
        start_date=date(2027, 7, 1),
        end_date=date(2027, 7, 3),
        timezone="UTC",
        stripe_secret_key="sk_test_fake",
    )


@pytest.fixture
def staff_user(db) -> User:
    return User.objects.create_user(username="stripeinvstaff", email="stripeinv@test.com", password="testpass123")


@pytest.fixture
def ticket_type(conference) -> TicketType:
    return TicketType.objects.create(
        conference=conference,
        name="Corporate",
        slug="corporate-si",
        price=Decimal("200.00"),
        total_quantity=0,
        limit_per_user=10,
        is_active=True,
    )


@pytest.fixture
def purchase_order(conference, staff_user, ticket_type) -> PurchaseOrder:
    return create_purchase_order(
        conference=conference,
        organization_name="Stripe Test Org",
        contact_email="billing@stripe-test.com",
        contact_name="Stripe Person",
        billing_address="789 Pay St",
        line_items=[
            {
                "description": "Corporate Ticket",
                "quantity": 3,
                "unit_price": Decimal("200.00"),
                "ticket_type": ticket_type,
            },
        ],
        created_by=staff_user,
    )


def _mock_stripe_client() -> MagicMock:
    """Build a mock that satisfies the StripeClient -> client chain."""
    client = MagicMock()

    # customers.list returns empty (create new customer)
    customer_list = MagicMock()
    customer_list.data = []
    client.v1.customers.list.return_value = customer_list

    # customers.create returns an id
    customer_obj = MagicMock()
    customer_obj.id = "cus_test_123"
    client.v1.customers.create.return_value = customer_obj

    # invoices.create returns invoice stub
    invoice_obj = MagicMock()
    invoice_obj.id = "in_test_456"
    client.v1.invoices.create.return_value = invoice_obj

    # invoice_items.create is a no-op
    client.v1.invoice_items.create.return_value = MagicMock()

    # invoices.finalize_invoice returns finalized invoice
    finalized = MagicMock()
    finalized.id = "in_test_456"
    finalized.hosted_invoice_url = "https://invoice.stripe.com/i/test_hosted"
    client.v1.invoices.finalize_invoice.return_value = finalized

    # invoices.send_invoice is a no-op
    client.v1.invoices.send_invoice.return_value = MagicMock()

    return client


# ---------------------------------------------------------------------------
# create_stripe_invoice
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.django_db
class TestCreateStripeInvoice:
    def test_create_stripe_invoice(self, purchase_order) -> None:
        mock_client = _mock_stripe_client()
        with patch(
            "django_program.registration.services.stripe_invoicing._get_stripe_client",
            return_value=mock_client,
        ):
            hosted_url = create_stripe_invoice(purchase_order)

        assert hosted_url == "https://invoice.stripe.com/i/test_hosted"
        purchase_order.refresh_from_db()
        assert purchase_order.stripe_invoice_id == "in_test_456"
        assert purchase_order.stripe_invoice_url == "https://invoice.stripe.com/i/test_hosted"
        mock_client.v1.invoices.finalize_invoice.assert_called_once_with("in_test_456")
        mock_client.v1.invoices.send_invoice.assert_called_once()

    def test_get_stripe_client_returns_sdk_client(self, conference) -> None:
        with patch("django_program.registration.services.stripe_invoicing.StripeClient") as mock_sc_cls:
            mock_instance = MagicMock()
            mock_instance.client = MagicMock()
            mock_sc_cls.return_value = mock_instance

            result = _get_stripe_client(conference)

        mock_sc_cls.assert_called_once_with(conference)
        assert result is mock_instance.client

    def test_create_stripe_invoice_no_key(self, conference, staff_user) -> None:
        conference.stripe_secret_key = None
        conference.save(update_fields=["stripe_secret_key"])

        po = create_purchase_order(
            conference=conference,
            organization_name="No Key Org",
            contact_email="nokey@test.com",
            contact_name="No Key",
            line_items=[{"description": "Item", "quantity": 1, "unit_price": Decimal("100.00")}],
            created_by=staff_user,
        )

        with pytest.raises(ValueError, match=r"[Ss]tripe"):
            create_stripe_invoice(po)

    def test_create_stripe_invoice_existing_customer(self, purchase_order) -> None:
        mock_client = _mock_stripe_client()
        # Override: customer already exists
        existing_customer = MagicMock()
        existing_customer.id = "cus_existing"
        customer_list = MagicMock()
        customer_list.data = [existing_customer]
        mock_client.v1.customers.list.return_value = customer_list

        with patch(
            "django_program.registration.services.stripe_invoicing._get_stripe_client",
            return_value=mock_client,
        ):
            hosted_url = create_stripe_invoice(purchase_order)

        assert hosted_url == "https://invoice.stripe.com/i/test_hosted"
        mock_client.v1.customers.create.assert_not_called()

    def test_create_stripe_invoice_already_exists(self, purchase_order) -> None:
        purchase_order.stripe_invoice_id = "in_existing"
        purchase_order.save(update_fields=["stripe_invoice_id"])

        with pytest.raises(ValueError, match="already has a Stripe invoice"):
            create_stripe_invoice(purchase_order)


# ---------------------------------------------------------------------------
# sync_stripe_invoice_status
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.django_db
class TestSyncStripeInvoiceStatus:
    def test_sync_stripe_invoice_status_paid(self, purchase_order) -> None:
        purchase_order.stripe_invoice_id = "in_sync_test"
        purchase_order.save(update_fields=["stripe_invoice_id"])

        mock_client = MagicMock()
        invoice = MagicMock()
        # amount_paid in cents: 600.00 USD = 60000 cents
        invoice.amount_paid = 60000
        invoice.status = "paid"
        mock_client.v1.invoices.retrieve.return_value = invoice

        with patch(
            "django_program.registration.services.stripe_invoicing._get_stripe_client",
            return_value=mock_client,
        ):
            sync_stripe_invoice_status(purchase_order)

        purchase_order.refresh_from_db()
        assert purchase_order.total_paid == Decimal("600.00")
        assert purchase_order.status == PurchaseOrder.Status.PAID

    def test_sync_stripe_invoice_no_new_payment(self, purchase_order) -> None:
        """When Stripe amount_paid matches what's already recorded, no new payment is created."""
        from django_program.registration.services.purchase_orders import record_payment

        purchase_order.stripe_invoice_id = "in_sync_noop"
        purchase_order.save(update_fields=["stripe_invoice_id"])

        # Pre-record a payment of 600.00
        record_payment(
            purchase_order,
            amount=Decimal("600.00"),
            method="stripe",
            payment_date=date(2027, 7, 1),
        )

        mock_client = MagicMock()
        invoice = MagicMock()
        invoice.amount_paid = 60000  # Same 600.00 already recorded
        invoice.status = "paid"
        mock_client.v1.invoices.retrieve.return_value = invoice

        with patch(
            "django_program.registration.services.stripe_invoicing._get_stripe_client",
            return_value=mock_client,
        ):
            sync_stripe_invoice_status(purchase_order)

        purchase_order.refresh_from_db()
        # Still 600.00 -- no duplicate payment
        assert purchase_order.total_paid == Decimal("600.00")

    def test_sync_stripe_invoice_no_invoice_id(self, purchase_order) -> None:
        with pytest.raises(ValueError, match="no Stripe invoice"):
            sync_stripe_invoice_status(purchase_order)


# ---------------------------------------------------------------------------
# handle_invoice_paid_webhook
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.django_db
class TestHandleInvoicePaidWebhook:
    def test_handle_invoice_paid_webhook(self, purchase_order) -> None:
        purchase_order.stripe_invoice_id = "in_webhook_test"
        purchase_order.status = PurchaseOrder.Status.SENT
        purchase_order.save(update_fields=["stripe_invoice_id", "status"])

        payload = {
            "data": {
                "object": {
                    "id": "in_webhook_test",
                    "amount_paid": 60000,
                },
            },
        }

        handle_invoice_paid_webhook(payload)

        purchase_order.refresh_from_db()
        assert purchase_order.total_paid == Decimal("600.00")
        assert purchase_order.status == PurchaseOrder.Status.PAID

    def test_handle_invoice_paid_webhook_no_matching_po(self) -> None:
        payload = {
            "data": {
                "object": {
                    "id": "in_nonexistent",
                    "amount_paid": 10000,
                },
            },
        }
        # Should not raise -- just logs and returns
        handle_invoice_paid_webhook(payload)

    def test_handle_invoice_paid_webhook_already_paid(self, purchase_order) -> None:
        purchase_order.stripe_invoice_id = "in_already_paid"
        purchase_order.status = PurchaseOrder.Status.PAID
        purchase_order.save(update_fields=["stripe_invoice_id", "status"])

        payload = {
            "data": {
                "object": {
                    "id": "in_already_paid",
                    "amount_paid": 60000,
                },
            },
        }

        handle_invoice_paid_webhook(payload)

        purchase_order.refresh_from_db()
        # No new payment recorded -- still just PAID with 0 total_paid from payments
        assert purchase_order.status == PurchaseOrder.Status.PAID

    def test_handle_invoice_paid_webhook_no_new_amount(self, purchase_order) -> None:
        """When payment is already recorded, webhook just updates status without new payment."""
        from django_program.registration.services.purchase_orders import record_payment

        purchase_order.stripe_invoice_id = "in_already_recorded"
        purchase_order.status = PurchaseOrder.Status.SENT
        purchase_order.save(update_fields=["stripe_invoice_id", "status"])

        # Pre-record the full amount
        record_payment(
            purchase_order,
            amount=Decimal("600.00"),
            method="stripe",
            payment_date=date(2027, 7, 1),
        )

        payload = {
            "data": {
                "object": {
                    "id": "in_already_recorded",
                    "amount_paid": 60000,
                },
            },
        }

        handle_invoice_paid_webhook(payload)

        purchase_order.refresh_from_db()
        assert purchase_order.total_paid == Decimal("600.00")

    def test_handle_invoice_paid_webhook_zero_new_amount(self, conference, staff_user, ticket_type) -> None:
        """When amount_paid matches what's already recorded, update_po_status is called but no new payment."""
        from django_program.registration.services.purchase_orders import record_payment

        # Create a PO with a large total so partial payment doesn't set status to PAID
        po = create_purchase_order(
            conference=conference,
            organization_name="Zero New Org",
            contact_email="zero@test.com",
            contact_name="Zero",
            line_items=[
                {
                    "description": "Big Ticket",
                    "quantity": 10,
                    "unit_price": Decimal("200.00"),
                    "ticket_type": ticket_type,
                },
            ],
            created_by=staff_user,
        )
        po.stripe_invoice_id = "in_zero_new"
        po.status = PurchaseOrder.Status.SENT
        po.save(update_fields=["stripe_invoice_id", "status"])

        # Pre-record a partial payment of 100.00
        record_payment(
            po,
            amount=Decimal("100.00"),
            method="stripe",
            payment_date=date(2027, 7, 1),
        )
        po.refresh_from_db()
        assert po.status == PurchaseOrder.Status.PARTIALLY_PAID

        # Webhook reports same 100.00 (10000 cents) -- no new amount
        payload = {
            "data": {
                "object": {
                    "id": "in_zero_new",
                    "amount_paid": 10000,
                },
            },
        }

        handle_invoice_paid_webhook(payload)

        po.refresh_from_db()
        assert po.total_paid == Decimal("100.00")

    def test_handle_invoice_paid_webhook_empty_id(self) -> None:
        payload = {"data": {"object": {"amount_paid": 1000}}}
        handle_invoice_paid_webhook(payload)

    def test_handle_invoice_paid_webhook_bad_payload(self) -> None:
        handle_invoice_paid_webhook({"data": "not_a_dict"})
        handle_invoice_paid_webhook({})
        handle_invoice_paid_webhook({"data": {"object": "not_a_dict"}})
