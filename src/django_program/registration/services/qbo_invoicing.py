"""QuickBooks Online invoicing integration for purchase orders.

Provides functions to create and sync QBO invoices from purchase orders,
using the QBO REST API v3 directly via httpx. Handles OAuth2 token refresh
transparently so callers only need a Conference with valid QBO credentials.

The QBO OAuth flow for obtaining initial tokens is out of scope -- tokens
are assumed to be stored on the Conference model and refreshed here when
expired.
"""

import base64
import logging
from http import HTTPStatus
from typing import TYPE_CHECKING

import httpx
from django.utils import timezone

if TYPE_CHECKING:
    from django_program.conference.models import Conference
    from django_program.registration.purchase_order import PurchaseOrder

logger = logging.getLogger(__name__)

QBO_BASE_URL = "https://quickbooks.api.intuit.com"
QBO_SANDBOX_BASE_URL = "https://sandbox-quickbooks.api.intuit.com"
QBO_TOKEN_ENDPOINT = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"  # noqa: S105

_REQUEST_TIMEOUT = 30.0


class QBONotConfiguredError(ValueError):
    """Raised when a conference does not have QBO credentials configured."""


class QBOAPIError(Exception):
    """Raised when the QBO API returns an error response.

    Args:
        status_code: The HTTP status code from the QBO API.
        detail: A description of the error.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        """Initialize with the HTTP status code and error detail."""
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"QBO API error {status_code}: {detail}")


def _check_response(response: httpx.Response) -> None:
    """Raise ``QBOAPIError`` if the response is not HTTP 200.

    Args:
        response: The httpx response to check.

    Raises:
        QBOAPIError: If the status code is not 200.
    """
    if response.status_code != HTTPStatus.OK:
        raise QBOAPIError(response.status_code, response.text)


def _ensure_qbo_configured(conference: Conference) -> None:
    """Validate that a conference has the required QBO credentials.

    Args:
        conference: The conference to validate.

    Raises:
        QBONotConfiguredError: If QBO credentials are missing.
    """
    realm_id = str(conference.qbo_realm_id or "")
    access_token = str(conference.qbo_access_token or "")
    if not realm_id or not access_token:
        msg = (
            f"Conference '{conference.slug}' does not have QuickBooks Online configured. "
            f"Set qbo_realm_id and qbo_access_token on the Conference record."
        )
        raise QBONotConfiguredError(msg)


def _refresh_token_if_needed(conference: Conference) -> str:
    """Return a valid QBO access token, refreshing if expired.

    Checks ``qbo_token_expires_at`` and uses the refresh token + client
    credentials to obtain a new access token when the current one has
    expired or is about to expire (within 5 minutes).

    Args:
        conference: The conference whose tokens to check/refresh.

    Returns:
        A valid access token string.

    Raises:
        QBONotConfiguredError: If credentials are missing.
        QBOAPIError: If the token refresh request fails.
    """
    _ensure_qbo_configured(conference)

    access_token = str(conference.qbo_access_token or "")
    expires_at = conference.qbo_token_expires_at
    now = timezone.now()

    # If token is still valid (with 5-minute buffer), return it directly
    if expires_at is not None and expires_at > now + timezone.timedelta(minutes=5):
        return access_token

    refresh_token = str(conference.qbo_refresh_token or "")
    client_id = str(conference.qbo_client_id or "")
    client_secret = str(conference.qbo_client_secret or "")

    if not refresh_token or not client_id or not client_secret:
        logger.warning(
            "QBO token may be expired for conference '%s' but refresh credentials are incomplete",
            conference.slug,
        )
        return access_token

    logger.info("Refreshing QBO access token for conference '%s'", conference.slug)

    auth_header = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    response = httpx.post(
        QBO_TOKEN_ENDPOINT,
        headers={
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=_REQUEST_TIMEOUT,
    )

    _check_response(response)

    token_data = response.json()
    new_access_token = token_data["access_token"]
    new_refresh_token = token_data.get("refresh_token", refresh_token)
    expires_in = int(token_data.get("expires_in", 3600))

    conference.qbo_access_token = new_access_token
    conference.qbo_refresh_token = new_refresh_token
    conference.qbo_token_expires_at = now + timezone.timedelta(seconds=expires_in)
    conference.save(
        update_fields=[
            "qbo_access_token",
            "qbo_refresh_token",
            "qbo_token_expires_at",
            "updated_at",
        ]
    )

    logger.info("QBO token refreshed for conference '%s', expires in %ds", conference.slug, expires_in)
    return new_access_token


def _qbo_api_url(conference: Conference, endpoint: str) -> str:
    """Build the full QBO API URL for a given endpoint.

    Args:
        conference: The conference (provides realm_id).
        endpoint: The API endpoint path (e.g. ``"invoice"``).

    Returns:
        The full URL string.
    """
    realm_id = str(conference.qbo_realm_id)
    return f"{QBO_BASE_URL}/v3/company/{realm_id}/{endpoint}"


def _qbo_headers(access_token: str) -> dict[str, str]:
    """Build standard QBO API request headers.

    Args:
        access_token: A valid OAuth2 access token.

    Returns:
        Headers dict with authorization and content type.
    """
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _build_billing_address(billing_address: str) -> dict[str, str]:
    """Parse a multiline billing address into a QBO BillAddr dict.

    Args:
        billing_address: Multiline billing address text.

    Returns:
        A dict suitable for the QBO ``BillAddr`` field.
    """
    lines = billing_address.strip().splitlines()
    bill_addr: dict[str, str] = {}
    if lines:
        bill_addr["Line1"] = lines[0]
    if len(lines) > 1:
        bill_addr["Line2"] = lines[1]
    if len(lines) > 2:  # noqa: PLR2004
        bill_addr["City"] = lines[2]
    return bill_addr


def _find_or_create_customer(
    conference: Conference,
    access_token: str,
    *,
    display_name: str,
    email: str,
    billing_address: str = "",
) -> str:
    """Find an existing QBO customer by display name, or create one.

    Args:
        conference: The conference for API context.
        access_token: Valid QBO access token.
        display_name: The customer display name (organization name).
        email: Contact email address.
        billing_address: Optional billing address text.

    Returns:
        The QBO Customer ID as a string.

    Raises:
        QBOAPIError: If the API request fails.
    """
    headers = _qbo_headers(access_token)

    # Query for existing customer by display name (QBO query language, not SQL)
    safe_name = display_name.replace("'", "\\'")
    query_url = _qbo_api_url(conference, "query")
    query = f"SELECT * FROM Customer WHERE DisplayName = '{safe_name}' MAXRESULTS 1"  # noqa: S608
    response = httpx.get(
        query_url,
        headers=headers,
        params={"query": query},
        timeout=_REQUEST_TIMEOUT,
    )

    _check_response(response)

    data = response.json()
    customers = data.get("QueryResponse", {}).get("Customer", [])
    if customers:
        return str(customers[0]["Id"])

    # Create a new customer
    customer_payload: dict[str, object] = {
        "DisplayName": display_name,
        "PrimaryEmailAddr": {"Address": email},
    }
    if billing_address:
        customer_payload["BillAddr"] = _build_billing_address(billing_address)

    create_url = _qbo_api_url(conference, "customer")
    response = httpx.post(
        create_url,
        headers=headers,
        json=customer_payload,
        timeout=_REQUEST_TIMEOUT,
    )

    _check_response(response)

    created = response.json().get("Customer", {})
    customer_id = str(created.get("Id", ""))
    if not customer_id:
        msg = "QBO returned a customer without an Id"
        raise QBOAPIError(HTTPStatus.OK, msg)

    logger.info("Created QBO customer '%s' (ID: %s) for conference '%s'", display_name, customer_id, conference.slug)
    return customer_id


def _build_invoice_lines(purchase_order: PurchaseOrder) -> list[dict[str, object]]:
    """Build QBO invoice line items from a purchase order's line items.

    Args:
        purchase_order: The PO whose line items to convert.

    Returns:
        A list of QBO-formatted line item dicts.
    """
    from django_program.registration.purchase_order import PurchaseOrderLineItem  # noqa: PLC0415

    po_lines = PurchaseOrderLineItem.objects.filter(purchase_order=purchase_order)
    return [
        {
            "Amount": float(line.line_total),
            "DetailType": "SalesItemLineDetail",
            "Description": str(line.description),
            "SalesItemLineDetail": {
                "Qty": line.quantity,
                "UnitPrice": float(line.unit_price),
            },
        }
        for line in po_lines
    ]


def create_qbo_invoice(purchase_order: PurchaseOrder) -> str:
    """Create a QBO Invoice from a purchase order's line items.

    Finds or creates the QBO Customer by organization name, then builds
    and submits an invoice with the PO's line items. Stores the resulting
    QBO invoice ID and public URL on the PurchaseOrder.

    Args:
        purchase_order: The purchase order to invoice.

    Returns:
        The QBO invoice ID string.

    Raises:
        QBONotConfiguredError: If the conference lacks QBO credentials.
        QBOAPIError: If any QBO API call fails.
        ValueError: If the PO already has a QBO invoice.
    """
    if purchase_order.qbo_invoice_id:
        msg = f"PO {purchase_order.reference} already has QBO invoice {purchase_order.qbo_invoice_id}"
        raise ValueError(msg)

    conference = purchase_order.conference
    access_token = _refresh_token_if_needed(conference)

    customer_id = _find_or_create_customer(
        conference,
        access_token,
        display_name=str(purchase_order.organization_name),
        email=str(purchase_order.contact_email),
        billing_address=str(purchase_order.billing_address),
    )

    invoice_lines = _build_invoice_lines(purchase_order)

    invoice_payload: dict[str, object] = {
        "CustomerRef": {"value": customer_id},
        "Line": invoice_lines,
        "CustomerMemo": {"value": f"Purchase Order {purchase_order.reference}"},
        "PrivateNote": f"django-program PO {purchase_order.reference}",
    }

    if purchase_order.contact_email:
        invoice_payload["BillEmail"] = {"Address": str(purchase_order.contact_email)}

    headers = _qbo_headers(access_token)
    create_url = _qbo_api_url(conference, "invoice")
    response = httpx.post(
        create_url,
        headers=headers,
        json=invoice_payload,
        timeout=_REQUEST_TIMEOUT,
    )

    _check_response(response)

    invoice_data = response.json().get("Invoice", {})
    invoice_id = str(invoice_data.get("Id", ""))
    if not invoice_id:
        msg = "QBO returned an invoice without an Id"
        raise QBOAPIError(HTTPStatus.OK, msg)

    # Build the customer-facing invoice URL
    realm_id = str(conference.qbo_realm_id)
    invoice_url = f"https://app.qbo.intuit.com/app/invoice?txnId={invoice_id}&companyId={realm_id}"

    purchase_order.qbo_invoice_id = invoice_id
    purchase_order.qbo_invoice_url = invoice_url
    purchase_order.save(update_fields=["qbo_invoice_id", "qbo_invoice_url", "updated_at"])

    logger.info(
        "Created QBO invoice %s for PO %s (conference '%s')",
        invoice_id,
        purchase_order.reference,
        conference.slug,
    )
    return invoice_id


def sync_qbo_invoice_status(purchase_order: PurchaseOrder) -> None:
    """Fetch the current QBO invoice status and record payment if paid.

    Queries the QBO invoice by ID, checks its ``Balance`` field, and if
    the invoice is fully paid (balance == 0), records a payment on the PO
    using the existing ``record_payment()`` service function.

    Args:
        purchase_order: The PO whose QBO invoice to sync.

    Raises:
        ValueError: If the PO has no QBO invoice ID.
        QBONotConfiguredError: If the conference lacks QBO credentials.
        QBOAPIError: If the QBO API call fails.
    """
    if not purchase_order.qbo_invoice_id:
        msg = f"PO {purchase_order.reference} has no QBO invoice to sync"
        raise ValueError(msg)

    conference = purchase_order.conference
    access_token = _refresh_token_if_needed(conference)
    headers = _qbo_headers(access_token)

    invoice_url = _qbo_api_url(conference, f"invoice/{purchase_order.qbo_invoice_id}")
    response = httpx.get(invoice_url, headers=headers, timeout=_REQUEST_TIMEOUT)

    _check_response(response)

    invoice_data = response.json().get("Invoice", {})
    balance = float(invoice_data.get("Balance", -1))
    total_amt = float(invoice_data.get("TotalAmt", 0))

    if balance == 0 and total_amt > 0:
        _record_qbo_payment(purchase_order, total_amt)
    else:
        logger.info(
            "QBO invoice %s for PO %s has balance %.2f (not yet fully paid)",
            purchase_order.qbo_invoice_id,
            purchase_order.reference,
            balance,
        )


def _record_qbo_payment(purchase_order: PurchaseOrder, total_amt: float) -> None:
    """Record a QBO payment on a purchase order if not already fully paid.

    Args:
        purchase_order: The PO to record payment for.
        total_amt: The total invoice amount from QBO.
    """
    from decimal import Decimal  # noqa: PLC0415

    from django_program.registration.services.purchase_orders import record_payment  # noqa: PLC0415

    already_paid = purchase_order.total_paid
    payment_amount = Decimal(str(total_amt)) - already_paid

    if payment_amount > 0:
        record_payment(
            purchase_order,
            amount=payment_amount,
            method="wire",
            reference=f"QBO Invoice #{purchase_order.qbo_invoice_id}",
            payment_date=timezone.now().date(),
            note="Auto-recorded from QBO invoice payment sync.",
        )
        logger.info(
            "Recorded QBO payment of %s for PO %s",
            payment_amount,
            purchase_order.reference,
        )


def send_qbo_invoice_email(purchase_order: PurchaseOrder) -> None:
    """Send the QBO invoice to the customer via QBO's email delivery.

    Uses the QBO ``invoice/{id}/send`` endpoint to trigger email delivery
    to the billing email address stored on the invoice.

    Args:
        purchase_order: The PO whose QBO invoice to send.

    Raises:
        ValueError: If the PO has no QBO invoice ID.
        QBONotConfiguredError: If the conference lacks QBO credentials.
        QBOAPIError: If the QBO API call fails.
    """
    if not purchase_order.qbo_invoice_id:
        msg = f"PO {purchase_order.reference} has no QBO invoice to send"
        raise ValueError(msg)

    conference = purchase_order.conference
    access_token = _refresh_token_if_needed(conference)
    headers = _qbo_headers(access_token)

    send_url = _qbo_api_url(conference, f"invoice/{purchase_order.qbo_invoice_id}/send")
    params: dict[str, str] = {}
    if purchase_order.contact_email:
        params["sendTo"] = str(purchase_order.contact_email)

    response = httpx.post(send_url, headers=headers, params=params, timeout=_REQUEST_TIMEOUT)

    _check_response(response)

    logger.info(
        "Sent QBO invoice %s via email for PO %s",
        purchase_order.qbo_invoice_id,
        purchase_order.reference,
    )


def handle_qbo_webhook(payload: dict[str, object]) -> None:
    """Process a QBO webhook notification for invoice payment events.

    QBO sends webhook events when invoices are paid. This handler looks
    for ``Payment`` events, finds the associated invoice(s), and syncs
    payment status for any matching purchase orders.

    Args:
        payload: The parsed JSON webhook payload from QBO.
    """
    event_notifications = payload.get("eventNotifications", [])
    if not isinstance(event_notifications, list):
        logger.warning("QBO webhook payload has unexpected eventNotifications type")
        return

    for notification in event_notifications:
        if not isinstance(notification, dict):
            continue
        _process_webhook_notification(notification)


def _process_webhook_notification(notification: dict[str, object]) -> None:
    """Process a single QBO webhook notification.

    Args:
        notification: A single event notification dict from the QBO webhook payload.
    """
    data_change_event = notification.get("dataChangeEvent")
    if not isinstance(data_change_event, dict):
        return
    entities = data_change_event.get("entities")
    if not isinstance(entities, list):
        return

    realm_id = notification.get("realmId", "")
    if not realm_id:
        return

    for entity in entities:
        if not isinstance(entity, dict):
            continue
        entity_name = entity.get("name", "")
        operation = entity.get("operation", "")

        if entity_name == "Payment" and operation in ("Create", "Update"):
            _sync_pos_for_realm(str(realm_id))


def _sync_pos_for_realm(realm_id: str) -> None:
    """Sync QBO invoice status for all outstanding POs in a given realm.

    Args:
        realm_id: The QBO realm/company ID.
    """
    from django_program.registration.purchase_order import PurchaseOrder as POModel  # noqa: PLC0415

    pos_with_qbo = POModel.objects.filter(
        conference__qbo_realm_id=realm_id,
        qbo_invoice_id__gt="",
    ).exclude(
        status__in=[POModel.Status.PAID, POModel.Status.CANCELLED],
    )

    for po in pos_with_qbo:
        try:
            sync_qbo_invoice_status(po)
        except Exception:
            logger.exception("Failed to sync QBO invoice status for PO %s", po.reference)
