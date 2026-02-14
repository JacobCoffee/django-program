"""Tests for global capacity enforcement in django_program.registration.services.capacity."""

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
    Order,
    OrderLineItem,
    TicketType,
)
from django_program.registration.services.capacity import (
    get_global_remaining,
    get_global_sold_count,
    validate_global_capacity,
)

User = get_user_model()


def _make_order(*, conference, user, status, reference=None, hold_expires_at=None):
    kwargs = {
        "conference": conference,
        "user": user,
        "status": status,
        "subtotal": Decimal("0.00"),
        "total": Decimal("0.00"),
        "reference": reference or f"ORD-{uuid4().hex[:8].upper()}",
    }
    if hold_expires_at is not None:
        kwargs["hold_expires_at"] = hold_expires_at
    return Order.objects.create(**kwargs)


@pytest.fixture
def conference():
    return Conference.objects.create(
        name="CapCon",
        slug="capcon",
        start_date=date(2027, 6, 1),
        end_date=date(2027, 6, 3),
        timezone="UTC",
        total_capacity=10,
    )


@pytest.fixture
def unlimited_conference():
    return Conference.objects.create(
        name="UnlimitedCon",
        slug="unlimitedcon",
        start_date=date(2027, 7, 1),
        end_date=date(2027, 7, 3),
        timezone="UTC",
        total_capacity=0,
    )


@pytest.fixture
def user():
    return User.objects.create_user(
        username="capuser",
        email="cap@example.com",
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
def addon(conference):
    return AddOn.objects.create(
        conference=conference,
        name="T-Shirt",
        slug="tshirt",
        price=Decimal("25.00"),
        total_quantity=0,
        is_active=True,
    )


@pytest.mark.django_db
class TestGetGlobalSoldCount:
    def test_empty_conference_returns_zero(self, conference):
        assert get_global_sold_count(conference) == 0

    def test_counts_paid_orders(self, conference, user, ticket_type):
        order = _make_order(conference=conference, user=user, status=Order.Status.PAID)
        OrderLineItem.objects.create(
            order=order,
            description="Ticket",
            quantity=3,
            unit_price=Decimal("100.00"),
            line_total=Decimal("300.00"),
            ticket_type=ticket_type,
        )
        assert get_global_sold_count(conference) == 3

    def test_counts_partially_refunded(self, conference, user, ticket_type):
        order = _make_order(conference=conference, user=user, status=Order.Status.PARTIALLY_REFUNDED)
        OrderLineItem.objects.create(
            order=order,
            description="Ticket",
            quantity=2,
            unit_price=Decimal("100.00"),
            line_total=Decimal("200.00"),
            ticket_type=ticket_type,
        )
        assert get_global_sold_count(conference) == 2

    def test_counts_pending_with_active_hold(self, conference, user, ticket_type):
        future = timezone.now() + timedelta(minutes=30)
        order = _make_order(
            conference=conference,
            user=user,
            status=Order.Status.PENDING,
            hold_expires_at=future,
        )
        OrderLineItem.objects.create(
            order=order,
            description="Ticket",
            quantity=1,
            unit_price=Decimal("100.00"),
            line_total=Decimal("100.00"),
            ticket_type=ticket_type,
        )
        assert get_global_sold_count(conference) == 1

    def test_ignores_pending_with_expired_hold(self, conference, user, ticket_type):
        past = timezone.now() - timedelta(minutes=30)
        order = _make_order(
            conference=conference,
            user=user,
            status=Order.Status.PENDING,
            hold_expires_at=past,
        )
        OrderLineItem.objects.create(
            order=order,
            description="Ticket",
            quantity=5,
            unit_price=Decimal("100.00"),
            line_total=Decimal("500.00"),
            ticket_type=ticket_type,
        )
        assert get_global_sold_count(conference) == 0

    def test_ignores_cancelled_orders(self, conference, user, ticket_type):
        order = _make_order(conference=conference, user=user, status=Order.Status.CANCELLED)
        OrderLineItem.objects.create(
            order=order,
            description="Ticket",
            quantity=4,
            unit_price=Decimal("100.00"),
            line_total=Decimal("400.00"),
            ticket_type=ticket_type,
        )
        assert get_global_sold_count(conference) == 0

    def test_ignores_refunded_orders(self, conference, user, ticket_type):
        order = _make_order(conference=conference, user=user, status=Order.Status.REFUNDED)
        OrderLineItem.objects.create(
            order=order,
            description="Ticket",
            quantity=4,
            unit_price=Decimal("100.00"),
            line_total=Decimal("400.00"),
            ticket_type=ticket_type,
        )
        assert get_global_sold_count(conference) == 0

    def test_excludes_addons(self, conference, user, addon):
        order = _make_order(conference=conference, user=user, status=Order.Status.PAID)
        OrderLineItem.objects.create(
            order=order,
            description="T-Shirt",
            quantity=10,
            unit_price=Decimal("25.00"),
            line_total=Decimal("250.00"),
            addon=addon,
        )
        assert get_global_sold_count(conference) == 0

    def test_sums_across_ticket_types(self, conference, user):
        tt_a = TicketType.objects.create(
            conference=conference,
            name="A",
            slug="a",
            price=Decimal("50.00"),
            total_quantity=0,
            limit_per_user=10,
            is_active=True,
        )
        tt_b = TicketType.objects.create(
            conference=conference,
            name="B",
            slug="b",
            price=Decimal("75.00"),
            total_quantity=0,
            limit_per_user=10,
            is_active=True,
        )
        order = _make_order(conference=conference, user=user, status=Order.Status.PAID)
        OrderLineItem.objects.create(
            order=order,
            description="A",
            quantity=3,
            unit_price=Decimal("50.00"),
            line_total=Decimal("150.00"),
            ticket_type=tt_a,
        )
        OrderLineItem.objects.create(
            order=order,
            description="B",
            quantity=4,
            unit_price=Decimal("75.00"),
            line_total=Decimal("300.00"),
            ticket_type=tt_b,
        )
        assert get_global_sold_count(conference) == 7


@pytest.mark.django_db
class TestGetGlobalRemaining:
    def test_no_limit_returns_none(self, unlimited_conference):
        assert get_global_remaining(unlimited_conference) is None

    def test_returns_remaining_when_limit_set(self, conference, user, ticket_type):
        order = _make_order(conference=conference, user=user, status=Order.Status.PAID)
        OrderLineItem.objects.create(
            order=order,
            description="Ticket",
            quantity=3,
            unit_price=Decimal("100.00"),
            line_total=Decimal("300.00"),
            ticket_type=ticket_type,
        )
        assert get_global_remaining(conference) == 7  # 10 - 3

    def test_empty_conference_returns_full_capacity(self, conference):
        assert get_global_remaining(conference) == 10


@pytest.mark.django_db
class TestValidateGlobalCapacity:
    def test_no_limit_bypasses_validation(self, unlimited_conference):
        validate_global_capacity(unlimited_conference, 99999)

    def test_under_capacity_passes(self, conference):
        validate_global_capacity(conference, 5)

    def test_at_capacity_passes(self, conference):
        validate_global_capacity(conference, 10)

    def test_over_capacity_raises(self, conference):
        with pytest.raises(ValidationError, match="Only 10 tickets remaining"):
            validate_global_capacity(conference, 11)

    def test_over_capacity_with_existing_sales(self, conference, user, ticket_type):
        order = _make_order(conference=conference, user=user, status=Order.Status.PAID)
        OrderLineItem.objects.create(
            order=order,
            description="Ticket",
            quantity=8,
            unit_price=Decimal("100.00"),
            line_total=Decimal("800.00"),
            ticket_type=ticket_type,
        )
        validate_global_capacity(conference, 2)  # 8 sold + 2 new = 10

        with pytest.raises(ValidationError, match="Only 2 tickets remaining"):
            validate_global_capacity(conference, 3)
