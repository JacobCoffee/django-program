"""Tests for purchase order management dashboard views."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from django_program.conference.models import Conference
from django_program.registration.models import TicketType
from django_program.registration.purchase_order import PurchaseOrder
from django_program.registration.services.purchase_orders import (
    create_purchase_order,
    send_purchase_order,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def superuser(db) -> User:
    return User.objects.create_superuser(username="poadmin", password="password", email="poadmin@test.com")


@pytest.fixture
def conference(db) -> Conference:
    return Conference.objects.create(
        name="PO Test Conf",
        slug="po-test-conf",
        start_date=date(2027, 6, 1),
        end_date=date(2027, 6, 3),
        timezone="UTC",
        is_active=True,
    )


@pytest.fixture
def ticket_type(conference) -> TicketType:
    return TicketType.objects.create(
        conference=conference,
        name="Corporate",
        slug="corporate",
        price=Decimal("250.00"),
        total_quantity=0,
        limit_per_user=10,
        is_active=True,
    )


@pytest.fixture
def logged_in_client(superuser) -> Client:
    c = Client()
    c.force_login(superuser)
    return c


@pytest.fixture
def purchase_order(conference, superuser, ticket_type) -> PurchaseOrder:
    return create_purchase_order(
        conference=conference,
        organization_name="Acme Corp",
        contact_email="billing@acme.com",
        contact_name="Jane Doe",
        billing_address="123 Corporate Ave",
        line_items=[
            {
                "description": "Corporate Ticket",
                "quantity": 5,
                "unit_price": Decimal("250.00"),
                "ticket_type": ticket_type,
            },
        ],
        notes="Test PO",
        created_by=superuser,
    )


def _po_url(name: str, conference_slug: str, pk: int | None = None) -> str:
    kwargs: dict[str, object] = {"conference_slug": conference_slug}
    if pk is not None:
        kwargs["pk"] = pk
    return reverse(f"manage:{name}", kwargs=kwargs)


# ---------------------------------------------------------------------------
# List view
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.django_db
class TestPurchaseOrderListView:
    def test_purchase_order_list_view(self, logged_in_client, conference, purchase_order) -> None:
        url = _po_url("purchase-order-list", conference.slug)
        resp = logged_in_client.get(url)
        assert resp.status_code == 200
        assert purchase_order in resp.context["purchase_orders"]

    def test_purchase_order_list_status_filter(self, logged_in_client, conference, purchase_order) -> None:
        url = _po_url("purchase-order-list", conference.slug) + "?status=draft"
        resp = logged_in_client.get(url)
        assert resp.status_code == 200
        assert purchase_order in resp.context["purchase_orders"]

        url_sent = _po_url("purchase-order-list", conference.slug) + "?status=sent"
        resp_sent = logged_in_client.get(url_sent)
        assert resp_sent.status_code == 200
        assert purchase_order not in resp_sent.context["purchase_orders"]


# ---------------------------------------------------------------------------
# Detail view
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.django_db
class TestPurchaseOrderDetailView:
    def test_purchase_order_detail_view(self, logged_in_client, conference, purchase_order) -> None:
        url = _po_url("purchase-order-detail", conference.slug, purchase_order.pk)
        resp = logged_in_client.get(url)
        assert resp.status_code == 200
        assert resp.context["purchase_order"] == purchase_order


# ---------------------------------------------------------------------------
# Create view
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.django_db
class TestPurchaseOrderCreateView:
    def test_purchase_order_create_get(self, logged_in_client, conference) -> None:
        url = _po_url("purchase-order-add", conference.slug)
        resp = logged_in_client.get(url)
        assert resp.status_code == 200

    def test_purchase_order_create_post(self, logged_in_client, conference) -> None:
        url = _po_url("purchase-order-add", conference.slug)
        resp = logged_in_client.post(
            url,
            {
                "organization_name": "NewOrg",
                "contact_email": "new@org.com",
                "contact_name": "Bob",
                "billing_address": "456 Elm St",
                "notes": "",
                "line_description": ["Widget"],
                "line_quantity": ["2"],
                "line_unit_price": ["100.00"],
            },
        )
        assert resp.status_code == 302
        po = PurchaseOrder.objects.get(organization_name="NewOrg")
        assert po.total == Decimal("200.00")

    def test_purchase_order_create_post_validation(self, logged_in_client, conference) -> None:
        url = _po_url("purchase-order-add", conference.slug)
        resp = logged_in_client.post(
            url,
            {
                "organization_name": "",
                "contact_email": "",
                "contact_name": "",
                "line_description": [],
                "line_quantity": [],
                "line_unit_price": [],
            },
        )
        # Re-renders the form (200), not a redirect
        assert resp.status_code == 200

    def test_purchase_order_create_post_blank_line_description(self, logged_in_client, conference) -> None:
        url = _po_url("purchase-order-add", conference.slug)
        resp = logged_in_client.post(
            url,
            {
                "organization_name": "BlankLineOrg",
                "contact_email": "blank@org.com",
                "contact_name": "Blank",
                "line_description": ["", "Widget"],
                "line_quantity": ["1", "2"],
                "line_unit_price": ["10.00", "50.00"],
            },
        )
        assert resp.status_code == 302
        po = PurchaseOrder.objects.get(organization_name="BlankLineOrg")
        # Only the non-blank line item should be created
        assert po.line_items.count() == 1
        assert po.total == Decimal("100.00")

    def test_purchase_order_create_post_invalid_line_items(self, logged_in_client, conference) -> None:
        url = _po_url("purchase-order-add", conference.slug)
        resp = logged_in_client.post(
            url,
            {
                "organization_name": "ValidOrg",
                "contact_email": "valid@org.com",
                "contact_name": "Valid",
                "line_description": ["Widget", "Gadget", "Doohickey"],
                "line_quantity": ["abc", "0", "2"],
                "line_unit_price": ["10.00", "20.00", "-5.00"],
            },
        )
        # Re-renders with errors (invalid qty, qty < 1, negative price)
        assert resp.status_code == 200

    def test_purchase_order_create_post_service_exception(self, logged_in_client, conference) -> None:
        url = _po_url("purchase-order-add", conference.slug)
        with patch(
            "django_program.manage.views_purchase_orders.create_purchase_order",
            side_effect=RuntimeError("DB error"),
        ):
            resp = logged_in_client.post(
                url,
                {
                    "organization_name": "ExcOrg",
                    "contact_email": "exc@org.com",
                    "contact_name": "Exc",
                    "line_description": ["Item"],
                    "line_quantity": ["1"],
                    "line_unit_price": ["50.00"],
                },
            )
        assert resp.status_code == 302


# ---------------------------------------------------------------------------
# Record payment view
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.django_db
class TestPurchaseOrderRecordPaymentView:
    def test_purchase_order_record_payment(self, logged_in_client, conference, purchase_order) -> None:
        url = _po_url("purchase-order-payment", conference.slug, purchase_order.pk)
        resp = logged_in_client.post(
            url,
            {
                "amount": "500.00",
                "method": "wire",
                "reference": "WIRE-001",
                "note": "First payment",
                "payment_date": "2027-06-01",
            },
        )
        assert resp.status_code == 302
        purchase_order.refresh_from_db()
        assert purchase_order.total_paid == Decimal("500.00")

    def test_purchase_order_record_payment_invalid_method(self, logged_in_client, conference, purchase_order) -> None:
        url = _po_url("purchase-order-payment", conference.slug, purchase_order.pk)
        resp = logged_in_client.post(
            url,
            {"amount": "100.00", "method": "invalid_method", "payment_date": "2027-06-01"},
        )
        assert resp.status_code == 302
        purchase_order.refresh_from_db()
        assert purchase_order.total_paid == Decimal("100.00")

    def test_purchase_order_record_payment_invalid_amount(self, logged_in_client, conference, purchase_order) -> None:
        url = _po_url("purchase-order-payment", conference.slug, purchase_order.pk)
        resp = logged_in_client.post(url, {"amount": "not-a-number", "method": "wire"})
        assert resp.status_code == 302
        purchase_order.refresh_from_db()
        assert purchase_order.total_paid == Decimal("0.00")

    def test_purchase_order_record_payment_zero_amount(self, logged_in_client, conference, purchase_order) -> None:
        url = _po_url("purchase-order-payment", conference.slug, purchase_order.pk)
        resp = logged_in_client.post(url, {"amount": "0", "method": "wire"})
        assert resp.status_code == 302
        purchase_order.refresh_from_db()
        assert purchase_order.total_paid == Decimal("0.00")

    def test_purchase_order_record_payment_invalid_date(self, logged_in_client, conference, purchase_order) -> None:
        url = _po_url("purchase-order-payment", conference.slug, purchase_order.pk)
        resp = logged_in_client.post(
            url,
            {"amount": "100.00", "method": "wire", "payment_date": "not-a-date"},
        )
        assert resp.status_code == 302
        purchase_order.refresh_from_db()
        assert purchase_order.total_paid == Decimal("100.00")

    def test_purchase_order_record_payment_exception(self, logged_in_client, conference, purchase_order) -> None:
        url = _po_url("purchase-order-payment", conference.slug, purchase_order.pk)
        with patch(
            "django_program.manage.views_purchase_orders.record_payment",
            side_effect=RuntimeError("DB error"),
        ):
            resp = logged_in_client.post(url, {"amount": "100.00", "method": "wire"})
        assert resp.status_code == 302
        purchase_order.refresh_from_db()
        assert purchase_order.total_paid == Decimal("0.00")

    def test_purchase_order_record_payment_cancelled(self, logged_in_client, conference, purchase_order) -> None:
        purchase_order.status = PurchaseOrder.Status.CANCELLED
        purchase_order.save(update_fields=["status"])

        url = _po_url("purchase-order-payment", conference.slug, purchase_order.pk)
        resp = logged_in_client.post(url, {"amount": "100.00", "method": "wire"})
        assert resp.status_code == 302
        purchase_order.refresh_from_db()
        assert purchase_order.total_paid == Decimal("0.00")


# ---------------------------------------------------------------------------
# Issue credit view
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.django_db
class TestPurchaseOrderIssueCreditView:
    def test_purchase_order_issue_credit(self, logged_in_client, conference, purchase_order) -> None:
        url = _po_url("purchase-order-credit", conference.slug, purchase_order.pk)
        resp = logged_in_client.post(
            url,
            {"amount": "200.00", "reason": "Comp discount"},
        )
        assert resp.status_code == 302
        purchase_order.refresh_from_db()
        assert purchase_order.balance_due == Decimal("1050.00")

    def test_purchase_order_issue_credit_invalid_amount(self, logged_in_client, conference, purchase_order) -> None:
        url = _po_url("purchase-order-credit", conference.slug, purchase_order.pk)
        resp = logged_in_client.post(url, {"amount": "bad", "reason": "Test"})
        assert resp.status_code == 302
        assert purchase_order.credit_notes.count() == 0

    def test_purchase_order_issue_credit_zero_amount(self, logged_in_client, conference, purchase_order) -> None:
        url = _po_url("purchase-order-credit", conference.slug, purchase_order.pk)
        resp = logged_in_client.post(url, {"amount": "0", "reason": "Test"})
        assert resp.status_code == 302
        assert purchase_order.credit_notes.count() == 0

    def test_purchase_order_issue_credit_missing_reason(self, logged_in_client, conference, purchase_order) -> None:
        url = _po_url("purchase-order-credit", conference.slug, purchase_order.pk)
        resp = logged_in_client.post(url, {"amount": "100.00", "reason": ""})
        assert resp.status_code == 302
        assert purchase_order.credit_notes.count() == 0

    def test_purchase_order_issue_credit_exception(self, logged_in_client, conference, purchase_order) -> None:
        url = _po_url("purchase-order-credit", conference.slug, purchase_order.pk)
        with patch(
            "django_program.manage.views_purchase_orders.issue_credit_note",
            side_effect=RuntimeError("DB error"),
        ):
            resp = logged_in_client.post(url, {"amount": "100.00", "reason": "Reason"})
        assert resp.status_code == 302
        assert purchase_order.credit_notes.count() == 0

    def test_purchase_order_issue_credit_cancelled(self, logged_in_client, conference, purchase_order) -> None:
        purchase_order.status = PurchaseOrder.Status.CANCELLED
        purchase_order.save(update_fields=["status"])

        url = _po_url("purchase-order-credit", conference.slug, purchase_order.pk)
        resp = logged_in_client.post(url, {"amount": "100.00", "reason": "Test"})
        assert resp.status_code == 302
        # No credit notes should have been created
        assert purchase_order.credit_notes.count() == 0


# ---------------------------------------------------------------------------
# Cancel view
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.django_db
class TestPurchaseOrderCancelView:
    def test_purchase_order_cancel(self, logged_in_client, conference, purchase_order) -> None:
        url = _po_url("purchase-order-cancel", conference.slug, purchase_order.pk)
        resp = logged_in_client.post(url)
        assert resp.status_code == 302
        purchase_order.refresh_from_db()
        assert purchase_order.status == PurchaseOrder.Status.CANCELLED

    def test_purchase_order_cancel_already_cancelled(self, logged_in_client, conference, purchase_order) -> None:
        purchase_order.status = PurchaseOrder.Status.CANCELLED
        purchase_order.save(update_fields=["status"])
        url = _po_url("purchase-order-cancel", conference.slug, purchase_order.pk)
        resp = logged_in_client.post(url)
        assert resp.status_code == 302

    def test_purchase_order_cancel_paid(self, logged_in_client, conference, purchase_order) -> None:
        purchase_order.status = PurchaseOrder.Status.PAID
        purchase_order.save(update_fields=["status"])
        url = _po_url("purchase-order-cancel", conference.slug, purchase_order.pk)
        resp = logged_in_client.post(url)
        assert resp.status_code == 302
        purchase_order.refresh_from_db()
        assert purchase_order.status == PurchaseOrder.Status.PAID

    def test_purchase_order_cancel_exception(self, logged_in_client, conference, purchase_order) -> None:
        url = _po_url("purchase-order-cancel", conference.slug, purchase_order.pk)
        with patch(
            "django_program.manage.views_purchase_orders.cancel_purchase_order",
            side_effect=RuntimeError("DB error"),
        ):
            resp = logged_in_client.post(url)
        assert resp.status_code == 302


# ---------------------------------------------------------------------------
# Send view
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.django_db
class TestPurchaseOrderSendView:
    def test_purchase_order_send(self, logged_in_client, conference, purchase_order) -> None:
        url = _po_url("purchase-order-send", conference.slug, purchase_order.pk)
        resp = logged_in_client.post(url)
        assert resp.status_code == 302
        purchase_order.refresh_from_db()
        assert purchase_order.status == PurchaseOrder.Status.SENT

    def test_purchase_order_send_non_draft_shows_error(self, logged_in_client, conference, purchase_order) -> None:
        send_purchase_order(purchase_order)
        purchase_order.refresh_from_db()
        assert purchase_order.status == PurchaseOrder.Status.SENT

        url = _po_url("purchase-order-send", conference.slug, purchase_order.pk)
        resp = logged_in_client.post(url)
        assert resp.status_code == 302

    def test_purchase_order_send_exception(self, logged_in_client, conference, purchase_order) -> None:
        url = _po_url("purchase-order-send", conference.slug, purchase_order.pk)
        with patch(
            "django_program.manage.views_purchase_orders.send_purchase_order",
            side_effect=RuntimeError("DB error"),
        ):
            resp = logged_in_client.post(url)
        assert resp.status_code == 302


# ---------------------------------------------------------------------------
# Invoice PDF view
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.django_db
class TestPurchaseOrderInvoiceView:
    def test_purchase_order_invoice_pdf(self, logged_in_client, conference, purchase_order) -> None:
        url = _po_url("purchase-order-invoice", conference.slug, purchase_order.pk)
        resp = logged_in_client.get(url)
        assert resp.status_code == 200
        assert resp["Content-Type"] == "application/pdf"
        assert "attachment" in resp["Content-Disposition"]
        assert purchase_order.reference in resp["Content-Disposition"]


# ---------------------------------------------------------------------------
# Stripe invoice view
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.django_db
class TestPurchaseOrderStripeInvoiceView:
    def test_stripe_invoice_creates_and_redirects(self, logged_in_client, conference, purchase_order) -> None:
        url = _po_url("purchase-order-stripe-invoice", conference.slug, purchase_order.pk)
        with patch(
            "django_program.manage.views_purchase_orders.create_stripe_invoice",
            return_value="https://invoice.stripe.com/i/test",
        ):
            resp = logged_in_client.post(url)
        assert resp.status_code == 302
        purchase_order.refresh_from_db()
        assert purchase_order.status == PurchaseOrder.Status.SENT

    def test_stripe_invoice_invalid_status(self, logged_in_client, conference, purchase_order) -> None:
        purchase_order.status = PurchaseOrder.Status.CANCELLED
        purchase_order.save(update_fields=["status"])

        url = _po_url("purchase-order-stripe-invoice", conference.slug, purchase_order.pk)
        resp = logged_in_client.post(url)
        assert resp.status_code == 302

    def test_stripe_invoice_value_error(self, logged_in_client, conference, purchase_order) -> None:
        url = _po_url("purchase-order-stripe-invoice", conference.slug, purchase_order.pk)
        with patch(
            "django_program.manage.views_purchase_orders.create_stripe_invoice",
            side_effect=ValueError("already has a Stripe invoice"),
        ):
            resp = logged_in_client.post(url)
        assert resp.status_code == 302

    def test_stripe_invoice_general_exception(self, logged_in_client, conference, purchase_order) -> None:
        url = _po_url("purchase-order-stripe-invoice", conference.slug, purchase_order.pk)
        with patch(
            "django_program.manage.views_purchase_orders.create_stripe_invoice",
            side_effect=RuntimeError("Stripe API down"),
        ):
            resp = logged_in_client.post(url)
        assert resp.status_code == 302


# ---------------------------------------------------------------------------
# QBO invoice view
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.django_db
class TestPurchaseOrderQBOInvoiceView:
    def test_qbo_invoice_creates_and_redirects(self, logged_in_client, conference, purchase_order) -> None:
        url = _po_url("purchase-order-qbo-invoice", conference.slug, purchase_order.pk)
        with (
            patch("django_program.manage.views_purchase_orders.create_qbo_invoice"),
            patch("django_program.manage.views_purchase_orders.send_qbo_invoice_email"),
        ):
            resp = logged_in_client.post(url)
        assert resp.status_code == 302
        purchase_order.refresh_from_db()
        assert purchase_order.status == PurchaseOrder.Status.SENT

    def test_qbo_invoice_invalid_status(self, logged_in_client, conference, purchase_order) -> None:
        purchase_order.status = PurchaseOrder.Status.CANCELLED
        purchase_order.save(update_fields=["status"])

        url = _po_url("purchase-order-qbo-invoice", conference.slug, purchase_order.pk)
        resp = logged_in_client.post(url)
        assert resp.status_code == 302

    def test_qbo_invoice_already_exists(self, logged_in_client, conference, purchase_order) -> None:
        purchase_order.qbo_invoice_id = "123"
        purchase_order.save(update_fields=["qbo_invoice_id"])

        url = _po_url("purchase-order-qbo-invoice", conference.slug, purchase_order.pk)
        resp = logged_in_client.post(url)
        assert resp.status_code == 302

    def test_qbo_invoice_not_configured(self, logged_in_client, conference, purchase_order) -> None:
        from django_program.registration.services.qbo_invoicing import QBONotConfiguredError

        url = _po_url("purchase-order-qbo-invoice", conference.slug, purchase_order.pk)
        with patch(
            "django_program.manage.views_purchase_orders.create_qbo_invoice",
            side_effect=QBONotConfiguredError("not configured"),
        ):
            resp = logged_in_client.post(url)
        assert resp.status_code == 302

    def test_qbo_invoice_api_error(self, logged_in_client, conference, purchase_order) -> None:
        from django_program.registration.services.qbo_invoicing import QBOAPIError

        url = _po_url("purchase-order-qbo-invoice", conference.slug, purchase_order.pk)
        with patch(
            "django_program.manage.views_purchase_orders.create_qbo_invoice",
            side_effect=QBOAPIError(400, "Bad request"),
        ):
            resp = logged_in_client.post(url)
        assert resp.status_code == 302

    def test_qbo_invoice_general_exception(self, logged_in_client, conference, purchase_order) -> None:
        url = _po_url("purchase-order-qbo-invoice", conference.slug, purchase_order.pk)
        with patch(
            "django_program.manage.views_purchase_orders.create_qbo_invoice",
            side_effect=RuntimeError("QBO down"),
        ):
            resp = logged_in_client.post(url)
        assert resp.status_code == 302
