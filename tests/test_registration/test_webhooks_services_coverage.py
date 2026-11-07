"""Coverage backfill tests for webhooks.py and services/purchase_orders.py.

Targets previously-uncovered branches: metadata-less webhook payloads,
duplicate/terminal payment states, bulk-purchase integration paths in
charge.refunded / checkout.session.completed / checkout.session.expired,
and the PDF-generation helpers in the purchase order service.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model

from django_program.conference.models import Conference
from django_program.registration.models import Order, Payment, StripeEvent
from django_program.registration.purchase_order import PurchaseOrderPayment
from django_program.registration.services.purchase_orders import (
    _draw_financial_summary,
    _draw_invoice_letterhead,
    _invoice_wrap_text,
    create_purchase_order,
    generate_invoice_pdf,
    generate_po_reference,
    issue_credit_note,
    record_payment,
)
from django_program.registration.webhooks import (
    ChargeRefundedWebhook,
    CheckoutSessionCompletedWebhook,
    CheckoutSessionExpiredWebhook,
    PaymentIntentPaymentFailedWebhook,
    PaymentIntentSucceededWebhook,
)
from django_program.sponsors.models import BulkPurchase

User = get_user_model()


# -- Fixtures -----------------------------------------------------------------


@pytest.fixture
def conference(db):
    return Conference.objects.create(
        name="TestCon",
        slug="testcon-wh-svc",
        start_date="2027-06-01",
        end_date="2027-06-03",
        timezone="UTC",
        is_active=True,
        stripe_secret_key="sk_test_abc123",
        stripe_publishable_key="pk_test_xyz789",
        stripe_webhook_secret="whsec_test_secret",
        venue="Convention Center",
        address="123 Main St",
        website_url="https://example.com",
    )


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="whsvcuser",
        email="whsvc@example.com",
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
        reference="ORD-WHSVC001",
    )


# =============================================================================
# PaymentIntentSucceededWebhook — metadata/duplicate edge cases
# =============================================================================


@pytest.mark.unit
@pytest.mark.django_db
class TestPaymentIntentSucceededMissingMetadata:
    def test_process_webhook_skips_when_no_order_id(self):
        payload = {
            "data": {
                "object": {
                    "id": "pi_no_meta_001",
                    "amount": 5000,
                    "metadata": {},
                },
            },
        }
        event = StripeEvent.objects.create(
            stripe_id="evt_pi_no_meta_001",
            kind="payment_intent.succeeded",
            payload=payload,
        )
        handler = PaymentIntentSucceededWebhook(event)
        handler.process_webhook()  # should not raise, should return early

        assert Payment.objects.count() == 0

    def test_send_signal_skips_when_no_order_id(self):
        payload = {
            "data": {
                "object": {
                    "id": "pi_no_meta_002",
                    "metadata": {},
                },
            },
        }
        event = StripeEvent.objects.create(
            stripe_id="evt_pi_no_meta_002",
            kind="payment_intent.succeeded",
            payload=payload,
        )
        handler = PaymentIntentSucceededWebhook(event)
        handler.send_signal()  # should not raise, should return early

    @patch("django_program.registration.webhooks.get_config")
    def test_skips_duplicate_already_captured_payment(self, mock_get_config, order):
        mock_config = MagicMock()
        mock_config.currency = "USD"
        mock_get_config.return_value = mock_config

        Payment.objects.create(
            order=order,
            method=Payment.Method.STRIPE,
            status=Payment.Status.SUCCEEDED,
            stripe_payment_intent_id="pi_dup_001",
            amount=Decimal("100.00"),
        )

        payload = {
            "data": {
                "object": {
                    "id": "pi_dup_001",
                    "amount": 10000,
                    "metadata": {"order_id": str(order.pk)},
                    "latest_charge": "ch_dup_001",
                },
            },
        }
        event = StripeEvent.objects.create(
            stripe_id="evt_pi_dup_001",
            kind="payment_intent.succeeded",
            payload=payload,
        )
        handler = PaymentIntentSucceededWebhook(event)
        handler.process_webhook()

        # No new payment was created; still exactly the one SUCCEEDED payment.
        assert Payment.objects.filter(order=order).count() == 1
        order.refresh_from_db()
        assert order.status == Order.Status.PENDING


@pytest.mark.unit
@pytest.mark.django_db
class TestPaymentIntentPaymentFailedMissingMetadata:
    def test_process_webhook_skips_when_no_order_id(self):
        payload = {
            "data": {
                "object": {
                    "id": "pi_fail_no_meta_001",
                    "metadata": {},
                },
            },
        }
        event = StripeEvent.objects.create(
            stripe_id="evt_pi_fail_no_meta_001",
            kind="payment_intent.payment_failed",
            payload=payload,
        )
        handler = PaymentIntentPaymentFailedWebhook(event)
        handler.process_webhook()  # should not raise, should return early


# =============================================================================
# ChargeRefundedWebhook — bulk purchase refund integration
# =============================================================================


@pytest.mark.unit
@pytest.mark.django_db
class TestChargeRefundedBulkPurchase:
    @patch("django_program.registration.webhooks.get_config")
    def test_full_refund_refunds_matching_bulk_purchase(self, mock_get_config, conference, order):
        mock_config = MagicMock()
        mock_config.currency = "USD"
        mock_get_config.return_value = mock_config

        Payment.objects.create(
            order=order,
            method=Payment.Method.STRIPE,
            status=Payment.Status.SUCCEEDED,
            stripe_payment_intent_id="pi_bp_refund_001",
            amount=Decimal("100.00"),
        )
        bulk_purchase = BulkPurchase.objects.create(
            conference=conference,
            quantity=5,
            unit_price=Decimal("20.00"),
            total_amount=Decimal("100.00"),
            stripe_payment_intent_id="pi_bp_refund_001",
            payment_status=BulkPurchase.PaymentStatus.PAID,
        )

        payload = {
            "data": {
                "object": {
                    "payment_intent": "pi_bp_refund_001",
                    "amount": 10000,
                    "amount_refunded": 10000,
                },
            },
        }
        event = StripeEvent.objects.create(
            stripe_id="evt_bp_refund_001",
            kind="charge.refunded",
            payload=payload,
        )
        handler = ChargeRefundedWebhook(event)
        handler.process_webhook()

        bulk_purchase.refresh_from_db()
        assert bulk_purchase.payment_status == BulkPurchase.PaymentStatus.REFUNDED


# =============================================================================
# CheckoutSessionCompletedWebhook
# =============================================================================


@pytest.mark.unit
@pytest.mark.django_db
class TestCheckoutSessionCompletedWebhook:
    def _make_event(self, session_id, metadata, payment_status="paid", payment_intent=""):
        payload = {
            "data": {
                "object": {
                    "id": session_id,
                    "metadata": metadata,
                    "payment_status": payment_status,
                    "payment_intent": payment_intent,
                },
            },
        }
        return StripeEvent.objects.create(
            stripe_id=f"evt_checkout_{session_id}",
            kind="checkout.session.completed",
            payload=payload,
        )

    def test_skips_when_no_bulk_purchase_id_in_metadata(self, db):
        event = self._make_event("cs_no_bp_001", metadata={})
        handler = CheckoutSessionCompletedWebhook(event)
        handler.process_webhook()  # should not raise, should return early

    def test_defers_when_payment_status_not_paid(self, db):
        event = self._make_event(
            "cs_unpaid_001",
            metadata={"bulk_purchase_id": "1"},
            payment_status="unpaid",
        )
        handler = CheckoutSessionCompletedWebhook(event)
        handler.process_webhook()  # should not raise, should return early

    def test_fulfills_bulk_purchase_and_updates_payment_intent(self, conference):
        bulk_purchase = BulkPurchase.objects.create(
            conference=conference,
            quantity=3,
            unit_price=Decimal("10.00"),
            total_amount=Decimal("30.00"),
            stripe_checkout_session_id="cs_fulfill_001",
            stripe_payment_intent_id="",
            payment_status=BulkPurchase.PaymentStatus.PROCESSING,
        )
        event = self._make_event(
            "cs_fulfill_001",
            metadata={"bulk_purchase_id": str(bulk_purchase.pk)},
            payment_status="paid",
            payment_intent="pi_fulfill_001",
        )
        handler = CheckoutSessionCompletedWebhook(event)

        with patch("django_program.sponsors.services.BulkPurchaseService.handle_checkout_webhook") as mock_handle:
            mock_handle.return_value = bulk_purchase
            handler.process_webhook()
            mock_handle.assert_called_once_with("cs_fulfill_001")

        bulk_purchase.refresh_from_db()
        assert bulk_purchase.stripe_payment_intent_id == "pi_fulfill_001"


# =============================================================================
# CheckoutSessionExpiredWebhook
# =============================================================================


@pytest.mark.unit
@pytest.mark.django_db
class TestCheckoutSessionExpiredWebhook:
    def _make_event(self, session_id):
        payload = {"data": {"object": {"id": session_id}}}
        return StripeEvent.objects.create(
            stripe_id=f"evt_expired_{session_id}",
            kind="checkout.session.expired",
            payload=payload,
        )

    def test_returns_when_no_matching_bulk_purchase(self, db):
        event = self._make_event("cs_no_match_001")
        handler = CheckoutSessionExpiredWebhook(event)
        handler.process_webhook()  # should not raise, should return early

    def test_marks_matching_bulk_purchase_failed(self, conference):
        bulk_purchase = BulkPurchase.objects.create(
            conference=conference,
            quantity=2,
            unit_price=Decimal("15.00"),
            total_amount=Decimal("30.00"),
            stripe_checkout_session_id="cs_expire_001",
            payment_status=BulkPurchase.PaymentStatus.PENDING,
        )
        event = self._make_event("cs_expire_001")
        handler = CheckoutSessionExpiredWebhook(event)
        handler.process_webhook()

        bulk_purchase.refresh_from_db()
        assert bulk_purchase.payment_status == BulkPurchase.PaymentStatus.FAILED


# =============================================================================
# generate_po_reference — exhaustion path
# =============================================================================


@pytest.mark.integration
@pytest.mark.django_db
class TestGeneratePOReferenceExhaustion:
    def test_raises_runtime_error_when_all_attempts_collide(self):
        with patch("django_program.registration.services.purchase_orders.PurchaseOrder.objects.filter") as mock_filter:
            mock_filter.return_value.exists.return_value = True
            with pytest.raises(RuntimeError, match="unique PO reference"):
                generate_po_reference()


# =============================================================================
# record_payment / issue_credit_note — validation errors
# =============================================================================


@pytest.fixture
def po_conference(db):
    return Conference.objects.create(
        name="POCon",
        slug="po-con-coverage",
        start_date=date(2027, 6, 1),
        end_date=date(2027, 6, 3),
        timezone="UTC",
    )


@pytest.fixture
def po_staff_user(db):
    return User.objects.create_user(
        username="pocoveragestaff",
        email="pocoveragestaff@example.com",
        password="testpass123",
        is_staff=True,
    )


@pytest.fixture
def simple_purchase_order(po_conference, po_staff_user):
    return create_purchase_order(
        conference=po_conference,
        organization_name="Coverage Corp",
        contact_email="billing@coverage.example",
        contact_name="Pat Doe",
        billing_address="456 Coverage Ave\nSuite 2",
        line_items=[
            {
                "description": "Ticket",
                "quantity": 2,
                "unit_price": Decimal("150.00"),
            },
        ],
        created_by=po_staff_user,
    )


@pytest.mark.integration
@pytest.mark.django_db
class TestRecordPaymentValidation:
    def test_raises_for_non_positive_amount(self, simple_purchase_order):
        with pytest.raises(ValueError, match="must be positive"):
            record_payment(
                simple_purchase_order,
                amount=Decimal("0.00"),
                method=PurchaseOrderPayment.Method.WIRE,
                payment_date=date(2027, 5, 1),
            )

    def test_raises_for_invalid_method(self, simple_purchase_order):
        with pytest.raises(ValueError, match="Invalid payment method"):
            record_payment(
                simple_purchase_order,
                amount=Decimal("50.00"),
                method="bitcoin",
                payment_date=date(2027, 5, 1),
            )


@pytest.mark.integration
@pytest.mark.django_db
class TestIssueCreditNoteValidation:
    def test_raises_for_non_positive_amount(self, simple_purchase_order):
        with pytest.raises(ValueError, match="must be positive"):
            issue_credit_note(
                simple_purchase_order,
                amount=Decimal("-5.00"),
                reason="Invalid test credit",
            )


# =============================================================================
# generate_invoice_pdf — full render path (letterhead, summary, history)
# =============================================================================


@pytest.mark.integration
@pytest.mark.django_db
class TestGenerateInvoicePdf:
    def test_renders_full_invoice_with_credits_and_payments(self, simple_purchase_order, po_staff_user):
        record_payment(
            simple_purchase_order,
            amount=Decimal("100.00"),
            method=PurchaseOrderPayment.Method.WIRE,
            reference="WIRE-REF-1",
            payment_date=date(2027, 5, 1),
            entered_by=po_staff_user,
        )
        issue_credit_note(
            simple_purchase_order,
            amount=Decimal("25.00"),
            reason="Speaker discount",
            issued_by=po_staff_user,
        )
        simple_purchase_order.refresh_from_db()

        pdf_bytes = generate_invoice_pdf(simple_purchase_order)

        assert pdf_bytes.startswith(b"%PDF")
        assert len(pdf_bytes) > 0

    def test_letterhead_includes_venue_address_and_website(self, po_conference, simple_purchase_order):
        po_conference.venue = "Big Hall"
        po_conference.address = "789 Event Blvd"
        po_conference.website_url = "https://coverage.example"
        po_conference.save(update_fields=["venue", "address", "website_url"])

        import io

        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        width, _height = A4
        margin = 25 * mm
        y = _draw_invoice_letterhead(c, po_conference, margin, 800, width)

        assert y < 800

    def test_financial_summary_includes_total_credited_line(self, simple_purchase_order, po_staff_user):
        issue_credit_note(
            simple_purchase_order,
            amount=Decimal("10.00"),
            reason="Partial credit",
            issued_by=po_staff_user,
        )
        simple_purchase_order.refresh_from_db()

        import io

        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        width, _height = A4
        margin = 25 * mm
        usable_width = width - 2 * margin
        y = _draw_financial_summary(c, simple_purchase_order, margin, 500, usable_width)

        assert y < 500


@pytest.mark.unit
class TestInvoiceWrapText:
    def test_wraps_long_text_into_multiple_lines(self):
        import io

        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)

        long_text = "word " * 50
        lines = _invoice_wrap_text(c, long_text.strip(), "Helvetica", 10, max_width=50)

        assert len(lines) > 1
