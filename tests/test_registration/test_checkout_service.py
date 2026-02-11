"""Tests for the CheckoutService in django_program.registration.services.checkout."""

import json
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from django_program.conference.models import Conference
from django_program.registration.models import (
    AddOn,
    Cart,
    Credit,
    Order,
    OrderLineItem,
    Payment,
    TicketType,
    Voucher,
)
from django_program.registration.services.cart import CartService, CartSummary, LineItemSummary
from django_program.registration.services.checkout import (
    CheckoutService,
    _expire_stale_pending_orders,
    _increment_voucher_usage,
)
from django_program.registration.signals import order_paid

User = get_user_model()


# -- Helpers ------------------------------------------------------------------


def _make_order(*, conference, user, status, reference=None):
    return Order.objects.create(
        conference=conference,
        user=user,
        status=status,
        subtotal=Decimal("0.00"),
        total=Decimal("0.00"),
        reference=reference or f"ORD-{uuid4().hex[:8].upper()}",
    )


# -- Fixtures -----------------------------------------------------------------


@pytest.fixture
def conference():
    return Conference.objects.create(
        name="TestCon",
        slug="testcon-checkout",
        start_date=date(2027, 6, 1),
        end_date=date(2027, 6, 3),
        timezone="UTC",
    )


@pytest.fixture
def user():
    return User.objects.create_user(
        username="checkoutuser",
        email="checkout@example.com",
        password="testpass123",
    )


@pytest.fixture
def other_user():
    return User.objects.create_user(
        username="othercheckoutuser",
        email="othercheckout@example.com",
        password="testpass123",
    )


@pytest.fixture
def ticket_type(conference):
    return TicketType.objects.create(
        conference=conference,
        name="General",
        slug="general",
        price=Decimal("100.00"),
        total_quantity=0,
        limit_per_user=10,
        is_active=True,
    )


@pytest.fixture
def limited_ticket(conference):
    return TicketType.objects.create(
        conference=conference,
        name="Limited",
        slug="limited",
        price=Decimal("200.00"),
        total_quantity=5,
        limit_per_user=3,
        is_active=True,
    )


@pytest.fixture
def cart(conference, user):
    return Cart.objects.create(
        user=user,
        conference=conference,
        status=Cart.Status.OPEN,
        expires_at=timezone.now() + timedelta(minutes=30),
    )


@pytest.fixture
def cart_with_ticket(cart, ticket_type):
    CartService.add_ticket(cart, ticket_type, qty=1)
    return cart


# =============================================================================
# TestCheckout
# =============================================================================


@pytest.mark.django_db
class TestCheckout:
    def test_creates_order_from_cart(self, cart_with_ticket, ticket_type):
        order = CheckoutService.checkout(
            cart_with_ticket,
            billing_name="Alice Smith",
            billing_email="alice@example.com",
        )

        assert order.status == Order.Status.PENDING
        assert order.conference == cart_with_ticket.conference
        assert order.user == cart_with_ticket.user
        assert order.subtotal == Decimal("100.00")
        assert order.total == Decimal("100.00")
        assert order.discount_amount == Decimal("0.00")
        assert order.billing_name == "Alice Smith"
        assert order.billing_email == "alice@example.com"
        assert order.reference.startswith("ORD-")
        assert len(order.reference) == 12  # ORD- + 8 chars
        assert order.hold_expires_at is not None

    def test_uses_custom_reference_prefix(self, cart_with_ticket, settings):
        settings.DJANGO_PROGRAM = {"order_reference_prefix": "PYCON"}

        order = CheckoutService.checkout(cart_with_ticket)

        assert order.reference.startswith("PYCON-")
        assert len(order.reference) == 14  # PYCON- + 8 chars

    def test_creates_order_line_items(self, cart, ticket_type, conference):
        CartService.add_ticket(cart, ticket_type, qty=2)
        addon = AddOn.objects.create(
            conference=conference,
            name="Workshop",
            slug="workshop",
            price=Decimal("50.00"),
            is_active=True,
        )
        CartService.add_addon(cart, addon, qty=1)

        order = CheckoutService.checkout(cart)

        lines = list(order.line_items.all())
        assert len(lines) == 2

        ticket_line = next(li for li in lines if li.ticket_type == ticket_type)
        assert ticket_line.quantity == 2
        assert ticket_line.unit_price == Decimal("100.00")
        assert ticket_line.description == "General"

        addon_line = next(li for li in lines if li.addon == addon)
        assert addon_line.quantity == 1
        assert addon_line.unit_price == Decimal("50.00")
        assert addon_line.description == "Workshop"

    def test_pending_order_reserves_inventory(self, conference, user, other_user):
        limited = TicketType.objects.create(
            conference=conference,
            name="Reserved",
            slug="reserved",
            price=Decimal("100.00"),
            total_quantity=2,
            limit_per_user=10,
            is_active=True,
        )
        cart1 = Cart.objects.create(
            user=user,
            conference=conference,
            status=Cart.Status.OPEN,
            expires_at=timezone.now() + timedelta(minutes=30),
        )
        CartService.add_ticket(cart1, limited, qty=2)
        order = CheckoutService.checkout(cart1)
        assert order.status == Order.Status.PENDING
        assert order.hold_expires_at is not None

        cart2 = Cart.objects.create(
            user=other_user,
            conference=conference,
            status=Cart.Status.OPEN,
            expires_at=timezone.now() + timedelta(minutes=30),
        )
        with pytest.raises(ValidationError, match=r"not available|remaining"):
            CartService.add_ticket(cart2, limited, qty=1)

    def test_expired_pending_order_releases_inventory(self, conference, user, other_user):
        limited = TicketType.objects.create(
            conference=conference,
            name="Reserved",
            slug="reserved-expired",
            price=Decimal("100.00"),
            total_quantity=2,
            limit_per_user=10,
            is_active=True,
        )
        cart1 = Cart.objects.create(
            user=user,
            conference=conference,
            status=Cart.Status.OPEN,
            expires_at=timezone.now() + timedelta(minutes=30),
        )
        CartService.add_ticket(cart1, limited, qty=2)
        order = CheckoutService.checkout(cart1)
        order.hold_expires_at = timezone.now() - timedelta(minutes=1)
        order.save(update_fields=["hold_expires_at", "updated_at"])

        cart2 = Cart.objects.create(
            user=other_user,
            conference=conference,
            status=Cart.Status.OPEN,
            expires_at=timezone.now() + timedelta(minutes=30),
        )
        item = CartService.add_ticket(cart2, limited, qty=1)
        assert item.quantity == 1

    def test_marks_cart_as_checked_out(self, cart_with_ticket):
        CheckoutService.checkout(cart_with_ticket)

        cart_with_ticket.refresh_from_db()
        assert cart_with_ticket.status == Cart.Status.CHECKED_OUT

    def test_snapshots_voucher_on_order(self, cart, ticket_type, conference):
        CartService.add_ticket(cart, ticket_type, qty=1)
        Voucher.objects.create(
            conference=conference,
            code="SAVE20",
            voucher_type=Voucher.VoucherType.PERCENTAGE,
            discount_value=Decimal("20.00"),
            max_uses=10,
            is_active=True,
        )
        CartService.apply_voucher(cart, "SAVE20")

        order = CheckoutService.checkout(cart)

        assert order.voucher_code == "SAVE20"
        details = json.loads(order.voucher_details)
        assert details["code"] == "SAVE20"
        assert details["voucher_type"] == "percentage"
        assert details["discount_value"] == "20.00"

    def test_increments_voucher_times_used(self, cart, ticket_type, conference):
        CartService.add_ticket(cart, ticket_type, qty=1)
        voucher = Voucher.objects.create(
            conference=conference,
            code="ONCE",
            voucher_type=Voucher.VoucherType.COMP,
            max_uses=5,
            times_used=2,
            is_active=True,
        )
        CartService.apply_voucher(cart, "ONCE")

        CheckoutService.checkout(cart)

        voucher.refresh_from_db()
        assert voucher.times_used == 3

    def test_applies_voucher_discount_to_order(self, cart, ticket_type, conference):
        CartService.add_ticket(cart, ticket_type, qty=1)  # $100
        Voucher.objects.create(
            conference=conference,
            code="HALF",
            voucher_type=Voucher.VoucherType.PERCENTAGE,
            discount_value=Decimal("50.00"),
            max_uses=10,
            is_active=True,
        )
        CartService.apply_voucher(cart, "HALF")

        order = CheckoutService.checkout(cart)

        assert order.subtotal == Decimal("100.00")
        assert order.discount_amount == Decimal("50.00")
        assert order.total == Decimal("50.00")

    def test_rejects_checkout_when_voucher_becomes_inactive(self, cart, ticket_type, conference):
        CartService.add_ticket(cart, ticket_type, qty=1)
        voucher = Voucher.objects.create(
            conference=conference,
            code="SAVE10",
            voucher_type=Voucher.VoucherType.PERCENTAGE,
            discount_value=Decimal("10.00"),
            max_uses=10,
            is_active=True,
        )
        CartService.apply_voucher(cart, "SAVE10")
        voucher.is_active = False
        voucher.save(update_fields=["is_active", "updated_at"])

        with pytest.raises(ValidationError, match="no longer valid"):
            CheckoutService.checkout(cart)

    def test_rejects_checkout_when_voucher_usage_limit_reached(self, cart, ticket_type, conference):
        CartService.add_ticket(cart, ticket_type, qty=1)
        voucher = Voucher.objects.create(
            conference=conference,
            code="LIMIT1",
            voucher_type=Voucher.VoucherType.COMP,
            discount_value=Decimal("0.00"),
            max_uses=1,
            is_active=True,
        )
        CartService.apply_voucher(cart, "LIMIT1")
        Voucher.objects.filter(pk=voucher.pk).update(times_used=1)

        with pytest.raises(ValidationError, match="no longer valid"):
            CheckoutService.checkout(cart)

    def test_retries_on_reference_collision(self, cart_with_ticket):
        """IntegrityError on duplicate reference triggers retry with new reference."""
        real_create = Order.objects.create
        call_count = 0

        def create_with_collision(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise IntegrityError("duplicate key")
            return real_create(**kwargs)

        with patch.object(Order.objects, "create", side_effect=create_with_collision):
            order = CheckoutService.checkout(cart_with_ticket)

        assert order.status == Order.Status.PENDING
        assert call_count == 2

    def test_raises_after_max_reference_retries(self, cart_with_ticket):
        """IntegrityError is re-raised after exhausting retry attempts."""
        with patch.object(Order.objects, "create", side_effect=IntegrityError("duplicate key")):
            with pytest.raises(IntegrityError):
                CheckoutService.checkout(cart_with_ticket)

    def test_voucher_race_condition_at_update(self, conference, user):
        """Voucher passes is_valid in-memory but DB update returns 0."""

        voucher = Voucher.objects.create(
            conference=conference,
            code="RACE",
            voucher_type=Voucher.VoucherType.PERCENTAGE,
            discount_value=Decimal("10.00"),
            max_uses=10,
            is_active=True,
        )
        # Deactivate in DB so the atomic update filter returns 0
        Voucher.objects.filter(pk=voucher.pk).update(is_active=False)

        with pytest.raises(ValidationError, match="no longer valid"):
            _increment_voucher_usage(voucher=voucher, now=timezone.now())

    def test_revalidates_addon_available_from_at_checkout(self, cart, conference):
        addon = AddOn.objects.create(
            conference=conference,
            name="Future Swag",
            slug="future-swag",
            price=Decimal("10.00"),
            is_active=True,
        )
        CartService.add_addon(cart, addon, qty=1)

        addon.available_from = timezone.now() + timedelta(days=30)
        addon.save(update_fields=["available_from", "updated_at"])

        with pytest.raises(ValidationError, match="not yet available"):
            CheckoutService.checkout(cart)

    def test_revalidates_addon_available_until_at_checkout(self, cart, conference):
        addon = AddOn.objects.create(
            conference=conference,
            name="Expired Swag",
            slug="expired-swag",
            price=Decimal("10.00"),
            is_active=True,
        )
        CartService.add_addon(cart, addon, qty=1)

        addon.available_until = timezone.now() - timedelta(days=1)
        addon.save(update_fields=["available_until", "updated_at"])

        with pytest.raises(ValidationError, match="no longer available"):
            CheckoutService.checkout(cart)

    def test_rejects_non_open_cart(self, cart_with_ticket):
        cart_with_ticket.status = Cart.Status.CHECKED_OUT
        cart_with_ticket.save(update_fields=["status", "updated_at"])

        with pytest.raises(ValidationError, match="Only open carts"):
            CheckoutService.checkout(cart_with_ticket)

    def test_rejects_expired_cart(self, cart_with_ticket):
        cart_with_ticket.expires_at = timezone.now() - timedelta(minutes=1)
        cart_with_ticket.save(update_fields=["expires_at", "updated_at"])

        with pytest.raises(ValidationError, match="expired"):
            CheckoutService.checkout(cart_with_ticket)

    def test_rejects_empty_cart(self, cart):
        with pytest.raises(ValidationError, match="empty"):
            CheckoutService.checkout(cart)

    def test_revalidates_stock_at_checkout(self, cart, limited_ticket, user, conference):
        CartService.add_ticket(cart, limited_ticket, qty=2)

        # Sell 4 of 5 via another order after cart was populated, leaving 1 remaining
        paid = _make_order(conference=conference, user=user, status=Order.Status.PAID)
        OrderLineItem.objects.create(
            order=paid,
            ticket_type=limited_ticket,
            description="Sold",
            quantity=4,
            unit_price=Decimal("200.00"),
            line_total=Decimal("800.00"),
        )

        with pytest.raises(ValidationError, match="remaining"):
            CheckoutService.checkout(cart)

    def test_revalidates_ticket_availability_at_checkout(self, cart, ticket_type):
        CartService.add_ticket(cart, ticket_type, qty=1)

        # Deactivate ticket after adding to cart
        ticket_type.is_active = False
        ticket_type.save(update_fields=["is_active", "updated_at"])

        with pytest.raises(ValidationError, match="no longer available"):
            CheckoutService.checkout(cart)

    def test_revalidates_addon_stock_at_checkout(self, cart, conference, user):
        addon = AddOn.objects.create(
            conference=conference,
            name="Limited Swag",
            slug="limited-swag",
            price=Decimal("15.00"),
            is_active=True,
            total_quantity=2,
        )
        CartService.add_addon(cart, addon, qty=1)

        # Sell all stock via another order
        paid = _make_order(conference=conference, user=user, status=Order.Status.PAID)
        OrderLineItem.objects.create(
            order=paid,
            addon=addon,
            description="Sold",
            quantity=2,
            unit_price=Decimal("15.00"),
            line_total=Decimal("30.00"),
        )

        with pytest.raises(ValidationError, match="remaining"):
            CheckoutService.checkout(cart)

    def test_revalidates_addon_active_at_checkout(self, cart, conference):
        addon = AddOn.objects.create(
            conference=conference,
            name="Swag",
            slug="swag",
            price=Decimal("15.00"),
            is_active=True,
        )
        CartService.add_addon(cart, addon, qty=1)

        addon.is_active = False
        addon.save(update_fields=["is_active", "updated_at"])

        with pytest.raises(ValidationError, match="no longer active"):
            CheckoutService.checkout(cart)

    def test_revalidates_addon_prerequisites_at_checkout(self, cart, ticket_type, conference):
        other_ticket = TicketType.objects.create(
            conference=conference,
            name="VIP",
            slug="vip-prereq",
            price=Decimal("500.00"),
            total_quantity=0,
            limit_per_user=10,
            is_active=True,
        )
        addon = AddOn.objects.create(
            conference=conference,
            name="Workshop",
            slug="workshop-prereq",
            price=Decimal("50.00"),
            is_active=True,
        )
        CartService.add_ticket(cart, ticket_type, qty=1)
        CartService.add_addon(cart, addon, qty=1)

        # Admin adds a prerequisite after the cart was assembled
        addon.requires_ticket_types.add(other_ticket)

        with pytest.raises(ValidationError, match="requires a ticket type"):
            CheckoutService.checkout(cart)

    def test_order_has_no_voucher_when_cart_has_none(self, cart_with_ticket):
        order = CheckoutService.checkout(cart_with_ticket)

        assert order.voucher_code == ""
        assert order.voucher_details == ""

    def test_checkout_is_atomic_on_failure(self, cart, conference):
        """If stock validation fails, no order or line items should be created."""
        ticket = TicketType.objects.create(
            conference=conference,
            name="Sold Out",
            slug="sold-out",
            price=Decimal("50.00"),
            total_quantity=1,
            is_active=True,
        )
        # Add to cart while still available
        CartService.add_ticket(cart, ticket, qty=1)

        # Now sell it out
        paid = _make_order(
            conference=conference,
            user=cart.user,
            status=Order.Status.PAID,
        )
        OrderLineItem.objects.create(
            order=paid,
            ticket_type=ticket,
            description="Sold",
            quantity=1,
            unit_price=Decimal("50.00"),
            line_total=Decimal("50.00"),
        )

        order_count_before = Order.objects.count()

        with pytest.raises(ValidationError):
            CheckoutService.checkout(cart)

        assert Order.objects.count() == order_count_before
        cart.refresh_from_db()
        assert cart.status == Cart.Status.OPEN

    def test_rejects_summary_item_id_mismatch(self, cart_with_ticket):
        """Defensive check: summary item_id not in fetched items raises ValidationError."""
        fake_summary = CartSummary(
            items=[
                LineItemSummary(
                    item_id=999999,
                    description="Ghost",
                    quantity=1,
                    unit_price=Decimal("10.00"),
                    discount=Decimal("0.00"),
                    line_total=Decimal("10.00"),
                ),
            ],
            subtotal=Decimal("10.00"),
            discount=Decimal("0.00"),
            total=Decimal("10.00"),
        )
        with patch.object(CartService, "get_summary_from_items", return_value=fake_summary):
            with pytest.raises(ValidationError, match="Cart changed during checkout"):
                CheckoutService.checkout(cart_with_ticket)


# =============================================================================
# TestApplyCredit
# =============================================================================


@pytest.mark.django_db
class TestApplyCredit:
    def test_applies_credit_to_pending_order(self, conference, user):
        order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)
        order.total = Decimal("100.00")
        order.save(update_fields=["total"])

        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("100.00"),
            status=Credit.Status.AVAILABLE,
        )

        payment = CheckoutService.apply_credit(order, credit)

        assert payment.method == Payment.Method.CREDIT
        assert payment.status == Payment.Status.SUCCEEDED
        assert payment.amount == Decimal("100.00")

        credit.refresh_from_db()
        assert credit.status == Credit.Status.APPLIED
        assert credit.applied_to_order == order
        assert credit.remaining_amount == Decimal("0.00")

    def test_fully_paid_transitions_to_paid(self, conference, user):
        order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)
        order.total = Decimal("50.00")
        order.hold_expires_at = timezone.now() + timedelta(minutes=15)
        order.save(update_fields=["total", "hold_expires_at", "updated_at"])

        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("50.00"),
            status=Credit.Status.AVAILABLE,
        )

        CheckoutService.apply_credit(order, credit)

        order.refresh_from_db()
        assert order.status == Order.Status.PAID
        assert order.hold_expires_at is None

    def test_partial_credit_does_not_change_status(self, conference, user):
        order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)
        order.total = Decimal("100.00")
        order.save(update_fields=["total"])

        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("30.00"),
            status=Credit.Status.AVAILABLE,
        )

        payment = CheckoutService.apply_credit(order, credit)

        assert payment.amount == Decimal("30.00")
        order.refresh_from_db()
        assert order.status == Order.Status.PENDING
        credit.refresh_from_db()
        assert credit.remaining_amount == Decimal("0.00")

    def test_credit_capped_at_remaining_balance(self, conference, user):
        order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)
        order.total = Decimal("50.00")
        order.save(update_fields=["total"])

        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("200.00"),
            status=Credit.Status.AVAILABLE,
        )

        payment = CheckoutService.apply_credit(order, credit)

        assert payment.amount == Decimal("50.00")
        credit.refresh_from_db()
        assert credit.status == Credit.Status.AVAILABLE
        assert credit.remaining_amount == Decimal("150.00")

    def test_rejects_non_pending_order(self, conference, user):
        order = _make_order(conference=conference, user=user, status=Order.Status.PAID)
        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("10.00"),
            status=Credit.Status.AVAILABLE,
        )

        with pytest.raises(ValidationError, match="pending orders"):
            CheckoutService.apply_credit(order, credit)

    def test_rejects_non_available_credit(self, conference, user):
        order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)
        order.total = Decimal("100.00")
        order.save(update_fields=["total"])

        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("50.00"),
            status=Credit.Status.APPLIED,
        )

        with pytest.raises(ValidationError, match="available credits"):
            CheckoutService.apply_credit(order, credit)

    def test_rejects_credit_from_different_user(self, conference, user, other_user):
        order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)
        order.total = Decimal("100.00")
        order.save(update_fields=["total"])

        credit = Credit.objects.create(
            user=other_user,
            conference=conference,
            amount=Decimal("50.00"),
            status=Credit.Status.AVAILABLE,
        )

        with pytest.raises(ValidationError, match="does not belong to this user"):
            CheckoutService.apply_credit(order, credit)

    def test_rejects_credit_from_different_conference(self, conference, user):
        other_conf = Conference.objects.create(
            name="OtherCon",
            slug="othercon-credit",
            start_date=date(2027, 8, 1),
            end_date=date(2027, 8, 3),
        )
        order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)
        order.total = Decimal("100.00")
        order.save(update_fields=["total"])

        credit = Credit.objects.create(
            user=user,
            conference=other_conf,
            amount=Decimal("50.00"),
            status=Credit.Status.AVAILABLE,
        )

        with pytest.raises(ValidationError, match="does not belong to this conference"):
            CheckoutService.apply_credit(order, credit)

    def test_rejects_when_order_already_fully_paid(self, conference, user):
        order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)
        order.total = Decimal("50.00")
        order.save(update_fields=["total"])

        Payment.objects.create(
            order=order,
            method=Payment.Method.STRIPE,
            status=Payment.Status.SUCCEEDED,
            amount=Decimal("50.00"),
        )

        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("10.00"),
            status=Credit.Status.AVAILABLE,
        )

        with pytest.raises(ValidationError, match="already fully paid"):
            CheckoutService.apply_credit(order, credit)

    def test_fires_order_paid_signal(self, conference, user):
        order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)
        order.total = Decimal("50.00")
        order.save(update_fields=["total"])

        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("50.00"),
            status=Credit.Status.AVAILABLE,
        )

        signal_received = []

        def handler(sender, order, user, **kwargs):
            signal_received.append((order.pk, user.pk))

        order_paid.connect(handler)
        try:
            CheckoutService.apply_credit(order, credit)
            assert len(signal_received) == 1
            assert signal_received[0] == (order.pk, user.pk)
        finally:
            order_paid.disconnect(handler)

    def test_rejects_credit_with_zero_remaining_amount(self, conference, user):
        order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)
        order.total = Decimal("100.00")
        order.save(update_fields=["total"])

        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("50.00"),
            status=Credit.Status.AVAILABLE,
        )
        # Bypass Credit.save() auto-init by updating directly
        Credit.objects.filter(pk=credit.pk).update(remaining_amount=Decimal("0.00"))
        credit.refresh_from_db()

        with pytest.raises(ValidationError, match="no remaining balance"):
            CheckoutService.apply_credit(order, credit)

    def test_fully_paid_without_hold_expires_at(self, conference, user):
        """When _order_has_hold_expires_at returns False, order saves without hold field."""
        order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)
        order.total = Decimal("50.00")
        order.save(update_fields=["total"])

        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("50.00"),
            status=Credit.Status.AVAILABLE,
        )

        with patch(
            "django_program.registration.services.checkout._order_has_hold_expires_at",
            return_value=False,
        ):
            CheckoutService.apply_credit(order, credit)

        order.refresh_from_db()
        assert order.status == Order.Status.PAID


# =============================================================================
# TestCancelOrder
# =============================================================================


@pytest.mark.django_db
class TestCancelOrder:
    def test_cancels_pending_order(self, conference, user):
        order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)

        result = CheckoutService.cancel_order(order)

        assert result.status == Order.Status.CANCELLED
        order.refresh_from_db()
        assert order.status == Order.Status.CANCELLED

    def test_decrements_voucher_times_used(self, conference, user):
        voucher = Voucher.objects.create(
            conference=conference,
            code="CANCEL-TEST",
            voucher_type=Voucher.VoucherType.COMP,
            max_uses=10,
            times_used=3,
            is_active=True,
        )
        order = Order.objects.create(
            conference=conference,
            user=user,
            status=Order.Status.PENDING,
            subtotal=Decimal("100.00"),
            total=Decimal("0.00"),
            voucher_code="CANCEL-TEST",
            reference=f"ORD-{uuid4().hex[:8].upper()}",
        )

        CheckoutService.cancel_order(order)

        voucher.refresh_from_db()
        assert voucher.times_used == 2

    def test_does_not_decrement_below_zero(self, conference, user):
        voucher = Voucher.objects.create(
            conference=conference,
            code="ZERO-TEST",
            voucher_type=Voucher.VoucherType.COMP,
            max_uses=10,
            times_used=0,
            is_active=True,
        )
        order = Order.objects.create(
            conference=conference,
            user=user,
            status=Order.Status.PENDING,
            subtotal=Decimal("100.00"),
            total=Decimal("0.00"),
            voucher_code="ZERO-TEST",
            reference=f"ORD-{uuid4().hex[:8].upper()}",
        )

        CheckoutService.cancel_order(order)

        voucher.refresh_from_db()
        assert voucher.times_used == 0

    def test_rejects_paid_order(self, conference, user):
        order = _make_order(conference=conference, user=user, status=Order.Status.PAID)

        with pytest.raises(ValidationError, match="Only pending orders"):
            CheckoutService.cancel_order(order)

    def test_rejects_cancelled_order(self, conference, user):
        order = _make_order(conference=conference, user=user, status=Order.Status.CANCELLED)

        with pytest.raises(ValidationError, match="Only pending orders"):
            CheckoutService.cancel_order(order)

    def test_rejects_refunded_order(self, conference, user):
        order = _make_order(conference=conference, user=user, status=Order.Status.REFUNDED)

        with pytest.raises(ValidationError, match="Only pending orders"):
            CheckoutService.cancel_order(order)

    def test_no_voucher_code_skips_decrement(self, conference, user):
        order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)

        result = CheckoutService.cancel_order(order)

        assert result.status == Order.Status.CANCELLED

    def test_reverses_credit_payments_on_cancel(self, conference, user):
        order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)
        order.total = Decimal("100.00")
        order.save(update_fields=["total"])

        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("30.00"),
            status=Credit.Status.AVAILABLE,
        )
        CheckoutService.apply_credit(order, credit)

        # Order is still PENDING (partial payment), credit is APPLIED
        order.refresh_from_db()
        assert order.status == Order.Status.PENDING
        credit.refresh_from_db()
        assert credit.status == Credit.Status.APPLIED

        CheckoutService.cancel_order(order)

        # Credit payment reversed, credit restored
        credit.refresh_from_db()
        assert credit.status == Credit.Status.AVAILABLE
        assert credit.applied_to_order is None
        assert credit.remaining_amount == Decimal("30.00")

        payment = order.payments.first()
        assert payment.status == Payment.Status.REFUNDED

    def test_cancel_without_hold_expires_at(self, conference, user):
        """When _order_has_hold_expires_at returns False, cancel saves without hold field."""
        order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)

        with patch(
            "django_program.registration.services.checkout._order_has_hold_expires_at",
            return_value=False,
        ):
            result = CheckoutService.cancel_order(order)

        assert result.status == Order.Status.CANCELLED

    def test_reverse_credit_payment_without_linked_credit(self, conference, user):
        """Credit payment exists but no Credit record linked -- skips reversal."""
        order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)
        order.total = Decimal("100.00")
        order.save(update_fields=["total"])

        Payment.objects.create(
            order=order,
            method=Payment.Method.CREDIT,
            status=Payment.Status.SUCCEEDED,
            amount=Decimal("25.00"),
        )

        result = CheckoutService.cancel_order(order)

        assert result.status == Order.Status.CANCELLED
        payment = order.payments.first()
        assert payment.status == Payment.Status.REFUNDED

    def test_reverse_skips_already_restored_credit(self, conference, user):
        """Credit already at full amount is not over-restored."""
        order = _make_order(conference=conference, user=user, status=Order.Status.PENDING)
        order.total = Decimal("100.00")
        order.save(update_fields=["total"])

        credit = Credit.objects.create(
            user=user,
            conference=conference,
            amount=Decimal("50.00"),
            status=Credit.Status.APPLIED,
            applied_to_order=order,
        )
        # Force remaining_amount to equal amount (already fully restored)
        Credit.objects.filter(pk=credit.pk).update(remaining_amount=Decimal("50.00"))

        Payment.objects.create(
            order=order,
            method=Payment.Method.CREDIT,
            status=Payment.Status.SUCCEEDED,
            amount=Decimal("50.00"),
        )

        result = CheckoutService.cancel_order(order)
        assert result.status == Order.Status.CANCELLED

        credit.refresh_from_db()
        # remaining_amount should NOT exceed amount
        assert credit.remaining_amount == Decimal("50.00")


# =============================================================================
# TestExpireStaleOrders
# =============================================================================


@pytest.mark.django_db
class TestExpireStaleOrders:
    def test_expire_skipped_without_hold_field(self, conference):
        """When _order_has_hold_expires_at returns False, no orders are expired."""

        with patch(
            "django_program.registration.services.checkout._order_has_hold_expires_at",
            return_value=False,
        ):
            _expire_stale_pending_orders(conference_id=conference.pk, now=timezone.now())

    def test_expire_decrements_voucher_usage(self, conference, user):
        """Expiring stale orders releases their voucher usage."""
        voucher = Voucher.objects.create(
            conference=conference,
            code="STALE",
            voucher_type=Voucher.VoucherType.COMP,
            max_uses=10,
            times_used=3,
            is_active=True,
        )
        order = Order.objects.create(
            conference=conference,
            user=user,
            status=Order.Status.PENDING,
            subtotal=Decimal("0.00"),
            total=Decimal("0.00"),
            reference=f"ORD-{uuid4().hex[:8].upper()}",
            voucher_code="STALE",
            hold_expires_at=timezone.now() - timedelta(minutes=1),
        )

        _expire_stale_pending_orders(conference_id=conference.pk, now=timezone.now())

        order.refresh_from_db()
        assert order.status == Order.Status.CANCELLED

        voucher.refresh_from_db()
        assert voucher.times_used == 2
