"""Tests for registration views.

Covers TicketSelectView, CartView, CheckoutView, OrderConfirmationView,
OrderDetailView, and the helper functions _generate_order_reference,
_calculate_discount, and _cart_totals.
"""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from django_program.conference.models import Conference
from django_program.registration.models import (
    AddOn,
    Cart,
    CartItem,
    Order,
    OrderLineItem,
    Payment,
    Voucher,
)
from django_program.registration.views import (
    _calculate_discount,
    _cart_totals,
    _generate_order_reference,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conference(db):
    return Conference.objects.create(
        name="TestCon 2027",
        slug="testcon",
        start_date=date(2027, 5, 1),
        end_date=date(2027, 5, 3),
        timezone="UTC",
        is_active=True,
    )


@pytest.fixture
def user(db):
    return User.objects.create_user(username="attendee", password="password", email="attendee@test.com")


@pytest.fixture
def other_user(db):
    return User.objects.create_user(username="other", password="password", email="other@test.com")


@pytest.fixture
def ticket_type(conference):
    return conference.ticket_types.create(
        name="General Admission",
        slug="general",
        price=Decimal("100.00"),
        is_active=True,
        order=1,
    )


@pytest.fixture
def ticket_type_b(conference):
    return conference.ticket_types.create(
        name="Student",
        slug="student",
        price=Decimal("50.00"),
        is_active=True,
        order=2,
    )


@pytest.fixture
def voucher_only_ticket(conference):
    return conference.ticket_types.create(
        name="Speaker",
        slug="speaker",
        price=Decimal("0.00"),
        is_active=True,
        requires_voucher=True,
        order=3,
    )


@pytest.fixture
def inactive_ticket(conference):
    return conference.ticket_types.create(
        name="Inactive Ticket",
        slug="inactive",
        price=Decimal("200.00"),
        is_active=False,
        order=4,
    )


@pytest.fixture
def sold_out_ticket(conference):
    return conference.ticket_types.create(
        name="VIP",
        slug="vip",
        price=Decimal("500.00"),
        is_active=True,
        total_quantity=1,
        order=5,
    )


@pytest.fixture
def addon(conference):
    return AddOn.objects.create(
        conference=conference,
        name="Workshop",
        slug="workshop",
        price=Decimal("25.00"),
        is_active=True,
        order=1,
    )


@pytest.fixture
def addon_b(conference):
    return AddOn.objects.create(
        conference=conference,
        name="T-Shirt",
        slug="tshirt",
        price=Decimal("20.00"),
        is_active=True,
        order=2,
    )


@pytest.fixture
def comp_voucher(conference):
    return Voucher.objects.create(
        conference=conference,
        code="COMP100",
        voucher_type=Voucher.VoucherType.COMP,
        discount_value=Decimal(0),
        max_uses=10,
    )


@pytest.fixture
def percentage_voucher(conference):
    return Voucher.objects.create(
        conference=conference,
        code="SAVE20",
        voucher_type=Voucher.VoucherType.PERCENTAGE,
        discount_value=Decimal(20),
        max_uses=10,
    )


@pytest.fixture
def fixed_voucher(conference):
    return Voucher.objects.create(
        conference=conference,
        code="FLAT15",
        voucher_type=Voucher.VoucherType.FIXED_AMOUNT,
        discount_value=Decimal(15),
        max_uses=10,
    )


@pytest.fixture
def expired_voucher(conference):
    return Voucher.objects.create(
        conference=conference,
        code="EXPIRED",
        voucher_type=Voucher.VoucherType.COMP,
        discount_value=Decimal(0),
        max_uses=1,
        times_used=1,
    )


@pytest.fixture
def cart(conference, user):
    return Cart.objects.create(
        user=user,
        conference=conference,
        status=Cart.Status.OPEN,
    )


@pytest.fixture
def cart_with_ticket(cart, ticket_type):
    CartItem.objects.create(cart=cart, ticket_type=ticket_type, quantity=1)
    return cart


@pytest.fixture
def cart_with_addon(cart, addon):
    CartItem.objects.create(cart=cart, addon=addon, quantity=2)
    return cart


@pytest.fixture
def client_logged_in(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def client_other_user(other_user):
    c = Client()
    c.force_login(other_user)
    return c


@pytest.fixture
def anon_client():
    return Client()


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestGenerateOrderReference:
    def test_format(self):
        ref = _generate_order_reference()
        assert ref.startswith("ORD-")
        assert len(ref) == 10  # "ORD-" + 6 chars

    def test_alphanumeric_chars(self):
        ref = _generate_order_reference()
        suffix = ref[4:]
        assert suffix.isalnum()
        assert suffix == suffix.upper()

    def test_uniqueness(self):
        refs = {_generate_order_reference() for _ in range(50)}
        assert len(refs) >= 45  # statistically near impossible to collide


class TestCalculateDiscount:
    def test_none_voucher_returns_zero(self):
        assert _calculate_discount(Decimal("100.00"), None) == Decimal("0.00")

    @pytest.mark.django_db
    def test_comp_voucher_returns_full_subtotal(self, comp_voucher):
        assert _calculate_discount(Decimal("100.00"), comp_voucher) == Decimal("100.00")

    @pytest.mark.django_db
    def test_percentage_voucher(self, percentage_voucher):
        result = _calculate_discount(Decimal("100.00"), percentage_voucher)
        assert result == Decimal("20.00")

    @pytest.mark.django_db
    def test_percentage_voucher_capped_at_subtotal(self, conference):
        huge_voucher = Voucher.objects.create(
            conference=conference,
            code="BIG",
            voucher_type=Voucher.VoucherType.PERCENTAGE,
            discount_value=Decimal(200),
            max_uses=1,
        )
        result = _calculate_discount(Decimal("50.00"), huge_voucher)
        assert result == Decimal("50.00")

    @pytest.mark.django_db
    def test_fixed_amount_voucher(self, fixed_voucher):
        result = _calculate_discount(Decimal("100.00"), fixed_voucher)
        assert result == Decimal("15.00")

    @pytest.mark.django_db
    def test_fixed_amount_capped_at_subtotal(self, fixed_voucher):
        result = _calculate_discount(Decimal("10.00"), fixed_voucher)
        assert result == Decimal("10.00")

    @pytest.mark.django_db
    def test_unknown_voucher_type_returns_zero(self, conference):
        voucher = Voucher.objects.create(
            conference=conference,
            code="UNKNOWN",
            voucher_type="nonexistent_type",
            discount_value=Decimal(10),
            max_uses=1,
        )
        result = _calculate_discount(Decimal("100.00"), voucher)
        assert result == Decimal("0.00")


@pytest.mark.django_db
class TestCartTotals:
    def test_empty_cart(self, cart):
        subtotal, discount, total = _cart_totals(cart)
        assert subtotal == Decimal("0.00")
        assert discount == Decimal("0.00")
        assert total == Decimal("0.00")

    def test_cart_with_ticket(self, cart_with_ticket):
        subtotal, discount, total = _cart_totals(cart_with_ticket)
        assert subtotal == Decimal("100.00")
        assert discount == Decimal("0.00")
        assert total == Decimal("100.00")

    def test_cart_with_addon(self, cart_with_addon):
        subtotal, _discount, total = _cart_totals(cart_with_addon)
        assert subtotal == Decimal("50.00")  # 25 * 2
        assert total == Decimal("50.00")

    def test_cart_with_voucher(self, cart_with_ticket, comp_voucher):
        cart_with_ticket.voucher = comp_voucher
        cart_with_ticket.save()
        subtotal, discount, total = _cart_totals(cart_with_ticket)
        assert subtotal == Decimal("100.00")
        assert discount == Decimal("100.00")
        assert total == Decimal("0.00")

    def test_total_never_negative(self, cart_with_ticket, fixed_voucher):
        # fixed_voucher is 15 off, subtotal is 100, so total should be 85
        cart_with_ticket.voucher = fixed_voucher
        cart_with_ticket.save()
        _subtotal, _discount, total = _cart_totals(cart_with_ticket)
        assert total >= Decimal("0.00")


# ---------------------------------------------------------------------------
# TicketSelectView tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTicketSelectView:
    def test_renders_available_tickets(self, anon_client, conference, ticket_type, ticket_type_b):
        url = reverse("registration:ticket-select", kwargs={"conference_slug": conference.slug})
        resp = anon_client.get(url)
        assert resp.status_code == 200
        qs = resp.context["ticket_types"]
        slugs = [t.slug for t in qs]
        assert "general" in slugs
        assert "student" in slugs

    def test_excludes_voucher_only_tickets(self, anon_client, conference, ticket_type, voucher_only_ticket):
        url = reverse("registration:ticket-select", kwargs={"conference_slug": conference.slug})
        resp = anon_client.get(url)
        slugs = [t.slug for t in resp.context["ticket_types"]]
        assert "speaker" not in slugs
        assert "general" in slugs

    def test_excludes_inactive_tickets(self, anon_client, conference, ticket_type, inactive_ticket):
        url = reverse("registration:ticket-select", kwargs={"conference_slug": conference.slug})
        resp = anon_client.get(url)
        slugs = [t.slug for t in resp.context["ticket_types"]]
        assert "inactive" not in slugs

    def test_now_in_context(self, anon_client, conference, ticket_type):
        url = reverse("registration:ticket-select", kwargs={"conference_slug": conference.slug})
        resp = anon_client.get(url)
        assert "now" in resp.context

    def test_nonexistent_conference_404(self, anon_client):
        url = reverse("registration:ticket-select", kwargs={"conference_slug": "nope"})
        resp = anon_client.get(url)
        assert resp.status_code == 404

    def test_empty_tickets(self, anon_client, conference):
        url = reverse("registration:ticket-select", kwargs={"conference_slug": conference.slug})
        resp = anon_client.get(url)
        assert resp.status_code == 200
        assert list(resp.context["ticket_types"]) == []

    def test_ordered_by_order_then_name(self, anon_client, conference, ticket_type, ticket_type_b):
        url = reverse("registration:ticket-select", kwargs={"conference_slug": conference.slug})
        resp = anon_client.get(url)
        tickets = list(resp.context["ticket_types"])
        assert tickets[0].slug == "general"  # order=1
        assert tickets[1].slug == "student"  # order=2


# ---------------------------------------------------------------------------
# CartView tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCartViewGet:
    def test_anonymous_redirects_to_login(self, anon_client, conference):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = anon_client.get(url)
        assert resp.status_code == 302
        assert "login" in resp.url

    def test_renders_empty_cart(self, client_logged_in, conference):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.get(url)
        assert resp.status_code == 200
        assert resp.context["cart"] is not None

    def test_creates_cart_on_first_visit(self, client_logged_in, conference, user):
        assert not Cart.objects.filter(user=user, conference=conference).exists()
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        client_logged_in.get(url)
        assert Cart.objects.filter(user=user, conference=conference, status=Cart.Status.OPEN).exists()

    def test_add_ticket_via_query_param(self, client_logged_in, conference, ticket_type):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.get(url, {"add_ticket": "general"})
        assert resp.status_code == 302
        cart = Cart.objects.get(user__username="attendee", conference=conference)
        assert cart.items.filter(ticket_type=ticket_type).exists()

    def test_add_ticket_increments_existing_item(self, client_logged_in, conference, ticket_type, cart_with_ticket):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.get(url, {"add_ticket": "general"})
        assert resp.status_code == 302
        item = CartItem.objects.get(cart=cart_with_ticket, ticket_type=ticket_type)
        assert item.quantity == 2

    def test_add_unavailable_ticket_shows_error(self, client_logged_in, conference, sold_out_ticket):
        # Make it sold out by creating an order with that ticket
        order = Order.objects.create(
            conference=conference,
            user=User.objects.get(username="attendee"),
            reference="ORD-SOLD01",
            status=Order.Status.PAID,
            subtotal=Decimal("500.00"),
            total=Decimal("500.00"),
        )
        OrderLineItem.objects.create(
            order=order,
            description="VIP",
            quantity=1,
            unit_price=Decimal("500.00"),
            line_total=Decimal("500.00"),
            ticket_type=sold_out_ticket,
        )
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.get(url, {"add_ticket": "vip"})
        assert resp.status_code == 302

    def test_add_nonexistent_ticket_slug_shows_error(self, client_logged_in, conference):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.get(url, {"add_ticket": "nonexistent"})
        assert resp.status_code == 302

    def test_cart_context_has_available_tickets_and_addons(self, client_logged_in, conference, ticket_type, addon):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.get(url)
        assert "available_tickets" in resp.context
        assert "available_addons" in resp.context
        assert "voucher_form" in resp.context
        assert "subtotal" in resp.context
        assert "discount" in resp.context
        assert "total" in resp.context


@pytest.mark.django_db
class TestCartViewPostAddItem:
    def test_add_ticket_via_form(self, client_logged_in, conference, ticket_type, cart):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "action": "add_item",
                "ticket_type_id": ticket_type.pk,
                "quantity": 2,
            },
        )
        assert resp.status_code == 302
        item = CartItem.objects.get(cart=cart, ticket_type=ticket_type)
        assert item.quantity == 2

    def test_add_addon_via_form(self, client_logged_in, conference, addon, cart):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "action": "add_item",
                "addon_id": addon.pk,
                "quantity": 1,
            },
        )
        assert resp.status_code == 302
        item = CartItem.objects.get(cart=cart, addon=addon)
        assert item.quantity == 1

    def test_add_item_increments_existing_ticket(self, client_logged_in, conference, ticket_type, cart_with_ticket):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        client_logged_in.post(
            url,
            {
                "action": "add_item",
                "ticket_type_id": ticket_type.pk,
                "quantity": 3,
            },
        )
        item = CartItem.objects.get(cart=cart_with_ticket, ticket_type=ticket_type)
        assert item.quantity == 4  # was 1, added 3

    def test_add_item_increments_existing_addon(self, client_logged_in, conference, addon, cart_with_addon):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        client_logged_in.post(
            url,
            {
                "action": "add_item",
                "addon_id": addon.pk,
                "quantity": 1,
            },
        )
        item = CartItem.objects.get(cart=cart_with_addon, addon=addon)
        assert item.quantity == 3  # was 2, added 1

    def test_add_item_invalid_form(self, client_logged_in, conference, cart):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "action": "add_item",
                # missing both ticket_type_id and addon_id and quantity
            },
        )
        assert resp.status_code == 302

    def test_add_unavailable_ticket_via_form(self, client_logged_in, conference, sold_out_ticket, cart, user):
        # Sell out the ticket
        order = Order.objects.create(
            conference=conference,
            user=user,
            reference="ORD-SOLD02",
            status=Order.Status.PAID,
            subtotal=Decimal("500.00"),
            total=Decimal("500.00"),
        )
        OrderLineItem.objects.create(
            order=order,
            description="VIP",
            quantity=1,
            unit_price=Decimal("500.00"),
            line_total=Decimal("500.00"),
            ticket_type=sold_out_ticket,
        )
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "action": "add_item",
                "ticket_type_id": sold_out_ticket.pk,
                "quantity": 1,
            },
        )
        assert resp.status_code == 302


@pytest.mark.django_db
class TestCartViewPostAddTicket:
    def test_add_ticket_by_slug(self, client_logged_in, conference, ticket_type, cart):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "action": "add_ticket",
                "ticket_type": "general",
                "quantity": 2,
            },
        )
        assert resp.status_code == 302
        item = CartItem.objects.get(cart=cart, ticket_type=ticket_type)
        assert item.quantity == 2

    def test_add_ticket_increments_existing(self, client_logged_in, conference, ticket_type, cart_with_ticket):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        client_logged_in.post(
            url,
            {
                "action": "add_ticket",
                "ticket_type": "general",
                "quantity": 1,
            },
        )
        item = CartItem.objects.get(cart=cart_with_ticket, ticket_type=ticket_type)
        assert item.quantity == 2

    def test_add_ticket_not_found(self, client_logged_in, conference, cart):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "action": "add_ticket",
                "ticket_type": "nonexistent",
            },
        )
        assert resp.status_code == 302

    def test_add_unavailable_ticket(self, client_logged_in, conference, sold_out_ticket, cart, user):
        order = Order.objects.create(
            conference=conference,
            user=user,
            reference="ORD-SOLD03",
            status=Order.Status.PAID,
            subtotal=Decimal("500.00"),
            total=Decimal("500.00"),
        )
        OrderLineItem.objects.create(
            order=order,
            description="VIP",
            quantity=1,
            unit_price=Decimal("500.00"),
            line_total=Decimal("500.00"),
            ticket_type=sold_out_ticket,
        )
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "action": "add_ticket",
                "ticket_type": "vip",
            },
        )
        assert resp.status_code == 302

    def test_add_ticket_default_quantity(self, client_logged_in, conference, ticket_type, cart):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        client_logged_in.post(
            url,
            {
                "action": "add_ticket",
                "ticket_type": "general",
            },
        )
        item = CartItem.objects.get(cart=cart, ticket_type=ticket_type)
        assert item.quantity == 1

    def test_add_ticket_invalid_quantity(self, client_logged_in, conference, cart):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "action": "add_ticket",
                "ticket_type": "general",
                "quantity": "abc",
            },
        )
        assert resp.status_code == 302
        assert not CartItem.objects.filter(cart=cart).exists()

    def test_add_ticket_zero_quantity(self, client_logged_in, conference, cart):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "action": "add_ticket",
                "ticket_type": "general",
                "quantity": 0,
            },
        )
        assert resp.status_code == 302
        assert not CartItem.objects.filter(cart=cart).exists()


@pytest.mark.django_db
class TestCartViewPostAddAddon:
    def test_add_addon_by_slug(self, client_logged_in, conference, addon, cart):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "action": "add_addon",
                "addon_slug": "workshop",
            },
        )
        assert resp.status_code == 302
        item = CartItem.objects.get(cart=cart, addon=addon)
        assert item.quantity == 1

    def test_add_addon_increments_existing(self, client_logged_in, conference, addon, cart_with_addon):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        client_logged_in.post(
            url,
            {
                "action": "add_addon",
                "addon_slug": "workshop",
            },
        )
        item = CartItem.objects.get(cart=cart_with_addon, addon=addon)
        assert item.quantity == 3  # was 2, added 1

    def test_add_addon_not_found(self, client_logged_in, conference, cart):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "action": "add_addon",
                "addon_slug": "nonexistent",
            },
        )
        assert resp.status_code == 302


@pytest.mark.django_db
class TestCartViewPostRemoveItem:
    def test_remove_item(self, client_logged_in, conference, cart_with_ticket, ticket_type):
        item = CartItem.objects.get(cart=cart_with_ticket, ticket_type=ticket_type)
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "action": "remove_item",
                "item_id": item.pk,
            },
        )
        assert resp.status_code == 302
        assert not CartItem.objects.filter(pk=item.pk).exists()

    def test_remove_nonexistent_item(self, client_logged_in, conference, cart):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "action": "remove_item",
                "item_id": 999999,
            },
        )
        assert resp.status_code == 302

    def test_remove_item_no_id(self, client_logged_in, conference, cart):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "action": "remove_item",
            },
        )
        assert resp.status_code == 302


@pytest.mark.django_db
class TestCartViewPostApplyVoucher:
    def test_apply_valid_voucher(self, client_logged_in, conference, cart, comp_voucher):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "action": "apply_voucher",
                "voucher_code": "COMP100",
            },
        )
        assert resp.status_code == 302
        cart.refresh_from_db()
        assert cart.voucher == comp_voucher

    def test_apply_voucher_via_code_field(self, client_logged_in, conference, cart, comp_voucher):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "action": "apply_voucher",
                "code": "COMP100",
            },
        )
        assert resp.status_code == 302
        cart.refresh_from_db()
        assert cart.voucher == comp_voucher

    def test_apply_voucher_case_insensitive(self, client_logged_in, conference, cart, comp_voucher):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        client_logged_in.post(
            url,
            {
                "action": "apply_voucher",
                "voucher_code": "comp100",
            },
        )
        cart.refresh_from_db()
        assert cart.voucher == comp_voucher

    def test_apply_empty_code(self, client_logged_in, conference, cart):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "action": "apply_voucher",
                "voucher_code": "",
            },
        )
        assert resp.status_code == 302
        cart.refresh_from_db()
        assert cart.voucher is None

    def test_apply_invalid_code(self, client_logged_in, conference, cart):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "action": "apply_voucher",
                "voucher_code": "BOGUS",
            },
        )
        assert resp.status_code == 302
        cart.refresh_from_db()
        assert cart.voucher is None

    def test_apply_expired_voucher(self, client_logged_in, conference, cart, expired_voucher):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "action": "apply_voucher",
                "voucher_code": "EXPIRED",
            },
        )
        assert resp.status_code == 302
        cart.refresh_from_db()
        assert cart.voucher is None


@pytest.mark.django_db
class TestCartViewPostRemoveVoucher:
    def test_remove_voucher(self, client_logged_in, conference, cart, comp_voucher):
        cart.voucher = comp_voucher
        cart.save()
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(url, {"action": "remove_voucher"})
        assert resp.status_code == 302
        cart.refresh_from_db()
        assert cart.voucher is None


@pytest.mark.django_db
class TestCartViewPostUnknownAction:
    def test_unknown_action(self, client_logged_in, conference, cart):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(url, {"action": "delete_everything"})
        assert resp.status_code == 302

    def test_no_action(self, client_logged_in, conference, cart):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(url, {})
        assert resp.status_code == 302


# ---------------------------------------------------------------------------
# CheckoutView tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCheckoutViewGet:
    def test_anonymous_redirects(self, anon_client, conference):
        url = reverse("registration:checkout", kwargs={"conference_slug": conference.slug})
        resp = anon_client.get(url)
        assert resp.status_code == 302
        assert "login" in resp.url

    def test_no_cart_redirects_to_cart(self, client_logged_in, conference):
        url = reverse("registration:checkout", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.get(url)
        assert resp.status_code == 302
        assert "cart" in resp.url

    def test_empty_cart_redirects(self, client_logged_in, conference, cart):
        url = reverse("registration:checkout", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.get(url)
        assert resp.status_code == 302

    def test_renders_with_items(self, client_logged_in, conference, cart_with_ticket):
        url = reverse("registration:checkout", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.get(url)
        assert resp.status_code == 200
        assert "form" in resp.context
        assert "cart" in resp.context
        assert "subtotal" in resp.context
        assert "total" in resp.context

    def test_billing_email_prefilled(self, client_logged_in, conference, cart_with_ticket, user):
        url = reverse("registration:checkout", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.get(url)
        form = resp.context["form"]
        assert form.initial["billing_email"] == user.email


@pytest.mark.django_db
class TestCheckoutViewPost:
    def test_no_cart_redirects(self, client_logged_in, conference):
        url = reverse("registration:checkout", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "billing_name": "Test User",
                "billing_email": "test@example.com",
            },
        )
        assert resp.status_code == 302
        assert "cart" in resp.url

    def test_empty_cart_redirects(self, client_logged_in, conference, cart):
        url = reverse("registration:checkout", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "billing_name": "Test User",
                "billing_email": "test@example.com",
            },
        )
        assert resp.status_code == 302

    def test_invalid_form_re_renders(self, client_logged_in, conference, cart_with_ticket):
        url = reverse("registration:checkout", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "billing_name": "",
                "billing_email": "not-an-email",
            },
        )
        assert resp.status_code == 200
        assert resp.context["form"].errors

    def test_successful_checkout_creates_order(self, client_logged_in, conference, cart_with_ticket, user):
        url = reverse("registration:checkout", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "billing_name": "Jane Doe",
                "billing_email": "jane@example.com",
                "billing_company": "Acme Inc",
            },
        )
        assert resp.status_code == 302
        order = Order.objects.get(conference=conference, user=user)
        assert order.billing_name == "Jane Doe"
        assert order.billing_email == "jane@example.com"
        assert order.billing_company == "Acme Inc"
        assert order.status == Order.Status.PENDING
        assert order.reference.startswith("ORD-")
        assert order.subtotal == Decimal("100.00")
        assert order.total == Decimal("100.00")
        assert "confirmation" in resp.url

    def test_checkout_creates_line_items(self, client_logged_in, conference, cart_with_ticket, ticket_type, user):
        url = reverse("registration:checkout", kwargs={"conference_slug": conference.slug})
        client_logged_in.post(
            url,
            {
                "billing_name": "Jane Doe",
                "billing_email": "jane@example.com",
            },
        )
        order = Order.objects.get(conference=conference, user=user)
        line_items = list(order.line_items.all())
        assert len(line_items) == 1
        assert line_items[0].description == "General Admission"
        assert line_items[0].quantity == 1
        assert line_items[0].unit_price == Decimal("100.00")
        assert line_items[0].ticket_type == ticket_type

    def test_checkout_marks_cart_as_checked_out(self, client_logged_in, conference, cart_with_ticket, user):
        url = reverse("registration:checkout", kwargs={"conference_slug": conference.slug})
        client_logged_in.post(
            url,
            {
                "billing_name": "Jane Doe",
                "billing_email": "jane@example.com",
            },
        )
        cart_with_ticket.refresh_from_db()
        assert cart_with_ticket.status == Cart.Status.CHECKED_OUT

    def test_checkout_with_voucher(self, client_logged_in, conference, cart_with_ticket, comp_voucher, user):
        cart_with_ticket.voucher = comp_voucher
        cart_with_ticket.save()
        url = reverse("registration:checkout", kwargs={"conference_slug": conference.slug})
        client_logged_in.post(
            url,
            {
                "billing_name": "Jane Doe",
                "billing_email": "jane@example.com",
            },
        )
        order = Order.objects.get(conference=conference, user=user)
        assert order.voucher_code == "COMP100"
        assert "comp" in order.voucher_details
        assert order.discount_amount == Decimal("100.00")
        assert order.total == Decimal("0.00")

        comp_voucher.refresh_from_db()
        assert comp_voucher.times_used == 1

    def test_checkout_sets_hold_expires(self, client_logged_in, conference, cart_with_ticket, user):
        url = reverse("registration:checkout", kwargs={"conference_slug": conference.slug})
        before = timezone.now()
        client_logged_in.post(
            url,
            {
                "billing_name": "Jane Doe",
                "billing_email": "jane@example.com",
            },
        )
        order = Order.objects.get(conference=conference, user=user)
        assert order.hold_expires_at is not None
        assert order.hold_expires_at > before + timedelta(minutes=29)

    def test_checkout_with_addon_item(self, client_logged_in, conference, cart_with_addon, addon, user):
        url = reverse("registration:checkout", kwargs={"conference_slug": conference.slug})
        client_logged_in.post(
            url,
            {
                "billing_name": "Jane Doe",
                "billing_email": "jane@example.com",
            },
        )
        order = Order.objects.get(conference=conference, user=user)
        line_items = list(order.line_items.all())
        assert len(line_items) == 1
        assert line_items[0].description == "Workshop"
        assert line_items[0].addon == addon
        assert line_items[0].quantity == 2

    def test_checkout_redirects_to_confirmation(self, client_logged_in, conference, cart_with_ticket, user):
        url = reverse("registration:checkout", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "billing_name": "Jane Doe",
                "billing_email": "jane@example.com",
            },
        )
        order = Order.objects.get(conference=conference, user=user)
        expected_url = reverse(
            "registration:order-confirmation",
            kwargs={"conference_slug": conference.slug, "reference": order.reference},
        )
        assert resp.url == expected_url

    def test_checkout_retries_on_reference_collision(self, client_logged_in, conference, cart_with_ticket, user):
        # Pre-create an order with a known reference
        Order.objects.create(
            conference=conference,
            user=user,
            reference="ORD-DUPE01",
            status=Order.Status.PAID,
            subtotal=Decimal(0),
            total=Decimal(0),
        )
        # First call returns the colliding reference, second returns a unique one
        with patch(
            "django_program.registration.views._generate_order_reference",
            side_effect=["ORD-DUPE01", "ORD-UNIQ99"],
        ):
            url = reverse("registration:checkout", kwargs={"conference_slug": conference.slug})
            resp = client_logged_in.post(
                url,
                {
                    "billing_name": "Jane Doe",
                    "billing_email": "jane@example.com",
                },
            )
        assert resp.status_code == 302
        new_order = Order.objects.get(reference="ORD-UNIQ99")
        assert new_order.user == user

    def test_checkout_with_expired_voucher(self, client_logged_in, conference, cart_with_ticket, user):
        expired_voucher = Voucher.objects.create(
            conference=conference,
            code="EXPIRED01",
            voucher_type="percentage",
            discount_value=Decimal(50),
            is_active=False,
            max_uses=10,
            times_used=0,
        )
        cart_with_ticket.voucher = expired_voucher
        cart_with_ticket.save()
        url = reverse("registration:checkout", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in.post(
            url,
            {
                "billing_name": "Jane Doe",
                "billing_email": "jane@example.com",
            },
        )
        assert resp.status_code == 200
        assert not Order.objects.filter(conference=conference, user=user).exists()


# ---------------------------------------------------------------------------
# OrderConfirmationView tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestOrderConfirmationView:
    @pytest.fixture
    def order(self, conference, user, ticket_type):
        o = Order.objects.create(
            conference=conference,
            user=user,
            reference="ORD-TEST01",
            status=Order.Status.PENDING,
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
        )
        OrderLineItem.objects.create(
            order=o,
            description="General Admission",
            quantity=1,
            unit_price=Decimal("100.00"),
            line_total=Decimal("100.00"),
            ticket_type=ticket_type,
        )
        return o

    def test_anonymous_redirects(self, anon_client, conference, order):
        url = reverse(
            "registration:order-confirmation",
            kwargs={"conference_slug": conference.slug, "reference": order.reference},
        )
        resp = anon_client.get(url)
        assert resp.status_code == 302

    def test_renders_for_owner(self, client_logged_in, conference, order):
        url = reverse(
            "registration:order-confirmation",
            kwargs={"conference_slug": conference.slug, "reference": order.reference},
        )
        resp = client_logged_in.get(url)
        assert resp.status_code == 200
        assert resp.context["order"] == order
        assert "line_items" in resp.context

    def test_other_user_gets_404(self, client_other_user, conference, order):
        url = reverse(
            "registration:order-confirmation",
            kwargs={"conference_slug": conference.slug, "reference": order.reference},
        )
        resp = client_other_user.get(url)
        assert resp.status_code == 404

    def test_nonexistent_reference_404(self, client_logged_in, conference):
        url = reverse(
            "registration:order-confirmation",
            kwargs={"conference_slug": conference.slug, "reference": "ORD-NOPE00"},
        )
        resp = client_logged_in.get(url)
        assert resp.status_code == 404

    def test_renders_order_reference_in_content(self, client_logged_in, conference, order):
        url = reverse(
            "registration:order-confirmation",
            kwargs={"conference_slug": conference.slug, "reference": order.reference},
        )
        resp = client_logged_in.get(url)
        assert order.reference.encode() in resp.content


# ---------------------------------------------------------------------------
# OrderDetailView tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestOrderDetailView:
    @pytest.fixture
    def order(self, conference, user, ticket_type):
        o = Order.objects.create(
            conference=conference,
            user=user,
            reference="ORD-DET001",
            status=Order.Status.PAID,
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
        )
        OrderLineItem.objects.create(
            order=o,
            description="General Admission",
            quantity=1,
            unit_price=Decimal("100.00"),
            line_total=Decimal("100.00"),
            ticket_type=ticket_type,
        )
        return o

    @pytest.fixture
    def payment(self, order):
        return Payment.objects.create(
            order=order,
            method=Payment.Method.STRIPE,
            amount=Decimal("100.00"),
            status=Payment.Status.SUCCEEDED,
        )

    def test_anonymous_redirects(self, anon_client, conference, order):
        url = reverse(
            "registration:order-detail",
            kwargs={"conference_slug": conference.slug, "reference": order.reference},
        )
        resp = anon_client.get(url)
        assert resp.status_code == 302

    def test_renders_for_owner(self, client_logged_in, conference, order, payment):
        url = reverse(
            "registration:order-detail",
            kwargs={"conference_slug": conference.slug, "reference": order.reference},
        )
        resp = client_logged_in.get(url)
        assert resp.status_code == 200
        assert resp.context["order"] == order
        assert "line_items" in resp.context
        assert "payments" in resp.context

    def test_other_user_gets_404(self, client_other_user, conference, order):
        url = reverse(
            "registration:order-detail",
            kwargs={"conference_slug": conference.slug, "reference": order.reference},
        )
        resp = client_other_user.get(url)
        assert resp.status_code == 404

    def test_nonexistent_reference_404(self, client_logged_in, conference):
        url = reverse(
            "registration:order-detail",
            kwargs={"conference_slug": conference.slug, "reference": "ORD-NOPE00"},
        )
        resp = client_logged_in.get(url)
        assert resp.status_code == 404

    def test_renders_order_reference_in_content(self, client_logged_in, conference, order):
        url = reverse(
            "registration:order-detail",
            kwargs={"conference_slug": conference.slug, "reference": order.reference},
        )
        resp = client_logged_in.get(url)
        assert order.reference.encode() in resp.content

    def test_renders_payment_history(self, client_logged_in, conference, order, payment):
        url = reverse(
            "registration:order-detail",
            kwargs={"conference_slug": conference.slug, "reference": order.reference},
        )
        resp = client_logged_in.get(url)
        payments = list(resp.context["payments"])
        assert len(payments) == 1
        assert payments[0] == payment


# ---------------------------------------------------------------------------
# URL routing tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestURLRouting:
    def test_ticket_select_url(self, conference):
        url = reverse("registration:ticket-select", kwargs={"conference_slug": conference.slug})
        assert url == f"/{conference.slug}/register/"

    def test_cart_url(self, conference):
        url = reverse("registration:cart", kwargs={"conference_slug": conference.slug})
        assert url == f"/{conference.slug}/register/cart/"

    def test_checkout_url(self, conference):
        url = reverse("registration:checkout", kwargs={"conference_slug": conference.slug})
        assert url == f"/{conference.slug}/register/checkout/"

    def test_order_detail_url(self, conference):
        url = reverse(
            "registration:order-detail",
            kwargs={"conference_slug": conference.slug, "reference": "ORD-ABC123"},
        )
        assert url == f"/{conference.slug}/register/orders/ORD-ABC123/"

    def test_order_confirmation_url(self, conference):
        url = reverse(
            "registration:order-confirmation",
            kwargs={"conference_slug": conference.slug, "reference": "ORD-ABC123"},
        )
        assert url == f"/{conference.slug}/register/orders/ORD-ABC123/confirmation/"
