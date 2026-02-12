"""Tests for registration template tags and filters."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.template import Context, Template

from django_program.conference.models import Conference
from django_program.registration.models import (
    AddOn,
    Cart,
    CartItem,
    Order,
    OrderLineItem,
    TicketType,
)
from django_program.registration.templatetags.registration_tags import (
    cart_total,
    format_currency,
    ticket_availability,
)

User = get_user_model()


def _now() -> datetime:
    return datetime(2027, 1, 15, 12, 0, tzinfo=UTC)


def _create_order(*, conference: Conference, user, status: str) -> Order:
    return Order.objects.create(
        conference=conference,
        user=user,
        status=status,
        subtotal=Decimal("0.00"),
        total=Decimal("0.00"),
        reference=f"ORD-{uuid4().hex[:8].upper()}",
    )


@pytest.fixture
def conference() -> Conference:
    return Conference.objects.create(
        name="TagCon",
        slug="tagcon",
        start_date=date(2027, 6, 1),
        end_date=date(2027, 6, 3),
        timezone="UTC",
    )


@pytest.fixture
def user():
    return User.objects.create_user(
        username="tag-user",
        email="tag@example.com",
        password="testpass123",
    )


# ---------------------------------------------------------------------------
# cart_total
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_cart_total_empty_cart(conference: Conference, user):
    cart = Cart.objects.create(user=user, conference=conference, status=Cart.Status.OPEN)

    result = cart_total(cart)

    assert result == Decimal("0.00")


@pytest.mark.django_db
def test_cart_total_with_ticket_items(conference: Conference, user):
    ticket = TicketType.objects.create(
        conference=conference,
        name="Standard",
        slug="standard",
        price=Decimal("50.00"),
    )
    cart = Cart.objects.create(user=user, conference=conference, status=Cart.Status.OPEN)
    CartItem.objects.create(cart=cart, ticket_type=ticket, quantity=2)

    result = cart_total(cart)

    assert result == Decimal("100.00")


@pytest.mark.django_db
def test_cart_total_with_mixed_items(conference: Conference, user):
    ticket = TicketType.objects.create(
        conference=conference,
        name="Standard",
        slug="standard",
        price=Decimal("50.00"),
    )
    addon = AddOn.objects.create(
        conference=conference,
        name="Workshop",
        slug="workshop",
        price=Decimal("25.00"),
    )
    cart = Cart.objects.create(user=user, conference=conference, status=Cart.Status.OPEN)
    CartItem.objects.create(cart=cart, ticket_type=ticket, quantity=2)
    CartItem.objects.create(cart=cart, addon=addon, quantity=3)

    result = cart_total(cart)

    assert result == Decimal("175.00")


@pytest.mark.django_db
def test_cart_total_template_rendering(conference: Conference, user):
    ticket = TicketType.objects.create(
        conference=conference,
        name="Standard",
        slug="standard",
        price=Decimal("42.50"),
    )
    cart = Cart.objects.create(user=user, conference=conference, status=Cart.Status.OPEN)
    CartItem.objects.create(cart=cart, ticket_type=ticket, quantity=1)

    tpl = Template("{% load registration_tags %}{% cart_total cart as total %}{{ total }}")
    rendered = tpl.render(Context({"cart": cart}))

    assert rendered.strip() == "42.50"


# ---------------------------------------------------------------------------
# format_currency
# ---------------------------------------------------------------------------


def test_format_currency_usd_default():
    assert format_currency(Decimal("10.00")) == "$10.00"


def test_format_currency_usd_explicit():
    assert format_currency(Decimal("10.00"), "USD") == "$10.00"


def test_format_currency_none_returns_zero():
    assert format_currency(None) == "$0.00"


def test_format_currency_none_with_currency():
    assert format_currency(None, "EUR") == "\u20ac0.00"


def test_format_currency_zero_decimal_jpy():
    assert format_currency(Decimal(1000), "JPY") == "\u00a51000"


def test_format_currency_zero_decimal_krw():
    assert format_currency(Decimal(5000), "KRW") == "\u20a95000"


def test_format_currency_eur():
    assert format_currency(Decimal("99.99"), "EUR") == "\u20ac99.99"


def test_format_currency_gbp():
    assert format_currency(Decimal("15.50"), "GBP") == "\u00a315.50"


def test_format_currency_unknown_currency():
    result = format_currency(Decimal("100.00"), "CHF")
    assert result == "CHF 100.00"


def test_format_currency_case_insensitive():
    assert format_currency(Decimal("10.00"), "usd") == "$10.00"


def test_format_currency_template_rendering():
    tpl = Template("{% load registration_tags %}{{ amount|format_currency }}")
    rendered = tpl.render(Context({"amount": Decimal("42.50")}))
    assert rendered.strip() == "$42.50"


def test_format_currency_template_with_currency_arg():
    tpl = Template('{% load registration_tags %}{{ amount|format_currency:"JPY" }}')
    rendered = tpl.render(Context({"amount": Decimal(1000)}))
    assert rendered.strip() == "\u00a51000"


# ---------------------------------------------------------------------------
# ticket_availability
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_ticket_availability_available_unlimited(conference: Conference):
    ticket = TicketType.objects.create(
        conference=conference,
        name="Unlimited",
        slug="unlimited",
        price=Decimal("10.00"),
        total_quantity=0,
        is_active=True,
    )

    assert ticket_availability(ticket) == "Available"


@pytest.mark.django_db
def test_ticket_availability_remaining(conference: Conference):
    ticket = TicketType.objects.create(
        conference=conference,
        name="Limited",
        slug="limited",
        price=Decimal("50.00"),
        total_quantity=10,
        is_active=True,
    )

    assert ticket_availability(ticket) == "10 remaining"


@pytest.mark.django_db
def test_ticket_availability_sold_out(conference: Conference, user, monkeypatch):
    now = _now()
    monkeypatch.setattr(
        "django_program.registration.templatetags.registration_tags.timezone.now",
        lambda: now,
    )
    monkeypatch.setattr(
        "django_program.registration.models.timezone.now",
        lambda: now,
    )
    ticket = TicketType.objects.create(
        conference=conference,
        name="Sold Out",
        slug="sold-out",
        price=Decimal("50.00"),
        total_quantity=2,
        is_active=True,
    )
    order = _create_order(conference=conference, user=user, status=Order.Status.PAID)
    OrderLineItem.objects.create(
        order=order,
        ticket_type=ticket,
        description="Sold Out Ticket",
        quantity=2,
        unit_price=Decimal("50.00"),
        line_total=Decimal("100.00"),
    )

    assert ticket_availability(ticket) == "Sold Out"


@pytest.mark.django_db
def test_ticket_availability_coming_soon(conference: Conference, monkeypatch):
    now = _now()
    monkeypatch.setattr(
        "django_program.registration.templatetags.registration_tags.timezone.now",
        lambda: now,
    )
    ticket = TicketType.objects.create(
        conference=conference,
        name="Future",
        slug="future",
        price=Decimal("50.00"),
        total_quantity=0,
        is_active=True,
        available_from=now + timedelta(days=7),
    )

    assert ticket_availability(ticket) == "Coming Soon"


@pytest.mark.django_db
def test_ticket_availability_ended(conference: Conference, monkeypatch):
    now = _now()
    monkeypatch.setattr(
        "django_program.registration.templatetags.registration_tags.timezone.now",
        lambda: now,
    )
    ticket = TicketType.objects.create(
        conference=conference,
        name="Past",
        slug="past",
        price=Decimal("50.00"),
        total_quantity=0,
        is_active=True,
        available_until=now - timedelta(days=1),
    )

    assert ticket_availability(ticket) == "Ended"


@pytest.mark.django_db
def test_ticket_availability_inactive(conference: Conference):
    ticket = TicketType.objects.create(
        conference=conference,
        name="Disabled",
        slug="disabled",
        price=Decimal("50.00"),
        total_quantity=0,
        is_active=False,
    )

    assert ticket_availability(ticket) == "Unavailable"


@pytest.mark.django_db
def test_ticket_availability_template_rendering(conference: Conference):
    ticket = TicketType.objects.create(
        conference=conference,
        name="Unlimited",
        slug="unlimited",
        price=Decimal("10.00"),
        total_quantity=0,
        is_active=True,
    )
    tpl = Template("{% load registration_tags %}{% ticket_availability ticket_type as status %}{{ status }}")
    rendered = tpl.render(Context({"ticket_type": ticket}))

    assert rendered.strip() == "Available"
