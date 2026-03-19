"""Tests for on-site check-in, door checks, and product redemption."""

import json
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from django_program.conference.models import Conference
from django_program.registration.attendee import Attendee
from django_program.registration.checkin import CheckIn, DoorCheck, ProductRedemption
from django_program.registration.models import AddOn, Order, OrderLineItem, TicketType
from django_program.registration.services.checkin import CheckInService, RedemptionService

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


def _make_staff_user(**kwargs: object) -> object:
    """Create a staff user with the change_conference permission required by check-in API."""
    from django.contrib.auth.models import Permission

    defaults: dict[str, object] = {
        "username": f"staff-{uuid4().hex[:8]}",
        "email": f"{uuid4().hex[:8]}@test.com",
        "is_staff": True,
        "password": "testpass123",
    }
    defaults.update(kwargs)
    user = User.objects.create_user(**defaults)
    perm = Permission.objects.get(content_type__app_label="program_conference", codename="change_conference")
    user.user_permissions.add(perm)
    return user


def _make_order(*, conference: Conference, user: object, status: str = Order.Status.PAID) -> Order:
    return Order.objects.create(
        conference=conference,
        user=user,
        status=status,
        subtotal=Decimal("100.00"),
        total=Decimal("100.00"),
        reference=f"ORD-{uuid4().hex[:8].upper()}",
    )


def _make_ticket_type(*, conference: Conference, **kwargs: object) -> TicketType:
    defaults: dict[str, object] = {
        "name": "General Admission",
        "slug": f"general-{uuid4().hex[:6]}",
        "price": Decimal("100.00"),
        "is_active": True,
    }
    defaults.update(kwargs)
    return TicketType.objects.create(conference=conference, **defaults)


def _make_addon(*, conference: Conference, **kwargs: object) -> AddOn:
    defaults: dict[str, object] = {
        "name": "Workshop",
        "slug": f"workshop-{uuid4().hex[:6]}",
        "price": Decimal("50.00"),
        "is_active": True,
    }
    defaults.update(kwargs)
    return AddOn.objects.create(conference=conference, **defaults)


def _make_line_item(
    *,
    order: Order,
    ticket_type: TicketType | None = None,
    addon: AddOn | None = None,
    quantity: int = 1,
    description: str = "",
) -> OrderLineItem:
    unit_price = Decimal("100.00")
    if ticket_type:
        unit_price = ticket_type.price
        description = description or str(ticket_type.name)
    elif addon:
        unit_price = addon.price
        description = description or str(addon.name)
    else:
        description = description or "Line Item"
    return OrderLineItem.objects.create(
        order=order,
        description=description,
        quantity=quantity,
        unit_price=unit_price,
        line_total=unit_price * quantity,
        ticket_type=ticket_type,
        addon=addon,
    )


def _make_attendee(*, conference: Conference, user: object, order: Order | None = None) -> Attendee:
    return Attendee.objects.create(user=user, conference=conference, order=order)


# -- Model Tests --------------------------------------------------------------


@pytest.mark.unit
class TestCheckInModel:
    """Tests for the CheckIn model."""

    def test_checkin_creation(self) -> None:
        conf = _make_conference()
        user = _make_user()
        attendee = _make_attendee(conference=conf, user=user)
        checkin = CheckIn.objects.create(attendee=attendee, conference=conf)

        assert checkin.pk is not None
        assert checkin.attendee == attendee
        assert checkin.conference == conf
        assert checkin.checked_in_at is not None
        assert checkin.checked_in_by is None
        assert checkin.station == ""
        assert checkin.note == ""

    def test_checkin_str(self) -> None:
        conf = _make_conference()
        user = _make_user()
        attendee = _make_attendee(conference=conf, user=user)
        checkin = CheckIn.objects.create(attendee=attendee, conference=conf)

        result = str(checkin)
        assert "CheckIn:" in result
        assert str(attendee) in result


@pytest.mark.unit
class TestDoorCheckModel:
    """Tests for the DoorCheck model."""

    def test_doorcheck_creation(self) -> None:
        conf = _make_conference()
        user = _make_user()
        attendee = _make_attendee(conference=conf, user=user)
        ticket_type = _make_ticket_type(conference=conf)
        door_check = DoorCheck.objects.create(
            attendee=attendee,
            conference=conf,
            ticket_type=ticket_type,
        )

        assert door_check.pk is not None
        assert door_check.attendee == attendee
        assert door_check.ticket_type == ticket_type
        assert door_check.addon is None
        assert door_check.checked_at is not None

    def test_doorcheck_str(self) -> None:
        conf = _make_conference()
        user = _make_user()
        attendee = _make_attendee(conference=conf, user=user)
        ticket_type = _make_ticket_type(conference=conf)
        door_check = DoorCheck.objects.create(
            attendee=attendee,
            conference=conf,
            ticket_type=ticket_type,
        )

        result = str(door_check)
        assert "DoorCheck:" in result
        assert str(attendee) in result


@pytest.mark.unit
class TestProductRedemptionModel:
    """Tests for the ProductRedemption model."""

    def test_redemption_creation(self) -> None:
        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        attendee = _make_attendee(conference=conf, user=user, order=order)
        line_item = _make_line_item(order=order, description="Tutorial Access")

        redemption = ProductRedemption.objects.create(
            attendee=attendee,
            order_line_item=line_item,
            conference=conf,
        )

        assert redemption.pk is not None
        assert redemption.attendee == attendee
        assert redemption.order_line_item == line_item
        assert redemption.redeemed_at is not None
        assert redemption.redeemed_by is None

    def test_redemption_str(self) -> None:
        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        attendee = _make_attendee(conference=conf, user=user, order=order)
        line_item = _make_line_item(order=order, description="Tutorial")

        redemption = ProductRedemption.objects.create(
            attendee=attendee,
            order_line_item=line_item,
            conference=conf,
        )

        result = str(redemption)
        assert "Redemption:" in result

    def test_allows_multiple_redemptions_up_to_quantity(self) -> None:
        """Multiple redemptions of the same line item are allowed (no DB constraint)."""
        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        attendee = Attendee.objects.create(user=user, conference=conf, order=order)
        line_item = OrderLineItem.objects.create(
            order=order,
            description="Workshop",
            quantity=2,
            unit_price=Decimal("50.00"),
            line_total=Decimal("100.00"),
        )
        ProductRedemption.objects.create(
            attendee=attendee,
            order_line_item=line_item,
            conference=conf,
        )
        ProductRedemption.objects.create(
            attendee=attendee,
            order_line_item=line_item,
            conference=conf,
        )
        assert ProductRedemption.objects.filter(attendee=attendee, order_line_item=line_item).count() == 2


# -- Service Tests: CheckInService --------------------------------------------


@pytest.mark.unit
class TestCheckInServiceLookup:
    """Tests for CheckInService.lookup_attendee."""

    def test_lookup_returns_attendee_for_valid_code(self) -> None:
        conf = _make_conference()
        user = _make_user()
        attendee = _make_attendee(conference=conf, user=user)

        result = CheckInService.lookup_attendee(
            conference=conf,
            access_code=attendee.access_code,
        )
        assert result.pk == attendee.pk

    def test_lookup_raises_does_not_exist_for_invalid_code(self) -> None:
        conf = _make_conference()

        with pytest.raises(Attendee.DoesNotExist):
            CheckInService.lookup_attendee(conference=conf, access_code="ZZZZZZZZ")


@pytest.mark.unit
class TestCheckInServiceCheckIn:
    """Tests for CheckInService.check_in."""

    def test_check_in_creates_record(self) -> None:
        conf = _make_conference()
        user = _make_user()
        attendee = _make_attendee(conference=conf, user=user)

        checkin = CheckInService.check_in(attendee=attendee, station="Door A")

        assert checkin.pk is not None
        assert checkin.attendee == attendee
        assert checkin.conference == conf
        assert checkin.station == "Door A"

    def test_check_in_sets_checked_in_at_on_first(self) -> None:
        conf = _make_conference()
        user = _make_user()
        attendee = _make_attendee(conference=conf, user=user)

        assert attendee.checked_in_at is None

        CheckInService.check_in(attendee=attendee)

        attendee.refresh_from_db()
        assert attendee.checked_in_at is not None

    def test_check_in_allows_multiple_reentry(self) -> None:
        conf = _make_conference()
        user = _make_user()
        attendee = _make_attendee(conference=conf, user=user)

        ci1 = CheckInService.check_in(attendee=attendee, station="Door A")
        ci2 = CheckInService.check_in(attendee=attendee, station="Door B")

        assert ci1.pk != ci2.pk
        assert CheckIn.objects.filter(attendee=attendee).count() == 2

    def test_check_in_does_not_overwrite_checked_in_at_on_reentry(self) -> None:
        conf = _make_conference()
        user = _make_user()
        attendee = _make_attendee(conference=conf, user=user)

        CheckInService.check_in(attendee=attendee)
        attendee.refresh_from_db()
        first_check_in_at = attendee.checked_in_at

        CheckInService.check_in(attendee=attendee)
        attendee.refresh_from_db()

        assert attendee.checked_in_at == first_check_in_at

    def test_check_in_records_staff_user(self) -> None:
        conf = _make_conference()
        user = _make_user()
        staff = _make_staff_user()
        attendee = _make_attendee(conference=conf, user=user)

        checkin = CheckInService.check_in(attendee=attendee, checked_in_by=staff)

        assert checkin.checked_in_by == staff


@pytest.mark.unit
class TestCheckInServiceBadgeData:
    """Tests for CheckInService.get_badge_data."""

    def test_badge_data_returns_correct_structure(self) -> None:
        conf = _make_conference()
        user = _make_user(first_name="Jane", last_name="Doe")
        order = _make_order(conference=conf, user=user)
        ticket_type = _make_ticket_type(conference=conf, name="Professional")
        addon = _make_addon(conference=conf, name="Tutorial Pass")
        _make_line_item(order=order, ticket_type=ticket_type)
        _make_line_item(order=order, addon=addon)
        attendee = _make_attendee(conference=conf, user=user, order=order)

        CheckInService.check_in(attendee=attendee)
        attendee.refresh_from_db()

        badge = CheckInService.get_badge_data(attendee)

        assert badge["name"] == "Jane Doe"
        assert badge["email"] == str(user.email)
        assert badge["access_code"] == str(attendee.access_code)
        assert badge["ticket_type"] == "Professional"
        assert badge["checked_in"] is True
        assert badge["first_check_in_at"] is not None
        assert badge["check_in_count"] == 1
        assert isinstance(badge["products"], list)
        assert len(badge["products"]) == 1  # only addons appear in products list

    def test_badge_data_unchecked_attendee(self) -> None:
        conf = _make_conference()
        user = _make_user()
        attendee = _make_attendee(conference=conf, user=user)

        badge = CheckInService.get_badge_data(attendee)

        assert badge["checked_in"] is False
        assert badge["first_check_in_at"] is None
        assert badge["check_in_count"] == 0


@pytest.mark.unit
class TestCheckInServiceDoorCheck:
    """Tests for CheckInService.record_door_check."""

    def test_door_check_with_ticket_type(self) -> None:
        conf = _make_conference()
        user = _make_user()
        attendee = _make_attendee(conference=conf, user=user)
        ticket_type = _make_ticket_type(conference=conf)

        dc = CheckInService.record_door_check(
            attendee=attendee,
            ticket_type=ticket_type,
            station="Tutorial Room 1",
        )

        assert dc.pk is not None
        assert dc.ticket_type == ticket_type
        assert dc.addon is None
        assert dc.station == "Tutorial Room 1"

    def test_door_check_with_addon(self) -> None:
        conf = _make_conference()
        user = _make_user()
        attendee = _make_attendee(conference=conf, user=user)
        addon = _make_addon(conference=conf)

        dc = CheckInService.record_door_check(attendee=attendee, addon=addon)

        assert dc.pk is not None
        assert dc.addon == addon
        assert dc.ticket_type is None

    def test_door_check_raises_if_neither_provided(self) -> None:
        conf = _make_conference()
        user = _make_user()
        attendee = _make_attendee(conference=conf, user=user)

        with pytest.raises(ValueError, match="Exactly one"):
            CheckInService.record_door_check(attendee=attendee)

    def test_door_check_raises_if_both_provided(self) -> None:
        conf = _make_conference()
        user = _make_user()
        attendee = _make_attendee(conference=conf, user=user)
        ticket_type = _make_ticket_type(conference=conf)
        addon = _make_addon(conference=conf)

        with pytest.raises(ValueError, match="Exactly one"):
            CheckInService.record_door_check(
                attendee=attendee,
                ticket_type=ticket_type,
                addon=addon,
            )


# -- Service Tests: RedemptionService -----------------------------------------


@pytest.mark.unit
class TestRedemptionServiceGetRedeemable:
    """Tests for RedemptionService.get_redeemable_products."""

    def test_returns_items_with_remaining(self) -> None:
        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        attendee = _make_attendee(conference=conf, user=user, order=order)
        addon = _make_addon(conference=conf)
        _make_line_item(order=order, addon=addon, quantity=2)

        products = RedemptionService.get_redeemable_products(attendee)

        assert len(products) == 1
        assert products[0]["quantity"] == 2
        assert products[0]["redeemed_count"] == 0
        assert products[0]["remaining"] == 2

    def test_returns_empty_for_no_order(self) -> None:
        conf = _make_conference()
        user = _make_user()
        attendee = _make_attendee(conference=conf, user=user, order=None)

        products = RedemptionService.get_redeemable_products(attendee)

        assert products == []

    def test_excludes_fully_redeemed_items(self) -> None:
        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        attendee = _make_attendee(conference=conf, user=user, order=order)
        line_item = _make_line_item(order=order, quantity=1, description="Single Use")

        ProductRedemption.objects.create(
            attendee=attendee,
            order_line_item=line_item,
            conference=conf,
        )

        products = RedemptionService.get_redeemable_products(attendee)

        assert len(products) == 0


@pytest.mark.unit
class TestRedemptionServiceRedeem:
    """Tests for RedemptionService.redeem_product."""

    def test_redeem_creates_redemption(self) -> None:
        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        attendee = _make_attendee(conference=conf, user=user, order=order)
        line_item = _make_line_item(order=order, quantity=1)

        redemption = RedemptionService.redeem_product(
            attendee=attendee,
            order_line_item=line_item,
        )

        assert redemption.pk is not None
        assert redemption.attendee == attendee
        assert redemption.order_line_item == line_item
        assert redemption.conference == conf

    def test_redeem_raises_for_wrong_order(self) -> None:
        conf = _make_conference()
        user1 = _make_user()
        user2 = _make_user()
        order1 = _make_order(conference=conf, user=user1)
        order2 = _make_order(conference=conf, user=user2)
        attendee = _make_attendee(conference=conf, user=user1, order=order1)
        other_line_item = _make_line_item(order=order2, description="Other Order Item")

        with pytest.raises(ValueError, match="does not belong"):
            RedemptionService.redeem_product(
                attendee=attendee,
                order_line_item=other_line_item,
            )

    def test_redeem_raises_when_fully_redeemed(self) -> None:
        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        attendee = _make_attendee(conference=conf, user=user, order=order)
        line_item = _make_line_item(order=order, quantity=1, description="One-Time Pass")

        RedemptionService.redeem_product(
            attendee=attendee,
            order_line_item=line_item,
        )

        with pytest.raises(ValueError, match="fully redeemed"):
            RedemptionService.redeem_product(
                attendee=attendee,
                order_line_item=line_item,
            )


# -- View / API Tests ---------------------------------------------------------


@pytest.mark.integration
class TestScanView:
    """Tests for the ScanView check-in endpoint."""

    def _url(self, conference: Conference) -> str:
        return reverse("registration:checkin-scan", args=[conference.slug])

    def test_returns_401_for_anonymous(self) -> None:
        conf = _make_conference()
        client = Client()
        response = client.post(
            self._url(conf),
            data=json.dumps({"access_code": "XXXXXXXX"}),
            content_type="application/json",
        )
        assert response.status_code == 401

    def test_returns_403_for_non_staff(self) -> None:
        conf = _make_conference()
        user = _make_user(password="testpass123")
        client = Client()
        client.force_login(user)
        response = client.post(
            self._url(conf),
            data=json.dumps({"access_code": "XXXXXXXX"}),
            content_type="application/json",
        )
        assert response.status_code == 403

    def test_checks_in_attendee_successfully(self) -> None:
        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        attendee = _make_attendee(conference=conf, user=user, order=order)
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"access_code": attendee.access_code, "station": "Door A"}),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "checked_in"
        assert data["attendee"]["access_code"] == attendee.access_code
        assert data["checkin_id"] is not None

    def test_returns_404_for_unknown_access_code(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"access_code": "NOTFOUND"}),
            content_type="application/json",
        )

        assert response.status_code == 404
        assert "not found" in response.json()["error"].lower()


@pytest.mark.integration
class TestLookupView:
    """Tests for the LookupView endpoint."""

    def _url(self, conference: Conference, access_code: str) -> str:
        return reverse("registration:checkin-lookup", args=[conference.slug, access_code])

    def test_returns_attendee_data(self) -> None:
        conf = _make_conference()
        user = _make_user(first_name="Alice", last_name="Smith")
        order = _make_order(conference=conf, user=user)
        attendee = _make_attendee(conference=conf, user=user, order=order)
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.get(self._url(conf, attendee.access_code))

        assert response.status_code == 200
        data = response.json()
        assert data["attendee"]["access_code"] == attendee.access_code
        assert "products" in data
        assert "redeemable" in data

    def test_returns_404_for_unknown_code(self) -> None:
        conf = _make_conference()
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.get(self._url(conf, "NOTFOUND"))

        assert response.status_code == 404


@pytest.mark.integration
class TestRedeemView:
    """Tests for the RedeemView endpoint."""

    def _url(self, conference: Conference) -> str:
        return reverse("registration:checkin-redeem", args=[conference.slug])

    def test_redeems_product_successfully(self) -> None:
        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        attendee = _make_attendee(conference=conf, user=user, order=order)
        line_item = _make_line_item(order=order, quantity=1, description="Tutorial")
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps(
                {
                    "access_code": attendee.access_code,
                    "line_item_id": line_item.pk,
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "redeemed"
        assert data["redemption_id"] is not None

    def test_returns_409_for_already_redeemed(self) -> None:
        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        attendee = _make_attendee(conference=conf, user=user, order=order)
        line_item = _make_line_item(order=order, quantity=1, description="One-Time")
        staff = _make_staff_user()

        # Redeem once via the service directly
        RedemptionService.redeem_product(attendee=attendee, order_line_item=line_item)

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps(
                {
                    "access_code": attendee.access_code,
                    "line_item_id": line_item.pk,
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 409
        assert response.json()["error"] == "Product already fully redeemed"


@pytest.mark.integration
class TestOfflinePreloadView:
    """Tests for the OfflinePreloadView endpoint."""

    def _url(self, conference: Conference) -> str:
        return reverse("registration:checkin-preload", args=[conference.slug])

    def test_returns_attendee_list(self) -> None:
        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user, status=Order.Status.PAID)
        _make_attendee(conference=conf, user=user, order=order)
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.get(self._url(conf))

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert len(data["attendees"]) == 1
        assert data["conference"] == str(conf.slug)

    def test_filters_by_ticket_type(self) -> None:
        conf = _make_conference()
        ticket_a = _make_ticket_type(conference=conf, name="VIP", slug="vip")
        ticket_b = _make_ticket_type(conference=conf, name="Standard", slug="standard")

        # Attendee with VIP ticket
        user1 = _make_user()
        order1 = _make_order(conference=conf, user=user1)
        _make_line_item(order=order1, ticket_type=ticket_a)
        _make_attendee(conference=conf, user=user1, order=order1)

        # Attendee with Standard ticket
        user2 = _make_user()
        order2 = _make_order(conference=conf, user=user2)
        _make_line_item(order=order2, ticket_type=ticket_b)
        _make_attendee(conference=conf, user=user2, order=order2)

        staff = _make_staff_user()
        client = Client()
        client.force_login(staff)

        response = client.get(self._url(conf), {"ticket_type": "vip"})

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["attendees"][0]["ticket_type"] == "VIP"
