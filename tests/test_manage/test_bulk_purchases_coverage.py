"""Coverage tests for bulk purchase management views and form."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from django_program.conference.models import Conference
from django_program.manage.forms_bulk_purchases import BulkPurchaseCreateForm
from django_program.registration.models import AddOn, TicketType
from django_program.sponsors.models import BulkPurchase, BulkPurchaseVoucher, Sponsor, SponsorLevel

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(username="bpadmin", password="password", email="bpadmin@test.com")


@pytest.fixture
def conference(db):
    return Conference.objects.create(
        name="BP Test Conf",
        slug="bp-test-conf",
        start_date=date(2027, 5, 1),
        end_date=date(2027, 5, 3),
        timezone="UTC",
        is_active=True,
    )


@pytest.fixture
def level(conference):
    return SponsorLevel.objects.create(conference=conference, name="Gold", slug="gold", cost=Decimal("10000.00"))


@pytest.fixture
def sponsor(conference, level):
    return Sponsor.objects.create(conference=conference, level=level, name="Acme Corp", slug="acme")


@pytest.fixture
def ticket_type(conference):
    return TicketType.objects.create(
        conference=conference,
        name="General",
        slug="general",
        price=Decimal("100.00"),
        bulk_enabled=True,
    )


@pytest.fixture
def addon(conference):
    return AddOn.objects.create(
        conference=conference,
        name="T-Shirt",
        slug="tshirt",
        price=Decimal("25.00"),
        bulk_enabled=True,
    )


@pytest.fixture
def client_logged_in_super(superuser):
    c = Client()
    c.login(username="bpadmin", password="password")
    return c


def _list_url(conference):
    return reverse("manage:bulk-purchase-list", kwargs={"conference_slug": conference.slug})


def _detail_url(conference, pk):
    return reverse("manage:bulk-purchase-detail", kwargs={"conference_slug": conference.slug, "pk": pk})


def _add_url(conference):
    return reverse("manage:bulk-purchase-add", kwargs={"conference_slug": conference.slug})


def _approve_url(conference, pk):
    return reverse("manage:bulk-purchase-approve", kwargs={"conference_slug": conference.slug, "pk": pk})


def _fulfill_url(conference, pk):
    return reverse("manage:bulk-purchase-fulfill", kwargs={"conference_slug": conference.slug, "pk": pk})


def make_bp(conference, sponsor, **overrides) -> BulkPurchase:
    defaults: dict[str, object] = {
        "conference": conference,
        "sponsor": sponsor,
        "quantity": 5,
        "unit_price": Decimal("50.00"),
        "total_amount": Decimal("250.00"),
        "payment_status": BulkPurchase.PaymentStatus.PENDING,
        "voucher_config": {},
    }
    defaults.update(overrides)
    return BulkPurchase.objects.create(**defaults)


# ---------------------------------------------------------------------------
# BulkPurchaseListView
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBulkPurchaseListView:
    def test_list_context_has_nav_and_status_choices(self, client_logged_in_super, conference, sponsor):
        make_bp(conference, sponsor)
        resp = client_logged_in_super.get(_list_url(conference))
        assert resp.status_code == 200
        assert resp.context["active_nav"] == "bulk-purchases"
        assert resp.context["status_choices"] == BulkPurchase.PaymentStatus.choices
        assert resp.context["current_status"] == ""

    def test_list_filters_by_valid_status(self, client_logged_in_super, conference, sponsor):
        pending = make_bp(conference, sponsor, payment_status=BulkPurchase.PaymentStatus.PENDING)
        approved = make_bp(conference, sponsor, payment_status=BulkPurchase.PaymentStatus.APPROVED)
        resp = client_logged_in_super.get(_list_url(conference), {"status": "approved"})
        results = list(resp.context["bulk_purchases"])
        assert approved in results
        assert pending not in results
        assert resp.context["current_status"] == "approved"

    def test_list_ignores_invalid_status(self, client_logged_in_super, conference, sponsor):
        pending = make_bp(conference, sponsor, payment_status=BulkPurchase.PaymentStatus.PENDING)
        resp = client_logged_in_super.get(_list_url(conference), {"status": "not-a-real-status"})
        results = list(resp.context["bulk_purchases"])
        assert pending in results


# ---------------------------------------------------------------------------
# BulkPurchaseDetailView
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBulkPurchaseDetailView:
    def test_detail_shows_voucher_links_and_nav(self, client_logged_in_super, conference, sponsor):
        from django_program.registration.models import Voucher

        bp = make_bp(conference, sponsor)
        voucher = Voucher.objects.create(
            conference=conference,
            code="BULK-TEST-1",
            voucher_type=Voucher.VoucherType.COMP,
            discount_value=Decimal("0.00"),
            max_uses=1,
        )
        link = BulkPurchaseVoucher.objects.create(bulk_purchase=bp, voucher=voucher)

        resp = client_logged_in_super.get(_detail_url(conference, bp.pk))
        assert resp.status_code == 200
        assert resp.context["active_nav"] == "bulk-purchases"
        assert link in list(resp.context["voucher_links"])
        assert resp.context["purchase"] == bp


# ---------------------------------------------------------------------------
# BulkPurchaseCreateView
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBulkPurchaseCreateView:
    def test_get_create_form_context(self, client_logged_in_super, conference):
        resp = client_logged_in_super.get(_add_url(conference))
        assert resp.status_code == 200
        assert resp.context["active_nav"] == "bulk-purchases"
        assert resp.context["is_create"] is True

    def test_get_scopes_field_querysets_to_conference(
        self, client_logged_in_super, conference, sponsor, ticket_type, addon
    ):
        other_conf = Conference.objects.create(
            name="Other Conf",
            slug="other-conf",
            start_date=date(2027, 7, 1),
            end_date=date(2027, 7, 3),
            timezone="UTC",
            is_active=True,
        )
        other_level = SponsorLevel.objects.create(conference=other_conf, name="Silver", cost=Decimal("1000.00"))
        other_sponsor = Sponsor.objects.create(conference=other_conf, level=other_level, name="Other Corp")
        other_ticket_type = TicketType.objects.create(
            conference=other_conf,
            name="Other General",
            slug="other-general",
            price=Decimal("10.00"),
            bulk_enabled=True,
        )
        other_addon = AddOn.objects.create(
            conference=other_conf, name="Other Addon", slug="other-addon", price=Decimal("5.00"), bulk_enabled=True
        )

        resp = client_logged_in_super.get(_add_url(conference))
        form = resp.context["form"]
        sponsor_qs = list(form.fields["sponsor"].queryset)
        ticket_type_qs = list(form.fields["ticket_type"].queryset)
        addon_qs = list(form.fields["addon"].queryset)

        assert sponsor in sponsor_qs
        assert other_sponsor not in sponsor_qs
        assert ticket_type in ticket_type_qs
        assert other_ticket_type not in ticket_type_qs
        assert addon in addon_qs
        assert other_addon not in addon_qs

    def test_post_creates_bulk_purchase_and_redirects(self, client_logged_in_super, conference, sponsor, ticket_type):
        resp = client_logged_in_super.post(
            _add_url(conference),
            {
                "product_description": "Gold Sponsor Comp Tickets",
                "ticket_type": ticket_type.pk,
                "addon": "",
                "quantity": 10,
                "unit_price": "0.00",
                "sponsor": sponsor.pk,
                "voucher_type": "comp",
                "discount_value": "0",
                "max_uses_per_voucher": 1,
                "valid_from": "",
                "valid_until": "",
            },
        )
        assert resp.status_code == 302
        assert resp.url == reverse("manage:bulk-purchase-list", kwargs={"conference_slug": conference.slug})

        bp = BulkPurchase.objects.get(product_description="Gold Sponsor Comp Tickets")
        assert bp.conference == conference
        assert bp.requested_by is not None


# ---------------------------------------------------------------------------
# BulkPurchaseApproveView
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBulkPurchaseApproveView:
    def test_approve_pending_purchase_succeeds(self, client_logged_in_super, conference, sponsor):
        bp = make_bp(conference, sponsor, payment_status=BulkPurchase.PaymentStatus.PENDING)
        resp = client_logged_in_super.post(_approve_url(conference, bp.pk))
        assert resp.status_code == 302
        bp.refresh_from_db()
        assert bp.payment_status == BulkPurchase.PaymentStatus.APPROVED
        assert bp.approved_by is not None

    def test_approve_non_pending_purchase_errors(self, client_logged_in_super, conference, sponsor):
        bp = make_bp(conference, sponsor, payment_status=BulkPurchase.PaymentStatus.APPROVED)
        resp = client_logged_in_super.post(_approve_url(conference, bp.pk))
        assert resp.status_code == 302
        assert resp.url == _detail_url(conference, bp.pk)
        bp.refresh_from_db()
        assert bp.payment_status == BulkPurchase.PaymentStatus.APPROVED


# ---------------------------------------------------------------------------
# BulkPurchaseFulfillView
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBulkPurchaseFulfillView:
    def test_fulfill_wrong_status_errors(self, client_logged_in_super, conference, sponsor):
        bp = make_bp(conference, sponsor, payment_status=BulkPurchase.PaymentStatus.PENDING)
        resp = client_logged_in_super.post(_fulfill_url(conference, bp.pk))
        assert resp.status_code == 302
        assert resp.url == _detail_url(conference, bp.pk)
        bp.refresh_from_db()
        assert bp.payment_status == BulkPurchase.PaymentStatus.PENDING

    def test_fulfill_success_generates_vouchers(self, client_logged_in_super, conference, sponsor):
        bp = make_bp(
            conference,
            sponsor,
            quantity=3,
            unit_price=Decimal("0.00"),
            total_amount=Decimal("0.00"),
            payment_status=BulkPurchase.PaymentStatus.APPROVED,
            voucher_config={
                "voucher_type": "comp",
                "discount_value": "0",
                "max_uses": 1,
            },
        )
        resp = client_logged_in_super.post(_fulfill_url(conference, bp.pk))
        assert resp.status_code == 302
        assert resp.url == _detail_url(conference, bp.pk)
        bp.refresh_from_db()
        assert bp.payment_status == BulkPurchase.PaymentStatus.PAID
        assert bp.vouchers_generated == 3

    def test_fulfill_already_fulfilled_shows_warning(self, client_logged_in_super, conference, sponsor):
        bp = make_bp(
            conference,
            sponsor,
            quantity=0,
            payment_status=BulkPurchase.PaymentStatus.PAID,
            voucher_config={"voucher_type": "comp", "discount_value": "0"},
        )
        resp = client_logged_in_super.post(_fulfill_url(conference, bp.pk))
        assert resp.status_code == 302
        detail_resp = client_logged_in_super.get(resp.url)
        messages = [str(m) for m in detail_resp.context["messages"]]
        assert any("already been fulfilled" in m for m in messages)

    def test_fulfill_service_error_shows_message(self, client_logged_in_super, conference, sponsor):
        bp = make_bp(
            conference,
            sponsor,
            unit_price=Decimal("50.00"),
            total_amount=Decimal("250.00"),
            payment_status=BulkPurchase.PaymentStatus.APPROVED,
            voucher_config={},
        )
        resp = client_logged_in_super.post(_fulfill_url(conference, bp.pk))
        assert resp.status_code == 302
        detail_resp = client_logged_in_super.get(resp.url)
        messages = [str(m) for m in detail_resp.context["messages"]]
        assert any("payment must be completed first" in m for m in messages)

    def test_fulfill_unexpected_exception_shows_generic_error(self, client_logged_in_super, conference, sponsor):
        bp = make_bp(
            conference,
            sponsor,
            payment_status=BulkPurchase.PaymentStatus.APPROVED,
            unit_price=Decimal("0.00"),
            total_amount=Decimal("0.00"),
            voucher_config={"voucher_type": "comp", "discount_value": "0"},
        )
        with patch(
            "django_program.manage.views_bulk_purchases.BulkPurchaseService.fulfill_bulk_purchase",
            side_effect=RuntimeError("boom"),
        ):
            resp = client_logged_in_super.post(_fulfill_url(conference, bp.pk))
        assert resp.status_code == 302
        detail_resp = client_logged_in_super.get(resp.url)
        messages = [str(m) for m in detail_resp.context["messages"]]
        assert any("Voucher generation failed" in m for m in messages)


# ---------------------------------------------------------------------------
# BulkPurchaseCreateForm
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBulkPurchaseCreateForm:
    def _base_data(self, ticket_type, sponsor):
        return {
            "product_description": "Deal",
            "ticket_type": ticket_type.pk,
            "addon": "",
            "quantity": 5,
            "unit_price": "20.00",
            "sponsor": sponsor.pk,
            "voucher_type": "percentage",
            "discount_value": "15.00",
            "max_uses_per_voucher": 2,
            "valid_from": "",
            "valid_until": "",
        }

    def test_clean_quantity_over_limit_raises(self, ticket_type, sponsor):
        data = self._base_data(ticket_type, sponsor)
        data["quantity"] = 501
        form = BulkPurchaseCreateForm(data=data)
        assert not form.is_valid()
        assert "quantity" in form.errors
        assert "Cannot generate more than 500" in str(form.errors["quantity"])

    def test_clean_computes_total_amount(self, ticket_type, sponsor):
        data = self._base_data(ticket_type, sponsor)
        form = BulkPurchaseCreateForm(data=data)
        assert form.is_valid(), form.errors
        assert form.cleaned_data["total_amount"] == Decimal("100.00")

    def test_save_populates_voucher_config_and_total(self, conference, ticket_type, sponsor):
        data = self._base_data(ticket_type, sponsor)
        data["valid_from"] = "2027-01-01T00:00"
        data["valid_until"] = "2027-06-01T00:00"
        form = BulkPurchaseCreateForm(data=data)
        assert form.is_valid(), form.errors
        instance = form.save(commit=False)
        instance.conference = conference
        instance.save()

        assert instance.total_amount == Decimal("100.00")
        assert instance.voucher_config["voucher_type"] == "percentage"
        assert instance.voucher_config["discount_value"] == "15.00"
        assert instance.voucher_config["max_uses"] == 2
        assert instance.voucher_config["valid_from"] is not None
        assert instance.voucher_config["valid_until"] is not None

    def test_save_without_validity_window_stores_none(self, conference, ticket_type, sponsor):
        data = self._base_data(ticket_type, sponsor)
        form = BulkPurchaseCreateForm(data=data)
        assert form.is_valid(), form.errors
        instance = form.save(commit=False)
        instance.conference = conference
        instance.save()

        assert instance.voucher_config["valid_from"] is None
        assert instance.voucher_config["valid_until"] is None
