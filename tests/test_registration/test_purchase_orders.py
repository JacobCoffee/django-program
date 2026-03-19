"""Tests for purchase order models and service functions."""

import re
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from django_program.conference.models import Conference
from django_program.registration.models import AddOn, TicketType
from django_program.registration.purchase_order import (
    PurchaseOrder,
    PurchaseOrderCreditNote,
    PurchaseOrderPayment,
)
from django_program.registration.services.purchase_orders import (
    cancel_purchase_order,
    create_purchase_order,
    generate_po_reference,
    issue_credit_note,
    record_payment,
    update_po_status,
)

User = get_user_model()


# -- Fixtures -----------------------------------------------------------------


@pytest.fixture
def conference() -> Conference:
    return Conference.objects.create(
        name="TestCon",
        slug="testcon-po",
        start_date=date(2027, 6, 1),
        end_date=date(2027, 6, 3),
        timezone="UTC",
    )


@pytest.fixture
def user() -> User:
    return User.objects.create_user(
        username="pouser",
        email="po@example.com",
        password="testpass123",
    )


@pytest.fixture
def staff_user() -> User:
    return User.objects.create_user(
        username="postaffuser",
        email="postaff@example.com",
        password="testpass123",
        is_staff=True,
    )


@pytest.fixture
def ticket_type(conference: Conference) -> TicketType:
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
def addon(conference: Conference) -> AddOn:
    return AddOn.objects.create(
        conference=conference,
        name="Workshop",
        slug="workshop",
        price=Decimal("75.00"),
        is_active=True,
    )


@pytest.fixture
def sample_line_items(ticket_type: TicketType, addon: AddOn) -> list[dict]:
    return [
        {
            "description": "Corporate Ticket",
            "quantity": 5,
            "unit_price": Decimal("250.00"),
            "ticket_type": ticket_type,
        },
        {
            "description": "Workshop Add-On",
            "quantity": 3,
            "unit_price": Decimal("75.00"),
            "addon": addon,
        },
    ]


@pytest.fixture
def purchase_order(conference: Conference, staff_user: User, sample_line_items: list[dict]) -> PurchaseOrder:
    return create_purchase_order(
        conference=conference,
        organization_name="Acme Corp",
        contact_email="billing@acme.com",
        contact_name="Jane Doe",
        billing_address="123 Corporate Ave",
        line_items=sample_line_items,
        notes="Test PO",
        created_by=staff_user,
    )


# =============================================================================
# Model tests
# =============================================================================


@pytest.mark.unit
@pytest.mark.django_db
class TestPurchaseOrderModel:
    def test_str_returns_reference_and_status(self, purchase_order: PurchaseOrder) -> None:
        result = str(purchase_order)
        assert purchase_order.reference in result
        assert "draft" in result

    def test_balance_due_no_payments(self, purchase_order: PurchaseOrder) -> None:
        # 5 * 250 + 3 * 75 = 1475
        assert purchase_order.total == Decimal("1475.00")
        assert purchase_order.balance_due == Decimal("1475.00")

    def test_balance_due_with_payment(self, purchase_order: PurchaseOrder) -> None:
        PurchaseOrderPayment.objects.create(
            purchase_order=purchase_order,
            amount=Decimal("500.00"),
            method=PurchaseOrderPayment.Method.WIRE,
            payment_date=date(2027, 5, 1),
        )
        assert purchase_order.balance_due == Decimal("975.00")

    def test_balance_due_with_credit(self, purchase_order: PurchaseOrder) -> None:
        PurchaseOrderCreditNote.objects.create(
            purchase_order=purchase_order,
            amount=Decimal("200.00"),
            reason="Adjustment",
        )
        assert purchase_order.balance_due == Decimal("1275.00")

    def test_balance_due_with_payment_and_credit(self, purchase_order: PurchaseOrder) -> None:
        PurchaseOrderPayment.objects.create(
            purchase_order=purchase_order,
            amount=Decimal("1000.00"),
            method=PurchaseOrderPayment.Method.ACH,
            payment_date=date(2027, 5, 1),
        )
        PurchaseOrderCreditNote.objects.create(
            purchase_order=purchase_order,
            amount=Decimal("100.00"),
            reason="Partial cancellation",
        )
        # 1475 - 1000 - 100 = 375
        assert purchase_order.balance_due == Decimal("375.00")

    def test_total_paid_sums_payments(self, purchase_order: PurchaseOrder) -> None:
        PurchaseOrderPayment.objects.create(
            purchase_order=purchase_order,
            amount=Decimal("300.00"),
            method=PurchaseOrderPayment.Method.WIRE,
            payment_date=date(2027, 5, 1),
        )
        PurchaseOrderPayment.objects.create(
            purchase_order=purchase_order,
            amount=Decimal("200.00"),
            method=PurchaseOrderPayment.Method.CHECK,
            payment_date=date(2027, 5, 15),
        )
        assert purchase_order.total_paid == Decimal("500.00")

    def test_total_paid_zero_when_no_payments(self, purchase_order: PurchaseOrder) -> None:
        assert purchase_order.total_paid == Decimal("0.00")


@pytest.mark.unit
@pytest.mark.django_db
class TestPurchaseOrderLineItemModel:
    def test_str_returns_quantity_and_description(self, purchase_order: PurchaseOrder) -> None:
        item = purchase_order.line_items.first()
        assert item is not None
        result = str(item)
        assert "Corporate Ticket" in result
        assert "5" in result


@pytest.mark.unit
@pytest.mark.django_db
class TestPurchaseOrderPaymentModel:
    def test_str_returns_method_amount_and_date(self, purchase_order: PurchaseOrder) -> None:
        payment = PurchaseOrderPayment.objects.create(
            purchase_order=purchase_order,
            amount=Decimal("500.00"),
            method=PurchaseOrderPayment.Method.WIRE,
            payment_date=date(2027, 5, 1),
        )
        result = str(payment)
        assert "500.00" in result
        assert "Wire Transfer" in result
        assert "2027-05-01" in result


@pytest.mark.unit
@pytest.mark.django_db
class TestPurchaseOrderCreditNoteModel:
    def test_str_returns_amount_and_reason(self, purchase_order: PurchaseOrder) -> None:
        cn = PurchaseOrderCreditNote.objects.create(
            purchase_order=purchase_order,
            amount=Decimal("100.00"),
            reason="Speaker discount applied",
        )
        result = str(cn)
        assert "100.00" in result
        assert "Speaker discount" in result


# =============================================================================
# Service tests
# =============================================================================


@pytest.mark.integration
@pytest.mark.django_db
class TestGeneratePOReference:
    def test_returns_po_prefix(self) -> None:
        ref = generate_po_reference()
        assert ref.startswith("PO-")

    def test_suffix_is_6_alphanumeric_chars(self) -> None:
        ref = generate_po_reference()
        suffix = ref.split("-", 1)[1]
        assert len(suffix) == 6
        assert re.match(r"^[A-Z0-9]+$", suffix)

    def test_generates_unique_references(self) -> None:
        refs = {generate_po_reference() for _ in range(20)}
        assert len(refs) == 20


@pytest.mark.integration
@pytest.mark.django_db
class TestCreatePurchaseOrder:
    def test_creates_po_with_line_items(
        self,
        conference: Conference,
        staff_user: User,
        sample_line_items: list[dict],
    ) -> None:
        po = create_purchase_order(
            conference=conference,
            organization_name="Widgets Inc",
            contact_email="billing@widgets.com",
            contact_name="Bob Smith",
            line_items=sample_line_items,
            created_by=staff_user,
        )

        assert po.pk is not None
        assert po.organization_name == "Widgets Inc"
        assert po.contact_email == "billing@widgets.com"
        assert po.line_items.count() == 2

    def test_computes_correct_subtotal_and_total(
        self,
        conference: Conference,
        sample_line_items: list[dict],
    ) -> None:
        po = create_purchase_order(
            conference=conference,
            organization_name="TestOrg",
            contact_email="test@org.com",
            contact_name="Tester",
            line_items=sample_line_items,
        )
        # 5 * 250 + 3 * 75 = 1250 + 225 = 1475
        assert po.subtotal == Decimal("1475.00")
        assert po.total == Decimal("1475.00")

    def test_reference_is_assigned(
        self,
        conference: Conference,
        sample_line_items: list[dict],
    ) -> None:
        po = create_purchase_order(
            conference=conference,
            organization_name="RefOrg",
            contact_email="ref@org.com",
            contact_name="Ref Person",
            line_items=sample_line_items,
        )
        assert po.reference.startswith("PO-")
        assert len(po.reference) == 9  # "PO-" + 6 chars

    def test_status_is_draft(
        self,
        conference: Conference,
        sample_line_items: list[dict],
    ) -> None:
        po = create_purchase_order(
            conference=conference,
            organization_name="DraftOrg",
            contact_email="draft@org.com",
            contact_name="Drafter",
            line_items=sample_line_items,
        )
        assert po.status == PurchaseOrder.Status.DRAFT

    def test_empty_line_items_creates_zero_total(
        self,
        conference: Conference,
    ) -> None:
        po = create_purchase_order(
            conference=conference,
            organization_name="EmptyOrg",
            contact_email="empty@org.com",
            contact_name="Empty Person",
            line_items=[],
        )
        assert po.subtotal == Decimal("0.00")
        assert po.total == Decimal("0.00")
        assert po.line_items.count() == 0

    def test_line_items_snapshot_pricing(
        self,
        conference: Conference,
        ticket_type: TicketType,
    ) -> None:
        items = [
            {
                "description": "Ticket",
                "quantity": 2,
                "unit_price": Decimal("300.00"),
                "ticket_type": ticket_type,
            },
        ]
        po = create_purchase_order(
            conference=conference,
            organization_name="SnapshotOrg",
            contact_email="snap@org.com",
            contact_name="Snap",
            line_items=items,
        )
        line = po.line_items.first()
        assert line is not None
        assert line.unit_price == Decimal("300.00")
        assert line.line_total == Decimal("600.00")
        assert line.ticket_type == ticket_type


@pytest.mark.integration
@pytest.mark.django_db
class TestRecordPayment:
    def test_partial_payment_sets_partially_paid(self, purchase_order: PurchaseOrder, staff_user: User) -> None:
        record_payment(
            purchase_order,
            amount=Decimal("500.00"),
            method=PurchaseOrderPayment.Method.WIRE,
            payment_date=date(2027, 5, 1),
            entered_by=staff_user,
        )
        purchase_order.refresh_from_db()
        assert purchase_order.status == PurchaseOrder.Status.PARTIALLY_PAID

    def test_full_payment_sets_paid(self, purchase_order: PurchaseOrder) -> None:
        record_payment(
            purchase_order,
            amount=Decimal("1475.00"),
            method=PurchaseOrderPayment.Method.ACH,
            payment_date=date(2027, 5, 1),
        )
        purchase_order.refresh_from_db()
        assert purchase_order.status == PurchaseOrder.Status.PAID

    def test_overpayment_sets_overpaid(self, purchase_order: PurchaseOrder) -> None:
        record_payment(
            purchase_order,
            amount=Decimal("2000.00"),
            method=PurchaseOrderPayment.Method.STRIPE,
            payment_date=date(2027, 5, 1),
        )
        purchase_order.refresh_from_db()
        assert purchase_order.status == PurchaseOrder.Status.OVERPAID

    def test_multiple_partial_payments_then_full(self, purchase_order: PurchaseOrder) -> None:
        record_payment(
            purchase_order,
            amount=Decimal("500.00"),
            method=PurchaseOrderPayment.Method.WIRE,
            payment_date=date(2027, 5, 1),
        )
        purchase_order.refresh_from_db()
        assert purchase_order.status == PurchaseOrder.Status.PARTIALLY_PAID

        record_payment(
            purchase_order,
            amount=Decimal("975.00"),
            method=PurchaseOrderPayment.Method.CHECK,
            payment_date=date(2027, 5, 15),
        )
        purchase_order.refresh_from_db()
        assert purchase_order.status == PurchaseOrder.Status.PAID

    def test_payment_creates_record(self, purchase_order: PurchaseOrder, staff_user: User) -> None:
        payment = record_payment(
            purchase_order,
            amount=Decimal("750.00"),
            method=PurchaseOrderPayment.Method.WIRE,
            reference="WIRE-12345",
            payment_date=date(2027, 5, 1),
            entered_by=staff_user,
            note="First installment",
        )
        assert payment.pk is not None
        assert payment.amount == Decimal("750.00")
        assert payment.reference == "WIRE-12345"
        assert payment.entered_by == staff_user
        assert payment.note == "First installment"


@pytest.mark.integration
@pytest.mark.django_db
class TestIssueCreditNote:
    def test_creates_credit_note(self, purchase_order: PurchaseOrder, staff_user: User) -> None:
        cn = issue_credit_note(
            purchase_order,
            amount=Decimal("200.00"),
            reason="Speaker comp adjustment",
            issued_by=staff_user,
        )
        assert cn.pk is not None
        assert cn.amount == Decimal("200.00")
        assert cn.reason == "Speaker comp adjustment"
        assert cn.issued_by == staff_user

    def test_credit_reduces_balance(self, purchase_order: PurchaseOrder) -> None:
        issue_credit_note(
            purchase_order,
            amount=Decimal("475.00"),
            reason="Discount",
        )
        purchase_order.refresh_from_db()
        # 1475 - 475 = 1000
        assert purchase_order.balance_due == Decimal("1000.00")

    def test_credit_plus_payment_marks_paid(self, purchase_order: PurchaseOrder) -> None:
        issue_credit_note(
            purchase_order,
            amount=Decimal("475.00"),
            reason="Sponsor comp",
        )
        record_payment(
            purchase_order,
            amount=Decimal("1000.00"),
            method=PurchaseOrderPayment.Method.WIRE,
            payment_date=date(2027, 5, 1),
        )
        purchase_order.refresh_from_db()
        assert purchase_order.status == PurchaseOrder.Status.PAID
        assert purchase_order.balance_due == Decimal("0.00")


@pytest.mark.integration
@pytest.mark.django_db
class TestUpdatePOStatus:
    def test_draft_stays_draft_with_no_payments(self, purchase_order: PurchaseOrder) -> None:
        update_po_status(purchase_order)
        purchase_order.refresh_from_db()
        assert purchase_order.status == PurchaseOrder.Status.DRAFT

    def test_sent_stays_sent_with_no_payments(self, purchase_order: PurchaseOrder) -> None:
        purchase_order.status = PurchaseOrder.Status.SENT
        purchase_order.save(update_fields=["status"])
        update_po_status(purchase_order)
        purchase_order.refresh_from_db()
        assert purchase_order.status == PurchaseOrder.Status.SENT

    def test_cancelled_is_not_changed(self, purchase_order: PurchaseOrder) -> None:
        purchase_order.status = PurchaseOrder.Status.CANCELLED
        purchase_order.save(update_fields=["status"])
        # Record a payment directly (bypassing service)
        PurchaseOrderPayment.objects.create(
            purchase_order=purchase_order,
            amount=Decimal("1475.00"),
            method=PurchaseOrderPayment.Method.WIRE,
            payment_date=date(2027, 5, 1),
        )
        update_po_status(purchase_order)
        purchase_order.refresh_from_db()
        assert purchase_order.status == PurchaseOrder.Status.CANCELLED


@pytest.mark.integration
@pytest.mark.django_db
class TestCancelPurchaseOrder:
    def test_cancel_draft_po(self, purchase_order: PurchaseOrder) -> None:
        cancel_purchase_order(purchase_order)
        purchase_order.refresh_from_db()
        assert purchase_order.status == PurchaseOrder.Status.CANCELLED

    def test_cancel_sent_po(self, purchase_order: PurchaseOrder) -> None:
        purchase_order.status = PurchaseOrder.Status.SENT
        purchase_order.save(update_fields=["status"])
        cancel_purchase_order(purchase_order)
        purchase_order.refresh_from_db()
        assert purchase_order.status == PurchaseOrder.Status.CANCELLED

    def test_cancel_paid_po_still_cancels(self, purchase_order: PurchaseOrder) -> None:
        # The service unconditionally sets CANCELLED (no guard against paid POs)
        record_payment(
            purchase_order,
            amount=Decimal("1475.00"),
            method=PurchaseOrderPayment.Method.WIRE,
            payment_date=date(2027, 5, 1),
        )
        purchase_order.refresh_from_db()
        assert purchase_order.status == PurchaseOrder.Status.PAID

        cancel_purchase_order(purchase_order)
        purchase_order.refresh_from_db()
        assert purchase_order.status == PurchaseOrder.Status.CANCELLED

    def test_cancelled_po_ignores_status_updates(self, purchase_order: PurchaseOrder) -> None:
        cancel_purchase_order(purchase_order)
        # Attempting to update status after cancellation is a no-op
        update_po_status(purchase_order)
        purchase_order.refresh_from_db()
        assert purchase_order.status == PurchaseOrder.Status.CANCELLED

    def test_cancel_preserves_payment_records(self, purchase_order: PurchaseOrder) -> None:
        record_payment(
            purchase_order,
            amount=Decimal("500.00"),
            method=PurchaseOrderPayment.Method.WIRE,
            payment_date=date(2027, 5, 1),
        )
        cancel_purchase_order(purchase_order)
        assert purchase_order.payments.count() == 1


# =============================================================================
# Admin registration tests
# =============================================================================


@pytest.mark.integration
@pytest.mark.django_db
class TestPurchaseOrderAdmin:
    def test_admin_list_display_fields(self) -> None:
        from django_program.registration.admin import PurchaseOrderAdmin

        expected_fields = {
            "reference",
            "organization_name",
            "conference",
            "status",
            "total",
            "balance_due_display",
            "created_at",
        }
        assert set(PurchaseOrderAdmin.list_display) == expected_fields

    def test_admin_has_search_fields(self) -> None:
        from django_program.registration.admin import PurchaseOrderAdmin

        assert "reference" in PurchaseOrderAdmin.search_fields
        assert "organization_name" in PurchaseOrderAdmin.search_fields
        assert "contact_email" in PurchaseOrderAdmin.search_fields

    def test_admin_has_readonly_money_fields(self) -> None:
        from django_program.registration.admin import PurchaseOrderAdmin

        assert "subtotal" in PurchaseOrderAdmin.readonly_fields
        assert "total" in PurchaseOrderAdmin.readonly_fields
        assert "reference" in PurchaseOrderAdmin.readonly_fields
