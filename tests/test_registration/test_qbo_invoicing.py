"""Tests for QuickBooks Online invoicing integration with purchase orders."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from django_program.conference.models import Conference
from django_program.registration.models import TicketType
from django_program.registration.purchase_order import PurchaseOrder
from django_program.registration.services.purchase_orders import create_purchase_order
from django_program.registration.services.qbo_invoicing import (
    QBOAPIError,
    QBONotConfiguredError,
    _check_response,
    _refresh_token_if_needed,
    create_qbo_invoice,
    handle_qbo_webhook,
    send_qbo_invoice_email,
    sync_qbo_invoice_status,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conference(db) -> Conference:
    return Conference.objects.create(
        name="QBO Inv Conf",
        slug="qbo-inv-conf",
        start_date=date(2027, 7, 1),
        end_date=date(2027, 7, 3),
        timezone="UTC",
        qbo_realm_id="1234567890",
        qbo_access_token="qbo_access_fake",
        qbo_refresh_token="qbo_refresh_fake",
        qbo_client_id="qbo_client_id_fake",
        qbo_client_secret="qbo_client_secret_fake",
        qbo_token_expires_at=timezone.now() + timedelta(hours=1),
    )


@pytest.fixture
def staff_user(db) -> User:
    return User.objects.create_user(username="qboinvstaff", email="qboinv@test.com", password="testpass123")


@pytest.fixture
def ticket_type(conference) -> TicketType:
    return TicketType.objects.create(
        conference=conference,
        name="Corporate",
        slug="corporate-qbo",
        price=Decimal("300.00"),
        total_quantity=0,
        limit_per_user=10,
        is_active=True,
    )


@pytest.fixture
def purchase_order(conference, staff_user, ticket_type) -> PurchaseOrder:
    return create_purchase_order(
        conference=conference,
        organization_name="QBO Test Org",
        contact_email="billing@qbo-test.com",
        contact_name="QBO Person",
        billing_address="100 Invoice Rd\nSuite 200\nPortland",
        line_items=[
            {
                "description": "Corporate Ticket",
                "quantity": 4,
                "unit_price": Decimal("300.00"),
                "ticket_type": ticket_type,
            },
        ],
        created_by=staff_user,
    )


def _mock_httpx_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = ""
    return resp


# ---------------------------------------------------------------------------
# create_qbo_invoice
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.django_db
class TestCreateQBOInvoice:
    def test_create_qbo_invoice(self, purchase_order) -> None:
        # Customer query returns empty (needs creation), then create returns customer
        query_resp = _mock_httpx_response(json_data={"QueryResponse": {"Customer": []}})
        create_customer_resp = _mock_httpx_response(json_data={"Customer": {"Id": "42"}})
        create_invoice_resp = _mock_httpx_response(json_data={"Invoice": {"Id": "INV-99"}})

        with patch("django_program.registration.services.qbo_invoicing.httpx") as mock_httpx:
            mock_httpx.get.return_value = query_resp
            mock_httpx.post.side_effect = [create_customer_resp, create_invoice_resp]

            invoice_id = create_qbo_invoice(purchase_order)

        assert invoice_id == "INV-99"
        purchase_order.refresh_from_db()
        assert purchase_order.qbo_invoice_id == "INV-99"
        assert "INV-99" in purchase_order.qbo_invoice_url

    def test_create_qbo_invoice_not_configured(self, staff_user) -> None:
        conf = Conference.objects.create(
            name="No QBO Conf",
            slug="no-qbo-conf",
            start_date=date(2027, 8, 1),
            end_date=date(2027, 8, 3),
            timezone="UTC",
        )
        po = create_purchase_order(
            conference=conf,
            organization_name="NoQBO Org",
            contact_email="noqbo@test.com",
            contact_name="NoQBO",
            line_items=[{"description": "Item", "quantity": 1, "unit_price": Decimal("50.00")}],
            created_by=staff_user,
        )

        with pytest.raises(QBONotConfiguredError):
            create_qbo_invoice(po)

    def test_create_qbo_invoice_already_exists(self, purchase_order) -> None:
        purchase_order.qbo_invoice_id = "INV-EXISTING"
        purchase_order.save(update_fields=["qbo_invoice_id"])

        with pytest.raises(ValueError, match="already has QBO invoice"):
            create_qbo_invoice(purchase_order)

    def test_create_qbo_invoice_customer_no_id(self, purchase_order) -> None:
        query_resp = _mock_httpx_response(json_data={"QueryResponse": {"Customer": []}})
        # Customer creation returns empty Id
        create_customer_resp = _mock_httpx_response(json_data={"Customer": {"Id": ""}})

        with patch("django_program.registration.services.qbo_invoicing.httpx") as mock_httpx:
            mock_httpx.get.return_value = query_resp
            mock_httpx.post.return_value = create_customer_resp

            with pytest.raises(QBOAPIError, match="without an Id"):
                create_qbo_invoice(purchase_order)

    def test_create_qbo_invoice_no_invoice_id_returned(self, purchase_order) -> None:
        query_resp = _mock_httpx_response(json_data={"QueryResponse": {"Customer": [{"Id": "42"}]}})
        # Invoice creation returns empty Id
        create_invoice_resp = _mock_httpx_response(json_data={"Invoice": {"Id": ""}})

        with patch("django_program.registration.services.qbo_invoicing.httpx") as mock_httpx:
            mock_httpx.get.return_value = query_resp
            mock_httpx.post.return_value = create_invoice_resp

            with pytest.raises(QBOAPIError, match="without an Id"):
                create_qbo_invoice(purchase_order)

    def test_create_qbo_invoice_existing_customer(self, purchase_order) -> None:
        # Customer query returns an existing customer
        query_resp = _mock_httpx_response(json_data={"QueryResponse": {"Customer": [{"Id": "77"}]}})
        create_invoice_resp = _mock_httpx_response(json_data={"Invoice": {"Id": "INV-200"}})

        with patch("django_program.registration.services.qbo_invoicing.httpx") as mock_httpx:
            mock_httpx.get.return_value = query_resp
            mock_httpx.post.return_value = create_invoice_resp

            invoice_id = create_qbo_invoice(purchase_order)

        assert invoice_id == "INV-200"
        # httpx.post should only be called once (for invoice, not customer creation)
        assert mock_httpx.post.call_count == 1


# ---------------------------------------------------------------------------
# sync_qbo_invoice_status
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.django_db
class TestSyncQBOInvoiceStatus:
    def test_sync_qbo_invoice_status_paid(self, purchase_order) -> None:
        purchase_order.qbo_invoice_id = "INV-SYNC"
        purchase_order.status = PurchaseOrder.Status.SENT
        purchase_order.save(update_fields=["qbo_invoice_id", "status"])

        invoice_resp = _mock_httpx_response(
            json_data={"Invoice": {"Balance": 0, "TotalAmt": 1200.00}},
        )

        with patch("django_program.registration.services.qbo_invoicing.httpx") as mock_httpx:
            mock_httpx.get.return_value = invoice_resp
            sync_qbo_invoice_status(purchase_order)

        purchase_order.refresh_from_db()
        assert purchase_order.total_paid == Decimal("1200.00")
        assert purchase_order.status == PurchaseOrder.Status.PAID

    def test_sync_qbo_invoice_no_invoice_id(self, purchase_order) -> None:
        with pytest.raises(ValueError, match="no QBO invoice"):
            sync_qbo_invoice_status(purchase_order)

    def test_sync_qbo_invoice_not_yet_paid(self, purchase_order) -> None:
        purchase_order.qbo_invoice_id = "INV-UNPAID"
        purchase_order.status = PurchaseOrder.Status.SENT
        purchase_order.save(update_fields=["qbo_invoice_id", "status"])

        invoice_resp = _mock_httpx_response(
            json_data={"Invoice": {"Balance": 600.00, "TotalAmt": 1200.00}},
        )

        with patch("django_program.registration.services.qbo_invoicing.httpx") as mock_httpx:
            mock_httpx.get.return_value = invoice_resp
            sync_qbo_invoice_status(purchase_order)

        purchase_order.refresh_from_db()
        assert purchase_order.total_paid == Decimal("0.00")
        assert purchase_order.status == PurchaseOrder.Status.SENT


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.django_db
class TestQBOTokenRefresh:
    def test_qbo_token_refresh(self, purchase_order, conference) -> None:
        # Set token as expired
        conference.qbo_token_expires_at = timezone.now() - timedelta(minutes=10)
        conference.save(update_fields=["qbo_token_expires_at"])

        purchase_order.qbo_invoice_id = "INV-REFRESH"
        purchase_order.status = PurchaseOrder.Status.SENT
        purchase_order.save(update_fields=["qbo_invoice_id", "status"])

        # Token refresh response
        token_resp = _mock_httpx_response(
            json_data={
                "access_token": "new_access_token",
                "refresh_token": "new_refresh_token",
                "expires_in": 3600,
            },
        )
        # Invoice status response (paid)
        invoice_resp = _mock_httpx_response(
            json_data={"Invoice": {"Balance": 0, "TotalAmt": 1200.00}},
        )

        with patch("django_program.registration.services.qbo_invoicing.httpx") as mock_httpx:
            # First call is POST (token refresh), second is GET (invoice fetch)
            mock_httpx.post.return_value = token_resp
            mock_httpx.get.return_value = invoice_resp

            sync_qbo_invoice_status(purchase_order)

        conference.refresh_from_db()
        assert str(conference.qbo_access_token) == "new_access_token"
        assert str(conference.qbo_refresh_token) == "new_refresh_token"

        purchase_order.refresh_from_db()
        assert purchase_order.total_paid == Decimal("1200.00")

    def test_qbo_token_refresh_incomplete_credentials(self, conference) -> None:
        """When refresh credentials are missing, the expired token is returned as-is."""
        conference.qbo_token_expires_at = timezone.now() - timedelta(minutes=10)
        conference.qbo_client_id = ""
        conference.qbo_client_secret = ""
        conference.save(update_fields=["qbo_token_expires_at", "qbo_client_id", "qbo_client_secret"])

        token = _refresh_token_if_needed(conference)
        assert token == str(conference.qbo_access_token)


# ---------------------------------------------------------------------------
# QBOAPIError and _check_response
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQBOAPIError:
    def test_error_attributes(self) -> None:
        err = QBOAPIError(400, "Bad request")
        assert err.status_code == 400
        assert err.detail == "Bad request"
        assert "400" in str(err)
        assert "Bad request" in str(err)

    def test_check_response_raises_on_error(self) -> None:
        resp = MagicMock()
        resp.status_code = 401
        resp.text = "Unauthorized"
        with pytest.raises(QBOAPIError) as exc_info:
            _check_response(resp)
        assert exc_info.value.status_code == 401

    def test_check_response_ok(self) -> None:
        resp = MagicMock()
        resp.status_code = 200
        _check_response(resp)  # Should not raise


# ---------------------------------------------------------------------------
# send_qbo_invoice_email
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.django_db
class TestSendQBOInvoiceEmail:
    def test_send_qbo_invoice_email(self, purchase_order) -> None:
        purchase_order.qbo_invoice_id = "INV-SEND"
        purchase_order.save(update_fields=["qbo_invoice_id"])

        send_resp = _mock_httpx_response()

        with patch("django_program.registration.services.qbo_invoicing.httpx") as mock_httpx:
            mock_httpx.post.return_value = send_resp
            send_qbo_invoice_email(purchase_order)

        mock_httpx.post.assert_called_once()

    def test_send_qbo_invoice_email_no_invoice_id(self, purchase_order) -> None:
        with pytest.raises(ValueError, match="no QBO invoice"):
            send_qbo_invoice_email(purchase_order)


# ---------------------------------------------------------------------------
# handle_qbo_webhook
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.django_db
class TestHandleQBOWebhook:
    def test_handle_qbo_webhook_payment_event(self, purchase_order, conference) -> None:
        purchase_order.qbo_invoice_id = "INV-WH"
        purchase_order.status = PurchaseOrder.Status.SENT
        purchase_order.save(update_fields=["qbo_invoice_id", "status"])

        invoice_resp = _mock_httpx_response(
            json_data={"Invoice": {"Balance": 0, "TotalAmt": 1200.00}},
        )

        payload = {
            "eventNotifications": [
                {
                    "realmId": str(conference.qbo_realm_id),
                    "dataChangeEvent": {
                        "entities": [
                            {"name": "Payment", "operation": "Create"},
                        ],
                    },
                },
            ],
        }

        with patch("django_program.registration.services.qbo_invoicing.httpx") as mock_httpx:
            mock_httpx.get.return_value = invoice_resp
            handle_qbo_webhook(payload)

        purchase_order.refresh_from_db()
        assert purchase_order.total_paid == Decimal("1200.00")

    def test_handle_qbo_webhook_non_payment_event(self) -> None:
        payload = {
            "eventNotifications": [
                {
                    "realmId": "999",
                    "dataChangeEvent": {
                        "entities": [
                            {"name": "Invoice", "operation": "Create"},
                        ],
                    },
                },
            ],
        }
        handle_qbo_webhook(payload)

    def test_handle_qbo_webhook_bad_payload(self) -> None:
        handle_qbo_webhook({"eventNotifications": "not_a_list"})
        handle_qbo_webhook({})

    def test_handle_qbo_webhook_bad_notification(self) -> None:
        handle_qbo_webhook({"eventNotifications": ["not_a_dict"]})

    def test_handle_qbo_webhook_missing_realm_id(self) -> None:
        payload = {
            "eventNotifications": [
                {
                    "dataChangeEvent": {
                        "entities": [
                            {"name": "Payment", "operation": "Create"},
                        ],
                    },
                },
            ],
        }
        handle_qbo_webhook(payload)

    def test_handle_qbo_webhook_bad_data_change_event(self) -> None:
        payload = {
            "eventNotifications": [
                {
                    "realmId": "999",
                    "dataChangeEvent": "not_a_dict",
                },
            ],
        }
        handle_qbo_webhook(payload)

    def test_handle_qbo_webhook_bad_entities(self) -> None:
        payload = {
            "eventNotifications": [
                {
                    "realmId": "999",
                    "dataChangeEvent": {
                        "entities": "not_a_list",
                    },
                },
            ],
        }
        handle_qbo_webhook(payload)

    def test_handle_qbo_webhook_sync_failure(self, purchase_order, conference) -> None:
        """When sync fails for a PO, it logs the exception and continues."""
        purchase_order.qbo_invoice_id = "INV-FAIL"
        purchase_order.status = PurchaseOrder.Status.SENT
        purchase_order.save(update_fields=["qbo_invoice_id", "status"])

        payload = {
            "eventNotifications": [
                {
                    "realmId": str(conference.qbo_realm_id),
                    "dataChangeEvent": {
                        "entities": [
                            {"name": "Payment", "operation": "Update"},
                        ],
                    },
                },
            ],
        }

        with patch(
            "django_program.registration.services.qbo_invoicing.sync_qbo_invoice_status",
            side_effect=RuntimeError("API failure"),
        ):
            handle_qbo_webhook(payload)

    def test_handle_qbo_webhook_many_pos_warning(self, conference, staff_user, ticket_type) -> None:
        """When there are more POs than _WEBHOOK_SYNC_LIMIT, a warning is logged."""
        with patch("django_program.registration.services.qbo_invoicing._WEBHOOK_SYNC_LIMIT", 1):
            for i in range(2):
                po = create_purchase_order(
                    conference=conference,
                    organization_name=f"Org {i}",
                    contact_email=f"org{i}@test.com",
                    contact_name=f"Person {i}",
                    line_items=[{"description": "Ticket", "quantity": 1, "unit_price": Decimal("100.00")}],
                    created_by=staff_user,
                )
                po.qbo_invoice_id = f"INV-MANY-{i}"
                po.status = PurchaseOrder.Status.SENT
                po.save(update_fields=["qbo_invoice_id", "status"])

            invoice_resp = _mock_httpx_response(
                json_data={"Invoice": {"Balance": 0, "TotalAmt": 100.00}},
            )

            payload = {
                "eventNotifications": [
                    {
                        "realmId": str(conference.qbo_realm_id),
                        "dataChangeEvent": {
                            "entities": [
                                {"name": "Payment", "operation": "Create"},
                            ],
                        },
                    },
                ],
            }

            with patch("django_program.registration.services.qbo_invoicing.httpx") as mock_httpx:
                mock_httpx.get.return_value = invoice_resp
                handle_qbo_webhook(payload)

    def test_handle_qbo_webhook_bad_entity(self) -> None:
        payload = {
            "eventNotifications": [
                {
                    "realmId": "999",
                    "dataChangeEvent": {
                        "entities": ["not_a_dict"],
                    },
                },
            ],
        }
        handle_qbo_webhook(payload)
