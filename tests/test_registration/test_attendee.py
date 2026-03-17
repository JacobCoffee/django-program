"""Tests for the attendee profile system."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import override_settings

from django_program.conference.models import Conference
from django_program.registration.attendee import Attendee, AttendeeProfileBase
from django_program.registration.models import Order
from django_program.registration.signals import order_paid
from django_program.settings import get_attendee_profile_model

User = get_user_model()

pytestmark = pytest.mark.django_db


# -- Helpers ------------------------------------------------------------------


def _make_conference(**kwargs: object) -> Conference:
    defaults: dict[str, object] = {
        "name": "TestCon",
        "slug": f"testcon-{uuid4().hex[:6]}",
        "start_date": date(2026, 7, 1),
        "end_date": date(2026, 7, 5),
    }
    defaults.update(kwargs)
    return Conference.objects.create(**defaults)


def _make_user(**kwargs: object) -> object:
    defaults: dict[str, object] = {
        "username": f"user-{uuid4().hex[:8]}",
        "email": f"{uuid4().hex[:8]}@test.com",
    }
    defaults.update(kwargs)
    return User.objects.create_user(**defaults)


def _make_order(*, conference: Conference, user: object, status: str = Order.Status.PAID) -> Order:
    return Order.objects.create(
        conference=conference,
        user=user,
        status=status,
        subtotal=Decimal("100.00"),
        total=Decimal("100.00"),
        reference=f"ORD-{uuid4().hex[:8].upper()}",
    )


# -- Tests: Attendee model ---------------------------------------------------


@pytest.mark.unit
class TestAttendeeModel:
    """Tests for the Attendee concrete model."""

    def test_attendee_creation_generates_access_code(self) -> None:
        conf = _make_conference()
        user = _make_user()
        attendee = Attendee.objects.create(user=user, conference=conf)
        assert len(attendee.access_code) == 8
        assert attendee.access_code.isalnum()
        assert attendee.access_code == attendee.access_code.upper()

    def test_attendee_access_code_unique(self) -> None:
        conf = _make_conference()
        a1 = Attendee.objects.create(user=_make_user(), conference=conf)
        a2 = Attendee.objects.create(user=_make_user(), conference=conf)
        assert a1.access_code != a2.access_code

    def test_attendee_unique_together(self) -> None:
        conf = _make_conference()
        user = _make_user()
        Attendee.objects.create(user=user, conference=conf)
        with pytest.raises(IntegrityError):
            Attendee.objects.create(user=user, conference=conf)

    def test_attendee_str(self) -> None:
        conf = _make_conference()
        user = _make_user()
        attendee = Attendee.objects.create(user=user, conference=conf)
        assert str(attendee) == f"{user} @ {conf}"

    def test_attendee_order_link(self) -> None:
        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        attendee = Attendee.objects.create(user=user, conference=conf, order=order)
        assert attendee.order == order
        assert order.attendees.first() == attendee


# -- Tests: Signal handler ---------------------------------------------------


@pytest.mark.unit
class TestOrderPaidSignal:
    """Tests for the create_attendee_on_order_paid signal handler."""

    def test_signal_creates_attendee_on_order_paid(self) -> None:
        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        order_paid.send(sender=Order, order=order, user=user)
        attendee = Attendee.objects.get(user=user, conference=conf)
        assert attendee.order == order
        assert attendee.completed_registration is True

    def test_signal_idempotent(self) -> None:
        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        order_paid.send(sender=Order, order=order, user=user)
        order_paid.send(sender=Order, order=order, user=user)
        assert Attendee.objects.filter(user=user, conference=conf).count() == 1

    def test_signal_updates_order_link(self) -> None:
        conf = _make_conference()
        user = _make_user()
        order1 = _make_order(conference=conf, user=user)
        order_paid.send(sender=Order, order=order1, user=user)

        # Second order for same user+conference — the attendee's order FK updates
        order2 = _make_order(conference=conf, user=user)
        # Must unlink order1 first since order is OneToOne
        attendee = Attendee.objects.get(user=user, conference=conf)
        attendee.order = None
        attendee.save(update_fields=["order", "updated_at"])

        order_paid.send(sender=Order, order=order2, user=user)
        attendee.refresh_from_db()
        assert attendee.order == order2


# -- Tests: Settings helpers --------------------------------------------------


@pytest.mark.unit
class TestAttendeeProfileSettings:
    """Tests for the swappable attendee profile model setting."""

    def test_get_attendee_profile_model_none_by_default(self) -> None:
        assert get_attendee_profile_model() is None

    @override_settings(DJANGO_PROGRAM={"attendee_profile_model": "program_registration.Attendee"})
    def test_get_attendee_profile_model_resolves(self) -> None:
        model = get_attendee_profile_model()
        assert model is Attendee


# -- Tests: Abstract base ----------------------------------------------------


@pytest.mark.unit
class TestAttendeeProfileBase:
    """Tests for the AttendeeProfileBase abstract model."""

    def test_abstract_base_cannot_instantiate(self) -> None:
        assert AttendeeProfileBase._meta.abstract is True
