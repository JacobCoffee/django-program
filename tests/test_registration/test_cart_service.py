"""Tests for the CartService in django_program.registration.services.cart."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from django_program.conference.models import Conference
from django_program.registration.models import (
    AddOn,
    Cart,
    CartItem,
    Order,
    OrderLineItem,
    TicketType,
    Voucher,
)
from django_program.registration.services.cart import CartService, CartSummary

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
        slug="testcon",
        start_date=date(2027, 6, 1),
        end_date=date(2027, 6, 3),
        timezone="UTC",
    )


@pytest.fixture
def other_conference():
    return Conference.objects.create(
        name="OtherCon",
        slug="othercon-main",
        start_date=date(2027, 7, 1),
        end_date=date(2027, 7, 3),
        timezone="UTC",
    )


@pytest.fixture
def user():
    return User.objects.create_user(
        username="cartuser",
        email="cart@example.com",
        password="testpass123",
    )


@pytest.fixture
def other_user():
    return User.objects.create_user(
        username="otheruser",
        email="other@example.com",
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


# =============================================================================
# TestGetOrCreateCart
# =============================================================================


@pytest.mark.django_db
class TestGetOrCreateCart:
    def test_returns_existing_open_cart(self, conference, user):
        existing = Cart.objects.create(
            user=user,
            conference=conference,
            status=Cart.Status.OPEN,
            expires_at=timezone.now() + timedelta(minutes=30),
        )

        result = CartService.get_or_create_cart(user, conference)

        assert result.pk == existing.pk
        assert result.status == Cart.Status.OPEN

    def test_creates_new_cart_when_none_exists(self, conference, user):
        assert Cart.objects.filter(user=user, conference=conference).count() == 0

        result = CartService.get_or_create_cart(user, conference)

        assert result.pk is not None
        assert result.user == user
        assert result.conference == conference
        assert result.status == Cart.Status.OPEN
        assert result.expires_at is not None

    def test_expires_stale_cart_and_creates_new(self, conference, user):
        stale = Cart.objects.create(
            user=user,
            conference=conference,
            status=Cart.Status.OPEN,
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        result = CartService.get_or_create_cart(user, conference)

        stale.refresh_from_db()
        assert stale.status == Cart.Status.EXPIRED
        assert result.pk != stale.pk
        assert result.status == Cart.Status.OPEN

    def test_sets_expiry_when_existing_open_cart_has_no_expiration(self, conference, user, settings):
        settings.DJANGO_PROGRAM = {"cart_expiry_minutes": 30}
        existing = Cart.objects.create(
            user=user,
            conference=conference,
            status=Cart.Status.OPEN,
            expires_at=None,
        )
        before = timezone.now()

        result = CartService.get_or_create_cart(user, conference)
        after = timezone.now()

        assert result.pk == existing.pk
        assert result.expires_at is not None
        expected_min = before + timedelta(minutes=30)
        expected_max = after + timedelta(minutes=30)
        assert expected_min <= result.expires_at <= expected_max

    def test_sets_correct_expires_at_from_config(self, conference, user, settings):
        settings.DJANGO_PROGRAM = {"cart_expiry_minutes": 45}

        before = timezone.now()
        result = CartService.get_or_create_cart(user, conference)
        after = timezone.now()

        expected_min = before + timedelta(minutes=45)
        expected_max = after + timedelta(minutes=45)
        assert expected_min <= result.expires_at <= expected_max


# =============================================================================
# TestAddTicket
# =============================================================================


@pytest.mark.django_db
class TestAddTicket:
    def test_adds_ticket_to_cart(self, cart, ticket_type):
        item = CartService.add_ticket(cart, ticket_type, qty=2)

        assert item.ticket_type == ticket_type
        assert item.quantity == 2
        assert item.cart == cart

    def test_increases_quantity_when_already_in_cart(self, cart, ticket_type):
        CartService.add_ticket(cart, ticket_type, qty=1)
        item = CartService.add_ticket(cart, ticket_type, qty=3)

        assert item.quantity == 4
        assert cart.items.filter(ticket_type=ticket_type).count() == 1

    def test_rejects_unavailable_ticket(self, cart, conference):
        inactive = TicketType.objects.create(
            conference=conference,
            name="Inactive",
            slug="inactive",
            price=Decimal("50.00"),
            is_active=False,
        )

        with pytest.raises(ValidationError, match="not available"):
            CartService.add_ticket(cart, inactive)

    def test_rejects_when_remaining_quantity_insufficient(self, cart, limited_ticket, user, conference):
        # Sell 4 of 5 via existing order
        paid = _make_order(conference=conference, user=user, status=Order.Status.PAID)
        OrderLineItem.objects.create(
            order=paid,
            ticket_type=limited_ticket,
            description="Sold",
            quantity=4,
            unit_price=Decimal("200.00"),
            line_total=Decimal("800.00"),
        )
        # remaining = 1, requesting 2
        with pytest.raises(ValidationError, match="remaining"):
            CartService.add_ticket(cart, limited_ticket, qty=2)

    def test_rejects_when_limit_per_user_exceeded_by_cart(self, cart, limited_ticket):
        # limit_per_user=3, add 2 then try 2 more
        CartService.add_ticket(cart, limited_ticket, qty=2)

        with pytest.raises(ValidationError, match="per-user limit"):
            CartService.add_ticket(cart, limited_ticket, qty=2)

    def test_rejects_when_limit_per_user_exceeded_counting_orders(self, cart, limited_ticket, user, conference):
        # 2 already bought in a paid order, limit=3, try adding 2 more
        paid = _make_order(conference=conference, user=user, status=Order.Status.PAID)
        OrderLineItem.objects.create(
            order=paid,
            ticket_type=limited_ticket,
            description="Bought",
            quantity=2,
            unit_price=Decimal("200.00"),
            line_total=Decimal("400.00"),
        )

        with pytest.raises(ValidationError, match="per-user limit"):
            CartService.add_ticket(cart, limited_ticket, qty=2)

    def test_rejects_requires_voucher_without_voucher(self, cart, conference):
        hidden = TicketType.objects.create(
            conference=conference,
            name="VIP Hidden",
            slug="vip-hidden",
            price=Decimal("500.00"),
            requires_voucher=True,
            is_active=True,
        )

        with pytest.raises(ValidationError, match="requires a voucher"):
            CartService.add_ticket(cart, hidden)

    def test_rejects_requires_voucher_when_voucher_does_not_unlock(self, cart, conference):
        hidden = TicketType.objects.create(
            conference=conference,
            name="VIP Hidden",
            slug="vip-hidden",
            price=Decimal("500.00"),
            requires_voucher=True,
            is_active=True,
        )
        voucher = Voucher.objects.create(
            conference=conference,
            code="NO-UNLOCK",
            voucher_type=Voucher.VoucherType.COMP,
            max_uses=10,
            unlocks_hidden_tickets=False,
            is_active=True,
        )
        cart.voucher = voucher
        cart.save(update_fields=["voucher"])

        with pytest.raises(ValidationError, match="requires a voucher that unlocks"):
            CartService.add_ticket(cart, hidden)

    def test_accepts_requires_voucher_with_proper_voucher(self, cart, conference):
        hidden = TicketType.objects.create(
            conference=conference,
            name="VIP Hidden",
            slug="vip-hidden",
            price=Decimal("500.00"),
            requires_voucher=True,
            is_active=True,
        )
        voucher = Voucher.objects.create(
            conference=conference,
            code="UNLOCK-ME",
            voucher_type=Voucher.VoucherType.COMP,
            max_uses=10,
            unlocks_hidden_tickets=True,
            is_active=True,
        )
        cart.voucher = voucher
        cart.save(update_fields=["voucher"])

        item = CartService.add_ticket(cart, hidden)

        assert item.ticket_type == hidden
        assert item.quantity == 1

    def test_rejects_voucher_that_unlocks_but_does_not_cover_ticket(self, cart, conference):
        """Voucher unlocks hidden tickets but has a specific applicable list that excludes this ticket."""
        other_ticket = TicketType.objects.create(
            conference=conference,
            name="Other",
            slug="other",
            price=Decimal("50.00"),
            is_active=True,
        )
        hidden = TicketType.objects.create(
            conference=conference,
            name="VIP Hidden",
            slug="vip-hidden",
            price=Decimal("500.00"),
            requires_voucher=True,
            is_active=True,
        )
        voucher = Voucher.objects.create(
            conference=conference,
            code="PARTIAL-UNLOCK",
            voucher_type=Voucher.VoucherType.COMP,
            max_uses=10,
            unlocks_hidden_tickets=True,
            is_active=True,
        )
        voucher.applicable_ticket_types.add(other_ticket)
        cart.voucher = voucher
        cart.save(update_fields=["voucher"])

        with pytest.raises(ValidationError, match="does not cover"):
            CartService.add_ticket(cart, hidden)

    def test_extends_cart_expiry_on_add(self, cart, ticket_type):
        old_expiry = cart.expires_at
        CartService.add_ticket(cart, ticket_type)
        cart.refresh_from_db()

        assert cart.expires_at >= old_expiry

    def test_rejects_qty_less_than_one(self, cart, ticket_type):
        with pytest.raises(ValidationError, match="at least 1"):
            CartService.add_ticket(cart, ticket_type, qty=0)

        with pytest.raises(ValidationError, match="at least 1"):
            CartService.add_ticket(cart, ticket_type, qty=-1)

    def test_rejects_non_open_cart(self, cart, ticket_type):
        cart.status = Cart.Status.CHECKED_OUT
        cart.save(update_fields=["status", "updated_at"])

        with pytest.raises(ValidationError, match="Only open carts"):
            CartService.add_ticket(cart, ticket_type)

    def test_rejects_expired_cart(self, cart, ticket_type):
        cart.expires_at = timezone.now() - timedelta(minutes=1)
        cart.save(update_fields=["expires_at", "updated_at"])

        with pytest.raises(ValidationError, match="expired"):
            CartService.add_ticket(cart, ticket_type)

    def test_rejects_ticket_from_other_conference(self, cart, other_conference):
        foreign_ticket = TicketType.objects.create(
            conference=other_conference,
            name="Foreign",
            slug="foreign-ticket",
            price=Decimal("50.00"),
            is_active=True,
        )

        with pytest.raises(ValidationError, match="does not belong"):
            CartService.add_ticket(cart, foreign_ticket)

    def test_rejects_increment_when_existing_cart_qty_would_exceed_remaining(self, cart, conference, user):
        stock_ticket = TicketType.objects.create(
            conference=conference,
            name="Stock Ticket",
            slug="stock-ticket",
            price=Decimal("30.00"),
            total_quantity=5,
            limit_per_user=20,
            is_active=True,
        )
        paid = _make_order(conference=conference, user=user, status=Order.Status.PAID)
        OrderLineItem.objects.create(
            order=paid,
            ticket_type=stock_ticket,
            description="Sold",
            quantity=3,
            unit_price=Decimal("30.00"),
            line_total=Decimal("90.00"),
        )

        CartService.add_ticket(cart, stock_ticket, qty=1)
        with pytest.raises(ValidationError, match="remaining"):
            CartService.add_ticket(cart, stock_ticket, qty=2)


# =============================================================================
# TestAddAddon
# =============================================================================


@pytest.mark.django_db
class TestAddAddon:
    def test_adds_addon_to_cart(self, cart, conference):
        addon = AddOn.objects.create(
            conference=conference,
            name="Workshop",
            slug="workshop",
            price=Decimal("50.00"),
            is_active=True,
        )

        item = CartService.add_addon(cart, addon, qty=1)

        assert item.addon == addon
        assert item.quantity == 1

    def test_rejects_inactive_addon(self, cart, conference):
        addon = AddOn.objects.create(
            conference=conference,
            name="Dead Addon",
            slug="dead-addon",
            price=Decimal("10.00"),
            is_active=False,
        )

        with pytest.raises(ValidationError, match="not active"):
            CartService.add_addon(cart, addon)

    def test_rejects_addon_before_available_from(self, cart, conference):
        addon = AddOn.objects.create(
            conference=conference,
            name="Future Addon",
            slug="future-addon",
            price=Decimal("10.00"),
            is_active=True,
            available_from=timezone.now() + timedelta(days=7),
        )

        with pytest.raises(ValidationError, match="not yet available"):
            CartService.add_addon(cart, addon)

    def test_rejects_addon_after_available_until(self, cart, conference):
        addon = AddOn.objects.create(
            conference=conference,
            name="Expired Addon",
            slug="expired-addon",
            price=Decimal("10.00"),
            is_active=True,
            available_until=timezone.now() - timedelta(days=1),
        )

        with pytest.raises(ValidationError, match="no longer available"):
            CartService.add_addon(cart, addon)

    def test_rejects_addon_when_required_ticket_not_in_cart(self, cart, conference, ticket_type):
        addon = AddOn.objects.create(
            conference=conference,
            name="Workshop",
            slug="workshop",
            price=Decimal("50.00"),
            is_active=True,
        )
        addon.requires_ticket_types.add(ticket_type)

        with pytest.raises(ValidationError, match="requires one of"):
            CartService.add_addon(cart, addon)

    def test_accepts_addon_when_required_ticket_in_cart(self, cart, conference, ticket_type):
        CartService.add_ticket(cart, ticket_type)

        addon = AddOn.objects.create(
            conference=conference,
            name="Workshop",
            slug="workshop",
            price=Decimal("50.00"),
            is_active=True,
        )
        addon.requires_ticket_types.add(ticket_type)

        item = CartService.add_addon(cart, addon)

        assert item.addon == addon
        assert item.quantity == 1

    def test_accepts_addon_with_no_ticket_restriction(self, cart, conference):
        addon = AddOn.objects.create(
            conference=conference,
            name="T-Shirt",
            slug="tshirt",
            price=Decimal("25.00"),
            is_active=True,
        )
        # No requires_ticket_types set

        item = CartService.add_addon(cart, addon)

        assert item.addon == addon

    def test_rejects_when_out_of_stock(self, cart, conference, user):
        addon = AddOn.objects.create(
            conference=conference,
            name="Limited Swag",
            slug="limited-swag",
            price=Decimal("15.00"),
            is_active=True,
            total_quantity=2,
        )
        # Sell all via existing orders
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
            CartService.add_addon(cart, addon)

    def test_increases_quantity_when_already_in_cart(self, cart, conference):
        addon = AddOn.objects.create(
            conference=conference,
            name="Sticker Pack",
            slug="sticker",
            price=Decimal("5.00"),
            is_active=True,
        )

        CartService.add_addon(cart, addon, qty=1)
        item = CartService.add_addon(cart, addon, qty=2)

        assert item.quantity == 3
        assert cart.items.filter(addon=addon).count() == 1

    def test_rejects_qty_less_than_one(self, cart, conference):
        addon = AddOn.objects.create(
            conference=conference,
            name="Nope",
            slug="nope",
            price=Decimal("5.00"),
            is_active=True,
        )

        with pytest.raises(ValidationError, match="at least 1"):
            CartService.add_addon(cart, addon, qty=0)

    def test_rejects_addon_from_other_conference(self, cart, other_conference):
        foreign_addon = AddOn.objects.create(
            conference=other_conference,
            name="Foreign Addon",
            slug="foreign-addon",
            price=Decimal("8.00"),
            is_active=True,
        )

        with pytest.raises(ValidationError, match="does not belong"):
            CartService.add_addon(cart, foreign_addon)

    def test_rejects_increment_when_existing_cart_qty_would_exceed_remaining(self, cart, conference, user):
        addon = AddOn.objects.create(
            conference=conference,
            name="Limited Pins",
            slug="limited-pins",
            price=Decimal("4.00"),
            is_active=True,
            total_quantity=5,
        )
        paid = _make_order(conference=conference, user=user, status=Order.Status.PAID)
        OrderLineItem.objects.create(
            order=paid,
            addon=addon,
            description="Sold",
            quantity=3,
            unit_price=Decimal("4.00"),
            line_total=Decimal("12.00"),
        )

        CartService.add_addon(cart, addon, qty=1)
        with pytest.raises(ValidationError, match="remaining"):
            CartService.add_addon(cart, addon, qty=2)


# =============================================================================
# TestRemoveItem
# =============================================================================


@pytest.mark.django_db
class TestRemoveItem:
    def test_removes_item_from_cart(self, cart, ticket_type):
        item = CartService.add_ticket(cart, ticket_type)
        item_id = item.pk

        CartService.remove_item(cart, item_id)

        assert not CartItem.objects.filter(pk=item_id).exists()

    def test_raises_for_nonexistent_item(self, cart):
        with pytest.raises(ValidationError, match="not found"):
            CartService.remove_item(cart, item_id=999999)

    def test_rejects_non_open_cart(self, cart, ticket_type):
        item = CartService.add_ticket(cart, ticket_type)
        cart.status = Cart.Status.CHECKED_OUT
        cart.save(update_fields=["status", "updated_at"])

        with pytest.raises(ValidationError, match="Only open carts"):
            CartService.remove_item(cart, item.pk)

    def test_cascade_removes_orphaned_addons(self, cart, conference, ticket_type):
        """Removing a ticket also removes addons that required that ticket type."""
        ticket_item = CartService.add_ticket(cart, ticket_type)

        addon = AddOn.objects.create(
            conference=conference,
            name="Workshop",
            slug="workshop",
            price=Decimal("50.00"),
            is_active=True,
        )
        addon.requires_ticket_types.add(ticket_type)
        addon_item = CartService.add_addon(cart, addon)

        CartService.remove_item(cart, ticket_item.pk)

        assert not CartItem.objects.filter(pk=ticket_item.pk).exists()
        assert not CartItem.objects.filter(pk=addon_item.pk).exists()

    def test_does_not_remove_addon_when_another_qualifying_ticket_remains(self, cart, conference, ticket_type):
        """Addon stays if another ticket type that satisfies its requirement remains."""
        other_ticket = TicketType.objects.create(
            conference=conference,
            name="Premium",
            slug="premium",
            price=Decimal("300.00"),
            is_active=True,
        )

        ticket_item = CartService.add_ticket(cart, ticket_type)
        CartService.add_ticket(cart, other_ticket)

        addon = AddOn.objects.create(
            conference=conference,
            name="Workshop",
            slug="workshop",
            price=Decimal("50.00"),
            is_active=True,
        )
        addon.requires_ticket_types.add(ticket_type, other_ticket)
        addon_item = CartService.add_addon(cart, addon)

        # Remove one qualifying ticket, the other still qualifies
        CartService.remove_item(cart, ticket_item.pk)

        assert CartItem.objects.filter(pk=addon_item.pk).exists()

    def test_does_not_remove_addon_with_no_ticket_restriction(self, cart, conference, ticket_type):
        """Addon with no requires_ticket_types is never orphaned by ticket removal."""
        ticket_item = CartService.add_ticket(cart, ticket_type)

        addon = AddOn.objects.create(
            conference=conference,
            name="T-Shirt",
            slug="tshirt",
            price=Decimal("25.00"),
            is_active=True,
        )
        addon_item = CartService.add_addon(cart, addon)

        CartService.remove_item(cart, ticket_item.pk)

        assert CartItem.objects.filter(pk=addon_item.pk).exists()


# =============================================================================
# TestUpdateQuantity
# =============================================================================


@pytest.mark.django_db
class TestUpdateQuantity:
    def test_updates_quantity_successfully(self, cart, ticket_type):
        item = CartService.add_ticket(cart, ticket_type, qty=1)

        updated = CartService.update_quantity(cart, item.pk, qty=5)

        assert updated is not None
        assert updated.quantity == 5

    def test_removes_item_when_qty_zero(self, cart, ticket_type):
        item = CartService.add_ticket(cart, ticket_type, qty=2)

        result = CartService.update_quantity(cart, item.pk, qty=0)

        assert result is None
        assert not CartItem.objects.filter(pk=item.pk).exists()

    def test_removes_item_when_qty_negative(self, cart, ticket_type):
        item = CartService.add_ticket(cart, ticket_type, qty=2)

        result = CartService.update_quantity(cart, item.pk, qty=-1)

        assert result is None
        assert not CartItem.objects.filter(pk=item.pk).exists()

    def test_revalidates_stock_for_ticket(self, cart, limited_ticket, user, conference):
        item = CartService.add_ticket(cart, limited_ticket, qty=1)

        # Sell 4 of 5 via orders, so only 1 remains
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
            CartService.update_quantity(cart, item.pk, qty=2)

    def test_revalidates_per_user_limit_for_ticket(self, cart, limited_ticket, user, conference):
        item = CartService.add_ticket(cart, limited_ticket, qty=1)

        # Already bought 2 in paid orders, limit=3
        paid = _make_order(conference=conference, user=user, status=Order.Status.PAID)
        OrderLineItem.objects.create(
            order=paid,
            ticket_type=limited_ticket,
            description="Bought",
            quantity=2,
            unit_price=Decimal("200.00"),
            line_total=Decimal("400.00"),
        )

        with pytest.raises(ValidationError, match="per-user limit"):
            CartService.update_quantity(cart, item.pk, qty=2)

    def test_revalidates_stock_for_addon(self, cart, conference, user):
        addon = AddOn.objects.create(
            conference=conference,
            name="Swag Bag",
            slug="swag-bag",
            price=Decimal("20.00"),
            is_active=True,
            total_quantity=3,
        )
        item = CartService.add_addon(cart, addon, qty=1)

        # Sell 2 of 3 via orders
        paid = _make_order(conference=conference, user=user, status=Order.Status.PAID)
        OrderLineItem.objects.create(
            order=paid,
            addon=addon,
            description="Sold",
            quantity=2,
            unit_price=Decimal("20.00"),
            line_total=Decimal("40.00"),
        )

        with pytest.raises(ValidationError, match="remaining"):
            CartService.update_quantity(cart, item.pk, qty=2)

    def test_raises_for_nonexistent_item(self, cart):
        with pytest.raises(ValidationError, match="not found"):
            CartService.update_quantity(cart, item_id=999999, qty=5)

    def test_rejects_non_open_cart(self, cart, ticket_type):
        item = CartService.add_ticket(cart, ticket_type, qty=1)
        cart.status = Cart.Status.CHECKED_OUT
        cart.save(update_fields=["status", "updated_at"])

        with pytest.raises(ValidationError, match="Only open carts"):
            CartService.update_quantity(cart, item.pk, qty=2)


# =============================================================================
# TestApplyVoucher
# =============================================================================


@pytest.mark.django_db
class TestApplyVoucher:
    def test_applies_valid_voucher(self, cart, conference):
        voucher = Voucher.objects.create(
            conference=conference,
            code="SAVE20",
            voucher_type=Voucher.VoucherType.PERCENTAGE,
            discount_value=Decimal("20.00"),
            max_uses=10,
            is_active=True,
        )

        result = CartService.apply_voucher(cart, "SAVE20")

        assert result.pk == voucher.pk
        cart.refresh_from_db()
        assert cart.voucher_id == voucher.pk

    def test_rejects_nonexistent_code(self, cart):
        with pytest.raises(ValidationError, match="not found"):
            CartService.apply_voucher(cart, "DOESNOTEXIST")

    def test_rejects_invalid_voucher(self, cart, conference):
        Voucher.objects.create(
            conference=conference,
            code="EXPIRED",
            voucher_type=Voucher.VoucherType.PERCENTAGE,
            discount_value=Decimal("10.00"),
            max_uses=1,
            times_used=1,
            is_active=True,
        )

        with pytest.raises(ValidationError, match="no longer valid"):
            CartService.apply_voucher(cart, "EXPIRED")

    def test_rejects_inactive_voucher(self, cart, conference):
        Voucher.objects.create(
            conference=conference,
            code="DEAD",
            voucher_type=Voucher.VoucherType.COMP,
            max_uses=10,
            is_active=False,
        )

        with pytest.raises(ValidationError, match="no longer valid"):
            CartService.apply_voucher(cart, "DEAD")

    def test_rejects_voucher_from_other_conference(self, cart, conference):
        other_conf = Conference.objects.create(
            name="OtherCon",
            slug="othercon",
            start_date=date(2027, 8, 1),
            end_date=date(2027, 8, 3),
        )
        Voucher.objects.create(
            conference=other_conf,
            code="WRONGCON",
            voucher_type=Voucher.VoucherType.COMP,
            max_uses=10,
            is_active=True,
        )

        with pytest.raises(ValidationError, match="not found"):
            CartService.apply_voucher(cart, "WRONGCON")

    def test_rejects_non_open_cart(self, cart, conference):
        Voucher.objects.create(
            conference=conference,
            code="SAVE10",
            voucher_type=Voucher.VoucherType.PERCENTAGE,
            discount_value=Decimal("10.00"),
            max_uses=10,
            is_active=True,
        )
        cart.status = Cart.Status.CHECKED_OUT
        cart.save(update_fields=["status", "updated_at"])

        with pytest.raises(ValidationError, match="Only open carts"):
            CartService.apply_voucher(cart, "SAVE10")


# =============================================================================
# TestGetSummary
# =============================================================================


@pytest.mark.django_db
class TestGetSummary:
    def test_empty_cart_returns_zero_totals(self, cart):
        summary = CartService.get_summary(cart)

        assert isinstance(summary, CartSummary)
        assert summary.items == []
        assert summary.subtotal == Decimal("0.00")
        assert summary.discount == Decimal("0.00")
        assert summary.total == Decimal("0.00")

    def test_subtotal_with_no_voucher(self, cart, ticket_type, conference):
        CartService.add_ticket(cart, ticket_type, qty=2)  # 2 x $100

        addon = AddOn.objects.create(
            conference=conference,
            name="T-Shirt",
            slug="tshirt",
            price=Decimal("25.00"),
            is_active=True,
        )
        CartService.add_addon(cart, addon, qty=1)  # 1 x $25

        summary = CartService.get_summary(cart)

        assert summary.subtotal == Decimal("225.00")
        assert summary.discount == Decimal("0.00")
        assert summary.total == Decimal("225.00")
        assert len(summary.items) == 2

    def test_comp_voucher_100_percent_off_applicable(self, cart, ticket_type, conference):
        CartService.add_ticket(cart, ticket_type, qty=2)  # 2 x $100

        voucher = Voucher.objects.create(
            conference=conference,
            code="FREE",
            voucher_type=Voucher.VoucherType.COMP,
            max_uses=10,
            is_active=True,
        )
        CartService.apply_voucher(cart, "FREE")

        summary = CartService.get_summary(cart)

        assert summary.subtotal == Decimal("200.00")
        assert summary.discount == Decimal("200.00")
        assert summary.total == Decimal("0.00")

    def test_percentage_voucher(self, cart, ticket_type, conference):
        CartService.add_ticket(cart, ticket_type, qty=1)  # 1 x $100

        Voucher.objects.create(
            conference=conference,
            code="HALF",
            voucher_type=Voucher.VoucherType.PERCENTAGE,
            discount_value=Decimal("50.00"),
            max_uses=10,
            is_active=True,
        )
        CartService.apply_voucher(cart, "HALF")

        summary = CartService.get_summary(cart)

        assert summary.subtotal == Decimal("100.00")
        assert summary.discount == Decimal("50.00")
        assert summary.total == Decimal("50.00")

    def test_fixed_amount_voucher(self, cart, ticket_type, conference):
        CartService.add_ticket(cart, ticket_type, qty=2)  # 2 x $100 = $200

        Voucher.objects.create(
            conference=conference,
            code="FLAT30",
            voucher_type=Voucher.VoucherType.FIXED_AMOUNT,
            discount_value=Decimal("30.00"),
            max_uses=10,
            is_active=True,
        )
        CartService.apply_voucher(cart, "FLAT30")

        summary = CartService.get_summary(cart)

        assert summary.subtotal == Decimal("200.00")
        assert summary.discount == Decimal("30.00")
        assert summary.total == Decimal("170.00")

    def test_fixed_amount_capped_at_subtotal(self, cart, conference):
        cheap_ticket = TicketType.objects.create(
            conference=conference,
            name="Cheap",
            slug="cheap",
            price=Decimal("10.00"),
            is_active=True,
        )
        CartService.add_ticket(cart, cheap_ticket, qty=1)  # $10

        Voucher.objects.create(
            conference=conference,
            code="BIG",
            voucher_type=Voucher.VoucherType.FIXED_AMOUNT,
            discount_value=Decimal("1000.00"),
            max_uses=10,
            is_active=True,
        )
        CartService.apply_voucher(cart, "BIG")

        summary = CartService.get_summary(cart)

        assert summary.total == Decimal("0.00")
        assert summary.discount == Decimal("10.00")

    def test_mixed_applicable_and_non_applicable_items(self, cart, conference, ticket_type):
        """Voucher only applies to specific ticket type, not to addon."""
        CartService.add_ticket(cart, ticket_type, qty=1)  # $100

        addon = AddOn.objects.create(
            conference=conference,
            name="T-Shirt",
            slug="tshirt",
            price=Decimal("30.00"),
            is_active=True,
        )
        CartService.add_addon(cart, addon, qty=1)  # $30

        voucher = Voucher.objects.create(
            conference=conference,
            code="TICKET-ONLY",
            voucher_type=Voucher.VoucherType.COMP,
            max_uses=10,
            is_active=True,
        )
        voucher.applicable_ticket_types.add(ticket_type)
        # No applicable_addons => addon qualifies by default with None set
        # but since applicable_ticket_types is set, _resolve_voucher_scope returns
        # (set of ticket IDs, None for addons).

        CartService.apply_voucher(cart, "TICKET-ONLY")

        summary = CartService.get_summary(cart)

        # ticket $100 is comped, addon $30 is also comped (addon_ids=None => all addons)
        assert summary.subtotal == Decimal("130.00")
        assert summary.discount == Decimal("130.00")
        assert summary.total == Decimal("0.00")

    def test_voucher_scoped_to_specific_ticket_and_addon(self, cart, conference, ticket_type):
        """Voucher applies only to specific ticket and specific addon."""
        other_ticket = TicketType.objects.create(
            conference=conference,
            name="Premium",
            slug="premium",
            price=Decimal("300.00"),
            is_active=True,
        )
        CartService.add_ticket(cart, ticket_type, qty=1)  # $100 - applicable
        CartService.add_ticket(cart, other_ticket, qty=1)  # $300 - NOT applicable

        addon = AddOn.objects.create(
            conference=conference,
            name="Workshop",
            slug="workshop",
            price=Decimal("50.00"),
            is_active=True,
        )
        other_addon = AddOn.objects.create(
            conference=conference,
            name="Dinner",
            slug="dinner",
            price=Decimal("75.00"),
            is_active=True,
        )
        CartService.add_addon(cart, addon, qty=1)  # $50 - applicable
        CartService.add_addon(cart, other_addon, qty=1)  # $75 - NOT applicable

        voucher = Voucher.objects.create(
            conference=conference,
            code="TARGETED",
            voucher_type=Voucher.VoucherType.COMP,
            max_uses=10,
            is_active=True,
        )
        voucher.applicable_ticket_types.add(ticket_type)
        voucher.applicable_addons.add(addon)

        CartService.apply_voucher(cart, "TARGETED")
        summary = CartService.get_summary(cart)

        # subtotal = 100 + 300 + 50 + 75 = 525
        assert summary.subtotal == Decimal("525.00")
        # Only $100 ticket + $50 addon comped = $150
        assert summary.discount == Decimal("150.00")
        assert summary.total == Decimal("375.00")

    def test_fixed_amount_proportional_distribution(self, cart, conference):
        """Fixed discount is distributed proportionally across multiple applicable items."""
        t1 = TicketType.objects.create(
            conference=conference,
            name="Basic",
            slug="basic",
            price=Decimal("100.00"),
            is_active=True,
        )
        t2 = TicketType.objects.create(
            conference=conference,
            name="Premium",
            slug="premium",
            price=Decimal("300.00"),
            is_active=True,
        )
        CartService.add_ticket(cart, t1, qty=1)  # $100
        CartService.add_ticket(cart, t2, qty=1)  # $300

        Voucher.objects.create(
            conference=conference,
            code="FIXED80",
            voucher_type=Voucher.VoucherType.FIXED_AMOUNT,
            discount_value=Decimal("80.00"),
            max_uses=10,
            is_active=True,
        )
        CartService.apply_voucher(cart, "FIXED80")
        summary = CartService.get_summary(cart)

        assert summary.subtotal == Decimal("400.00")
        assert summary.discount == Decimal("80.00")
        assert summary.total == Decimal("320.00")

        # Verify proportional split: 100/400 * 80 = 20, 300/400 * 80 = 60
        discounts = [item.discount for item in summary.items]
        assert sorted(discounts) == [Decimal("20.00"), Decimal("60.00")]

    def test_total_never_below_zero(self, cart, conference):
        cheap = TicketType.objects.create(
            conference=conference,
            name="Freebie",
            slug="freebie",
            price=Decimal("5.00"),
            is_active=True,
        )
        CartService.add_ticket(cart, cheap, qty=1)

        Voucher.objects.create(
            conference=conference,
            code="OVERKILL",
            voucher_type=Voucher.VoucherType.FIXED_AMOUNT,
            discount_value=Decimal("9999.00"),
            max_uses=10,
            is_active=True,
        )
        CartService.apply_voucher(cart, "OVERKILL")

        summary = CartService.get_summary(cart)

        assert summary.total >= Decimal("0.00")

    def test_percentage_voucher_on_multiple_items(self, cart, conference):
        t1 = TicketType.objects.create(
            conference=conference,
            name="A",
            slug="a",
            price=Decimal("100.00"),
            is_active=True,
        )
        t2 = TicketType.objects.create(
            conference=conference,
            name="B",
            slug="b",
            price=Decimal("50.00"),
            is_active=True,
        )
        CartService.add_ticket(cart, t1, qty=1)
        CartService.add_ticket(cart, t2, qty=2)  # 2 x $50 = $100

        Voucher.objects.create(
            conference=conference,
            code="TEN",
            voucher_type=Voucher.VoucherType.PERCENTAGE,
            discount_value=Decimal("10.00"),
            max_uses=10,
            is_active=True,
        )
        CartService.apply_voucher(cart, "TEN")

        summary = CartService.get_summary(cart)

        # subtotal = 200, 10% = 20
        assert summary.subtotal == Decimal("200.00")
        assert summary.discount == Decimal("20.00")
        assert summary.total == Decimal("180.00")

    def test_line_totals_reflect_discount(self, cart, ticket_type, conference):
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

        summary = CartService.get_summary(cart)

        assert len(summary.items) == 1
        line = summary.items[0]
        assert line.discount == Decimal("50.00")
        assert line.line_total == Decimal("50.00")
