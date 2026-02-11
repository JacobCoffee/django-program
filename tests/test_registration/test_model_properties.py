"""Tests for registration model computed properties."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from django_program.conference.models import Conference
from django_program.registration.models import Order, OrderLineItem, TicketType, Voucher

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
        name="PropCon",
        slug="propcon",
        start_date=date(2027, 5, 1),
        end_date=date(2027, 5, 3),
        timezone="UTC",
    )


@pytest.fixture
def user():
    return User.objects.create_user(username="prop-user", email="prop@example.com", password="testpass123")


@pytest.mark.django_db
def test_remaining_quantity_is_none_for_unlimited_ticket(conference: Conference):
    ticket = TicketType.objects.create(
        conference=conference,
        name="Unlimited",
        slug="unlimited",
        price=Decimal("10.00"),
        total_quantity=0,
    )

    assert ticket.remaining_quantity is None


@pytest.mark.django_db
def test_remaining_quantity_counts_only_paid_like_statuses(conference: Conference, user):
    ticket = TicketType.objects.create(
        conference=conference,
        name="Limited",
        slug="limited",
        price=Decimal("50.00"),
        total_quantity=10,
    )

    paid = _create_order(conference=conference, user=user, status=Order.Status.PAID)
    partial = _create_order(conference=conference, user=user, status=Order.Status.PARTIALLY_REFUNDED)
    pending = _create_order(conference=conference, user=user, status=Order.Status.PENDING)
    refunded = _create_order(conference=conference, user=user, status=Order.Status.REFUNDED)

    OrderLineItem.objects.create(
        order=paid,
        ticket_type=ticket,
        description="Paid",
        quantity=2,
        unit_price=Decimal("50.00"),
        line_total=Decimal("100.00"),
    )
    OrderLineItem.objects.create(
        order=partial,
        ticket_type=ticket,
        description="Partial",
        quantity=3,
        unit_price=Decimal("50.00"),
        line_total=Decimal("150.00"),
    )
    OrderLineItem.objects.create(
        order=pending,
        ticket_type=ticket,
        description="Pending",
        quantity=4,
        unit_price=Decimal("50.00"),
        line_total=Decimal("200.00"),
    )
    OrderLineItem.objects.create(
        order=refunded,
        ticket_type=ticket,
        description="Refunded",
        quantity=1,
        unit_price=Decimal("50.00"),
        line_total=Decimal("50.00"),
    )

    assert ticket.remaining_quantity == 5


@pytest.mark.django_db
def test_ticket_is_available_respects_window_and_boundaries(conference: Conference, monkeypatch):
    now = _now()
    ticket = TicketType.objects.create(
        conference=conference,
        name="Windowed",
        slug="windowed",
        price=Decimal("50.00"),
        total_quantity=0,
        available_from=now,
        available_until=now + timedelta(hours=2),
    )

    monkeypatch.setattr("django_program.registration.models.timezone.now", lambda: now - timedelta(seconds=1))
    assert ticket.is_available is False

    monkeypatch.setattr("django_program.registration.models.timezone.now", lambda: now)
    assert ticket.is_available is True

    monkeypatch.setattr("django_program.registration.models.timezone.now", lambda: now + timedelta(hours=2))
    assert ticket.is_available is True

    monkeypatch.setattr("django_program.registration.models.timezone.now", lambda: now + timedelta(hours=2, seconds=1))
    assert ticket.is_available is False


@pytest.mark.django_db
def test_ticket_is_available_false_when_sold_out(conference: Conference, user, monkeypatch):
    now = _now()
    monkeypatch.setattr("django_program.registration.models.timezone.now", lambda: now)

    ticket = TicketType.objects.create(
        conference=conference,
        name="Sold Out",
        slug="sold-out",
        price=Decimal("50.00"),
        total_quantity=2,
        available_from=now - timedelta(days=1),
        available_until=now + timedelta(days=1),
    )
    paid = _create_order(conference=conference, user=user, status=Order.Status.PAID)
    OrderLineItem.objects.create(
        order=paid,
        ticket_type=ticket,
        description="Sold",
        quantity=2,
        unit_price=Decimal("50.00"),
        line_total=Decimal("100.00"),
    )

    assert ticket.is_available is False


@pytest.mark.django_db
def test_voucher_is_valid_respects_usage_and_activity(conference: Conference):
    voucher = Voucher.objects.create(
        conference=conference,
        code="ACTIVE-1",
        voucher_type=Voucher.VoucherType.COMP,
        max_uses=2,
        times_used=1,
        is_active=True,
    )
    assert voucher.is_valid is True

    voucher.times_used = 2
    voucher.save(update_fields=["times_used"])
    assert voucher.is_valid is False

    voucher.times_used = 0
    voucher.is_active = False
    voucher.save(update_fields=["times_used", "is_active"])
    assert voucher.is_valid is False


@pytest.mark.django_db
def test_voucher_is_valid_respects_time_window_boundaries(conference: Conference, monkeypatch):
    now = _now()
    voucher = Voucher.objects.create(
        conference=conference,
        code="WINDOW-1",
        voucher_type=Voucher.VoucherType.COMP,
        max_uses=10,
        times_used=0,
        valid_from=now,
        valid_until=now + timedelta(hours=1),
        is_active=True,
    )

    monkeypatch.setattr("django_program.registration.models.timezone.now", lambda: now - timedelta(seconds=1))
    assert voucher.is_valid is False

    monkeypatch.setattr("django_program.registration.models.timezone.now", lambda: now)
    assert voucher.is_valid is True

    monkeypatch.setattr("django_program.registration.models.timezone.now", lambda: now + timedelta(hours=1))
    assert voucher.is_valid is True

    monkeypatch.setattr("django_program.registration.models.timezone.now", lambda: now + timedelta(hours=1, seconds=1))
    assert voucher.is_valid is False
