"""Coverage backfill tests for:

- ``services/checkin.py`` (order-status validation and door-check guards)
- ``views_checkin.py`` (JSON API edge cases: malformed bodies, missing
  ticket types, 409/404 branches, redemption counts in preload export)
- ``views.py`` (the attendee-facing visa letter download view, and the
  rare IntegrityError race in letter request creation)
- ``admin.py`` (purchase order inline permission guards and display methods)
"""

import json
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.http import HttpRequest
from django.test import Client, RequestFactory
from django.urls import reverse

from django_program.conference.models import Conference
from django_program.registration.admin import (
    PurchaseOrderAdmin,
    PurchaseOrderCreditNoteInline,
    PurchaseOrderPaymentInline,
)
from django_program.registration.attendee import Attendee
from django_program.registration.letter import LetterRequest
from django_program.registration.models import AddOn, Order, OrderLineItem, TicketType
from django_program.registration.purchase_order import PurchaseOrder
from django_program.registration.services.checkin import CheckInService
from django_program.registration.services.purchase_orders import create_purchase_order

User = get_user_model()

pytestmark = pytest.mark.django_db


# -- Helpers ------------------------------------------------------------------


def _make_conference(**kwargs: object) -> Conference:
    defaults: dict[str, object] = {
        "name": "TestCon",
        "slug": f"testcon-ca-{uuid4().hex[:6]}",
        "start_date": date(2026, 7, 1),
        "end_date": date(2026, 7, 5),
    }
    defaults.update(kwargs)
    return Conference.objects.create(**defaults)


def _make_user(**kwargs: object) -> object:
    defaults: dict[str, object] = {
        "username": f"user-ca-{uuid4().hex[:8]}",
        "email": f"{uuid4().hex[:8]}@test.com",
    }
    defaults.update(kwargs)
    return User.objects.create_user(**defaults)


def _make_staff_user(**kwargs: object) -> object:
    from django.contrib.auth.models import Permission

    defaults: dict[str, object] = {
        "username": f"staff-ca-{uuid4().hex[:8]}",
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
        reference=f"ORD-CA-{uuid4().hex[:8].upper()}",
    )


def _make_ticket_type(*, conference: Conference, **kwargs: object) -> TicketType:
    defaults: dict[str, object] = {
        "name": "General Admission",
        "slug": f"general-ca-{uuid4().hex[:6]}",
        "price": Decimal("100.00"),
        "is_active": True,
    }
    defaults.update(kwargs)
    return TicketType.objects.create(conference=conference, **defaults)


def _make_addon(*, conference: Conference, **kwargs: object) -> AddOn:
    defaults: dict[str, object] = {
        "name": "Workshop",
        "slug": f"workshop-ca-{uuid4().hex[:6]}",
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


# =============================================================================
# CheckInService.validate_order_status
# =============================================================================


@pytest.mark.unit
class TestValidateOrderStatus:
    def test_returns_message_when_attendee_has_no_order(self):
        conf = _make_conference()
        user = _make_user()
        attendee = _make_attendee(conference=conf, user=user, order=None)

        result = CheckInService.validate_order_status(attendee)

        assert result == "Attendee has no associated order."

    def test_returns_message_when_order_status_invalid(self):
        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user, status=Order.Status.PENDING)
        attendee = _make_attendee(conference=conf, user=user, order=order)

        result = CheckInService.validate_order_status(attendee)

        assert result is not None
        assert "check-in not allowed" in result


# =============================================================================
# CheckInService.record_door_check — conference mismatch guards
# =============================================================================


@pytest.mark.unit
class TestRecordDoorCheckConferenceMismatch:
    def test_raises_when_ticket_type_belongs_to_other_conference(self):
        conf = _make_conference()
        other_conf = _make_conference()
        user = _make_user()
        attendee = _make_attendee(conference=conf, user=user)
        foreign_ticket_type = _make_ticket_type(conference=other_conf)

        with pytest.raises(ValueError, match="does not belong to the attendee's conference"):
            CheckInService.record_door_check(
                attendee=attendee,
                ticket_type=foreign_ticket_type,
                addon=None,
                station="Door A",
            )

    def test_raises_when_addon_belongs_to_other_conference(self):
        conf = _make_conference()
        other_conf = _make_conference()
        user = _make_user()
        attendee = _make_attendee(conference=conf, user=user)
        foreign_addon = _make_addon(conference=other_conf)

        with pytest.raises(ValueError, match="does not belong to the attendee's conference"):
            CheckInService.record_door_check(
                attendee=attendee,
                ticket_type=None,
                addon=foreign_addon,
                station="Door A",
            )


# =============================================================================
# views_checkin._get_ticket_type_name / _parse_json_body (unit-level)
# =============================================================================


@pytest.mark.unit
class TestTicketTypeNameHelper:
    def test_returns_empty_string_for_none_order(self):
        from django_program.registration.views_checkin import _get_ticket_type_name

        assert _get_ticket_type_name(None) == ""

    def test_returns_ticket_type_name_from_line_items(self):
        from django_program.registration.views_checkin import _get_ticket_type_name

        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        ticket_type = _make_ticket_type(conference=conf, name="VIP Pass")
        _make_line_item(order=order, ticket_type=ticket_type)

        assert _get_ticket_type_name(order) == "VIP Pass"


@pytest.mark.unit
class TestParseJsonBody:
    def test_returns_none_for_invalid_json(self):
        from django_program.registration.views_checkin import _parse_json_body

        request = HttpRequest()
        request._body = b"not valid json {"
        assert _parse_json_body(request) is None

    def test_returns_none_for_non_dict_payload(self):
        from django_program.registration.views_checkin import _parse_json_body

        request = HttpRequest()
        request._body = b"[1, 2, 3]"
        assert _parse_json_body(request) is None


# =============================================================================
# ScanView edge cases
# =============================================================================


@pytest.mark.integration
class TestScanViewEdgeCases:
    def _url(self, conference: Conference) -> str:
        return reverse("registration:checkin-scan", args=[conference.slug])

    def test_invalid_json_body_returns_400(self):
        conf = _make_conference()
        staff = _make_staff_user()
        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data="not json",
            content_type="application/json",
        )
        assert response.status_code == 400
        assert response.json()["error"] == "Invalid JSON body"

    def test_missing_access_code_returns_400(self):
        conf = _make_conference()
        staff = _make_staff_user()
        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert response.json()["error"] == "access_code is required"

    def test_order_status_error_returns_409(self):
        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user, status=Order.Status.PENDING)
        attendee = _make_attendee(conference=conf, user=user, order=order)
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"access_code": attendee.access_code}),
            content_type="application/json",
        )

        assert response.status_code == 409
        data = response.json()
        assert "check-in not allowed" in data["error"]
        assert data["order_status"] == Order.Status.PENDING

    def test_returns_ticket_type_name_in_badge(self):
        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        ticket_type = _make_ticket_type(conference=conf, name="Corporate")
        _make_line_item(order=order, ticket_type=ticket_type)
        attendee = _make_attendee(conference=conf, user=user, order=order)
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"access_code": attendee.access_code}),
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json()["badge"]["ticket_type"] == "Corporate"


# =============================================================================
# LookupView — redeemed counts
# =============================================================================


@pytest.mark.integration
class TestLookupViewRedeemedCounts:
    def _url(self, conference: Conference, access_code: str) -> str:
        return reverse("registration:checkin-lookup", args=[conference.slug, access_code])

    def test_reflects_redeemed_count_for_addon_line_item(self):
        from django_program.registration.services.checkin import RedemptionService

        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        addon = _make_addon(conference=conf)
        line_item = _make_line_item(order=order, addon=addon, quantity=2)
        attendee = _make_attendee(conference=conf, user=user, order=order)
        staff = _make_staff_user()

        RedemptionService.redeem_product(attendee=attendee, order_line_item=line_item)

        client = Client()
        client.force_login(staff)
        response = client.get(self._url(conf, attendee.access_code))

        assert response.status_code == 200
        data = response.json()
        assert len(data["redeemable"]) == 1
        assert data["redeemable"][0]["redeemed_count"] == 1
        assert data["redeemable"][0]["remaining"] == 1


# =============================================================================
# RedeemView edge cases
# =============================================================================


@pytest.mark.integration
class TestRedeemViewEdgeCases:
    def _url(self, conference: Conference) -> str:
        return reverse("registration:checkin-redeem", args=[conference.slug])

    def test_invalid_json_body_returns_400(self):
        conf = _make_conference()
        staff = _make_staff_user()
        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data="not json",
            content_type="application/json",
        )
        assert response.status_code == 400
        assert response.json()["error"] == "Invalid JSON body"

    def test_non_integer_line_item_id_returns_400(self):
        conf = _make_conference()
        staff = _make_staff_user()
        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"access_code": "SOMECODE", "line_item_id": "not-a-number"}),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "valid integer line_item_id" in response.json()["error"]

    def test_missing_access_code_returns_400(self):
        conf = _make_conference()
        staff = _make_staff_user()
        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"access_code": "", "line_item_id": 1}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_unknown_access_code_returns_404(self):
        conf = _make_conference()
        staff = _make_staff_user()
        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"access_code": "NOTFOUND", "line_item_id": 1}),
            content_type="application/json",
        )
        assert response.status_code == 404
        assert "not found" in response.json()["error"].lower()

    def test_order_status_error_returns_409(self):
        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user, status=Order.Status.PENDING)
        attendee = _make_attendee(conference=conf, user=user, order=order)
        line_item = _make_line_item(order=order, quantity=1)
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"access_code": attendee.access_code, "line_item_id": line_item.pk}),
            content_type="application/json",
        )

        assert response.status_code == 409

    def test_unknown_line_item_returns_400(self):
        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        attendee = _make_attendee(conference=conf, user=user, order=order)
        staff = _make_staff_user()

        client = Client()
        client.force_login(staff)
        response = client.post(
            self._url(conf),
            data=json.dumps({"access_code": attendee.access_code, "line_item_id": 999999}),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert response.json()["error"] == "Line item not found in attendee's order"


# =============================================================================
# OfflinePreloadView — redeemed counts in preload export
# =============================================================================


@pytest.mark.integration
class TestOfflinePreloadViewRedeemedCounts:
    def _url(self, conference: Conference) -> str:
        return reverse("registration:checkin-preload", args=[conference.slug])

    def test_includes_redeemed_counts_for_prior_redemptions(self):
        from django_program.registration.services.checkin import RedemptionService

        conf = _make_conference()
        user = _make_user()
        order = _make_order(conference=conf, user=user)
        addon = _make_addon(conference=conf)
        line_item = _make_line_item(order=order, addon=addon, quantity=3)
        attendee = _make_attendee(conference=conf, user=user, order=order)
        staff = _make_staff_user()

        RedemptionService.redeem_product(attendee=attendee, order_line_item=line_item)

        client = Client()
        client.force_login(staff)
        response = client.get(self._url(conf))

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        product = data["attendees"][0]["products"][0]
        assert product["redeemed_count"] == 1
        assert product["remaining"] == 2


# =============================================================================
# LetterRequestCreateView — IntegrityError race
# =============================================================================


def _mock_feature_enabled(feature: object, conference: object = None) -> bool:
    return True


@pytest.mark.integration
class TestLetterRequestCreateIntegrityRace:
    def _url(self, conference: Conference) -> str:
        return reverse("registration:letter-request", kwargs={"conference_slug": conference.slug})

    @patch("django_program.features.is_feature_enabled", side_effect=_mock_feature_enabled)
    def test_integrity_error_on_save_redirects_to_detail(self, mock_feature):
        conf = _make_conference()
        user = _make_user(password="testpass123")
        LetterRequest.objects.create(
            conference=conf,
            user=user,
            passport_name="Existing Holder",
            passport_number="X0000000",
            nationality="Testlandia",
            travel_from=date(2027, 5, 1),
            travel_until=date(2027, 5, 10),
            destination_address="123 Test St",
        )

        client = Client()
        client.force_login(user)

        # Simulate a race: the pre-check "existing" lookup misses, but the
        # real unique_together constraint still rejects the duplicate save.
        with patch("django_program.registration.views.LetterRequest.objects.filter") as mock_filter:
            mock_filter.return_value.first.return_value = None
            response = client.post(
                self._url(conf),
                {
                    "passport_name": "Existing Holder",
                    "passport_number": "X0000000",
                    "nationality": "Testlandia",
                    "travel_from": "2027-05-01",
                    "travel_until": "2027-05-10",
                    "destination_address": "123 Test St",
                },
            )

        assert response.status_code == 302
        detail_url = reverse("registration:letter-request-detail", args=[conf.slug])
        assert response.url == detail_url


# =============================================================================
# LetterRequestDownloadView (attendee-facing self-download)
# =============================================================================


@pytest.mark.integration
class TestLetterRequestDownloadView:
    def _url(self, conference: Conference) -> str:
        return reverse("registration:letter-request-download", kwargs={"conference_slug": conference.slug})

    @patch("django_program.features.is_feature_enabled", side_effect=_mock_feature_enabled)
    def test_downloads_generated_pdf(self, mock_feature):
        conf = _make_conference()
        user = _make_user(password="testpass123")
        letter_request = LetterRequest.objects.create(
            conference=conf,
            user=user,
            passport_name="Jane Doe",
            passport_number="AB1234567",
            nationality="Testlandia",
            travel_from=date(2027, 5, 1),
            travel_until=date(2027, 5, 10),
            destination_address="123 Test St",
            status=LetterRequest.Status.GENERATED,
        )
        letter_request.generated_pdf.save("invite.pdf", ContentFile(b"%PDF-fake-contents"), save=True)

        client = Client()
        client.force_login(user)
        response = client.get(self._url(conf))

        assert response.status_code == 200
        assert response["Content-Type"] == "application/pdf"
        assert response.content == b"%PDF-fake-contents"
        assert "invitation-letter.pdf" in response["Content-Disposition"]

    @patch("django_program.features.is_feature_enabled", side_effect=_mock_feature_enabled)
    def test_returns_404_when_no_pdf_generated(self, mock_feature):
        conf = _make_conference()
        user = _make_user(password="testpass123")
        LetterRequest.objects.create(
            conference=conf,
            user=user,
            passport_name="Jane Doe",
            passport_number="AB1234567",
            nationality="Testlandia",
            travel_from=date(2027, 5, 1),
            travel_until=date(2027, 5, 10),
            destination_address="123 Test St",
        )

        client = Client()
        client.force_login(user)
        response = client.get(self._url(conf))

        assert response.status_code == 404

    @patch("django_program.features.is_feature_enabled", side_effect=_mock_feature_enabled)
    def test_returns_404_when_no_letter_request_exists(self, mock_feature):
        conf = _make_conference()
        user = _make_user(password="testpass123")

        client = Client()
        client.force_login(user)
        response = client.get(self._url(conf))

        assert response.status_code == 404


# =============================================================================
# PurchaseOrder admin — inline permission guards and display methods
# =============================================================================


@pytest.fixture
def po_conference():
    return Conference.objects.create(
        name="AdminPOCon",
        slug="admin-po-con",
        start_date=date(2027, 6, 1),
        end_date=date(2027, 6, 3),
        timezone="UTC",
    )


@pytest.fixture
def po_staff_user():
    return User.objects.create_user(
        username="adminpostaff",
        email="adminpostaff@example.com",
        password="testpass123",
        is_staff=True,
    )


@pytest.fixture
def admin_purchase_order(po_conference, po_staff_user):
    return create_purchase_order(
        conference=po_conference,
        organization_name="Admin Corp",
        contact_email="billing@admincorp.example",
        contact_name="Admin Contact",
        line_items=[{"description": "Ticket", "quantity": 1, "unit_price": Decimal("200.00")}],
        created_by=po_staff_user,
    )


@pytest.mark.unit
class TestPurchaseOrderInlinePermissions:
    def test_payment_inline_has_add_permission_false(self):
        inline = PurchaseOrderPaymentInline(PurchaseOrder, admin_site=MagicMock())
        request = RequestFactory().get("/")
        assert inline.has_add_permission(request) is False

    def test_payment_inline_has_delete_permission_false(self):
        inline = PurchaseOrderPaymentInline(PurchaseOrder, admin_site=MagicMock())
        request = RequestFactory().get("/")
        assert inline.has_delete_permission(request) is False

    def test_credit_note_inline_has_add_permission_false(self):
        inline = PurchaseOrderCreditNoteInline(PurchaseOrder, admin_site=MagicMock())
        request = RequestFactory().get("/")
        assert inline.has_add_permission(request) is False

    def test_credit_note_inline_has_delete_permission_false(self):
        inline = PurchaseOrderCreditNoteInline(PurchaseOrder, admin_site=MagicMock())
        request = RequestFactory().get("/")
        assert inline.has_delete_permission(request) is False


@pytest.mark.integration
class TestPurchaseOrderAdminQuerysetAndDisplays:
    def test_get_queryset_annotates_totals(self, admin_purchase_order):
        admin_instance = PurchaseOrderAdmin(PurchaseOrder, admin_site=MagicMock())
        request = RequestFactory().get("/")
        qs = admin_instance.get_queryset(request)
        po = qs.get(pk=admin_purchase_order.pk)

        assert po._annotated_total_paid == Decimal("0.00")
        assert po._annotated_total_credited == Decimal("0.00")

    def test_balance_due_display_renders_string(self, admin_purchase_order):
        admin_instance = PurchaseOrderAdmin(PurchaseOrder, admin_site=MagicMock())
        result = admin_instance.balance_due_display(admin_purchase_order)
        assert result == str(admin_purchase_order.balance_due)

    def test_total_paid_display_renders_string(self, admin_purchase_order):
        admin_instance = PurchaseOrderAdmin(PurchaseOrder, admin_site=MagicMock())
        result = admin_instance.total_paid_display(admin_purchase_order)
        assert result == str(admin_purchase_order.total_paid)
