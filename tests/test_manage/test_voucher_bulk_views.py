"""Tests for voucher bulk generation views."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.db import IntegrityError
from django.test import Client
from django.urls import reverse

from django_program.conference.models import Conference
from django_program.registration.models import AddOn, TicketType, Voucher

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(username="admin", password="password", email="admin@test.com")


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(username="regular", password="password", email="regular@test.com")


@pytest.fixture
def conference(db):
    return Conference.objects.create(
        name="BulkCon",
        slug="bulkcon",
        start_date=date(2027, 5, 1),
        end_date=date(2027, 5, 3),
        timezone="UTC",
        is_active=True,
    )


@pytest.fixture
def ticket_type(conference):
    return TicketType.objects.create(
        conference=conference,
        name="General",
        slug="general",
        price=Decimal("100.00"),
    )


@pytest.fixture
def addon(conference):
    return AddOn.objects.create(
        conference=conference,
        name="T-Shirt",
        slug="tshirt",
        price=Decimal("25.00"),
    )


@pytest.fixture
def client_logged_in_super(superuser):
    c = Client()
    c.login(username="admin", password="password")
    return c


@pytest.fixture
def client_logged_in_regular(regular_user):
    c = Client()
    c.login(username="regular", password="password")
    return c


@pytest.fixture
def bulk_url(conference):
    return reverse("manage:voucher-bulk-generate", kwargs={"conference_slug": conference.slug})


# ---------------------------------------------------------------------------
# GET tests
# ---------------------------------------------------------------------------


class TestVoucherBulkGenerateViewGet:
    """Tests for the GET request on the bulk generate view."""

    def test_renders_form(self, client_logged_in_super, bulk_url):
        resp = client_logged_in_super.get(bulk_url)
        assert resp.status_code == 200
        assert "form" in resp.context

    def test_active_nav_is_vouchers(self, client_logged_in_super, bulk_url):
        resp = client_logged_in_super.get(bulk_url)
        assert resp.context["active_nav"] == "vouchers"

    def test_form_has_expected_fields(self, client_logged_in_super, bulk_url):
        resp = client_logged_in_super.get(bulk_url)
        form = resp.context["form"]
        expected = {
            "prefix",
            "count",
            "voucher_type",
            "discount_value",
            "applicable_ticket_types",
            "applicable_addons",
            "max_uses",
            "valid_from",
            "valid_until",
            "unlocks_hidden_tickets",
        }
        assert set(form.fields.keys()) == expected

    def test_form_querysets_scoped_to_conference(self, client_logged_in_super, bulk_url, ticket_type, addon):
        resp = client_logged_in_super.get(bulk_url)
        form = resp.context["form"]
        assert ticket_type in form.fields["applicable_ticket_types"].queryset
        assert addon in form.fields["applicable_addons"].queryset

    def test_anonymous_user_redirected(self, client, bulk_url):
        resp = client.get(bulk_url)
        assert resp.status_code == 302
        assert "/accounts/login/" in resp.url or "login" in resp.url

    def test_non_superuser_denied(self, client_logged_in_regular, bulk_url):
        resp = client_logged_in_regular.get(bulk_url)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST tests
# ---------------------------------------------------------------------------


class TestVoucherBulkGenerateViewPost:
    """Tests for the POST request on the bulk generate view."""

    def test_creates_vouchers_and_redirects(self, client_logged_in_super, bulk_url, conference):
        resp = client_logged_in_super.post(
            bulk_url,
            {
                "prefix": "SPEAKER-",
                "count": 3,
                "voucher_type": "comp",
                "discount_value": "0.00",
                "max_uses": 1,
            },
        )
        assert resp.status_code == 302
        vouchers = Voucher.objects.filter(conference=conference)
        assert vouchers.count() == 3
        for v in vouchers:
            assert v.code.startswith("SPEAKER-")

    def test_redirects_to_voucher_list(self, client_logged_in_super, bulk_url, conference):
        resp = client_logged_in_super.post(
            bulk_url,
            {
                "prefix": "REDIR-",
                "count": 1,
                "voucher_type": "comp",
                "discount_value": "0.00",
                "max_uses": 1,
            },
        )
        expected_url = reverse("manage:voucher-list", kwargs={"conference_slug": conference.slug})
        assert resp.status_code == 302
        assert resp.url == expected_url

    def test_success_message_on_creation(self, client_logged_in_super, bulk_url):
        resp = client_logged_in_super.post(
            bulk_url,
            {
                "prefix": "MSG-",
                "count": 2,
                "voucher_type": "comp",
                "discount_value": "0.00",
                "max_uses": 1,
            },
            follow=True,
        )
        messages_list = list(resp.context["messages"])
        assert len(messages_list) == 1
        assert "Successfully generated 2 voucher codes" in str(messages_list[0])

    def test_invalid_form_missing_required_field(self, client_logged_in_super, bulk_url):
        resp = client_logged_in_super.post(
            bulk_url,
            {
                "prefix": "BAD-",
                "voucher_type": "comp",
                "discount_value": "0.00",
                "max_uses": 1,
            },
        )
        assert resp.status_code == 200
        form = resp.context["form"]
        assert form.errors
        assert "count" in form.errors

    def test_invalid_form_count_zero(self, client_logged_in_super, bulk_url):
        resp = client_logged_in_super.post(
            bulk_url,
            {
                "prefix": "ZERO-",
                "count": 0,
                "voucher_type": "comp",
                "discount_value": "0.00",
                "max_uses": 1,
            },
        )
        assert resp.status_code == 200
        form = resp.context["form"]
        assert "count" in form.errors

    def test_invalid_form_count_over_500(self, client_logged_in_super, bulk_url):
        resp = client_logged_in_super.post(
            bulk_url,
            {
                "prefix": "OVER-",
                "count": 501,
                "voucher_type": "comp",
                "discount_value": "0.00",
                "max_uses": 1,
            },
        )
        assert resp.status_code == 200
        form = resp.context["form"]
        assert "count" in form.errors

    def test_post_with_ticket_types(self, client_logged_in_super, bulk_url, conference, ticket_type):
        resp = client_logged_in_super.post(
            bulk_url,
            {
                "prefix": "TT-",
                "count": 2,
                "voucher_type": "percentage",
                "discount_value": "25.00",
                "max_uses": 1,
                "applicable_ticket_types": [ticket_type.pk],
            },
        )
        assert resp.status_code == 302
        for v in Voucher.objects.filter(conference=conference):
            assert ticket_type in v.applicable_ticket_types.all()

    def test_post_with_addons(self, client_logged_in_super, bulk_url, conference, addon):
        resp = client_logged_in_super.post(
            bulk_url,
            {
                "prefix": "AO-",
                "count": 2,
                "voucher_type": "fixed_amount",
                "discount_value": "10.00",
                "max_uses": 1,
                "applicable_addons": [addon.pk],
            },
        )
        assert resp.status_code == 302
        for v in Voucher.objects.filter(conference=conference):
            assert addon in v.applicable_addons.all()

    def test_runtime_error_shows_error_message(self, client_logged_in_super, bulk_url):
        with patch(
            "django_program.manage.views_vouchers.generate_voucher_codes",
            side_effect=RuntimeError("code generation failed"),
        ):
            resp = client_logged_in_super.post(
                bulk_url,
                {
                    "prefix": "ERR-",
                    "count": 1,
                    "voucher_type": "comp",
                    "discount_value": "0.00",
                    "max_uses": 1,
                },
                follow=True,
            )
            messages_list = list(resp.context["messages"])
            assert len(messages_list) == 1
            assert "Failed to generate voucher codes" in str(messages_list[0])

    def test_integrity_error_shows_error_message(self, client_logged_in_super, bulk_url):
        with patch(
            "django_program.manage.views_vouchers.generate_voucher_codes",
            side_effect=IntegrityError("duplicate key"),
        ):
            resp = client_logged_in_super.post(
                bulk_url,
                {
                    "prefix": "DUP-",
                    "count": 1,
                    "voucher_type": "comp",
                    "discount_value": "0.00",
                    "max_uses": 1,
                },
                follow=True,
            )
            messages_list = list(resp.context["messages"])
            assert len(messages_list) == 1
            assert "Failed to generate voucher codes" in str(messages_list[0])

    def test_post_with_unlocks_hidden_tickets(self, client_logged_in_super, bulk_url, conference):
        resp = client_logged_in_super.post(
            bulk_url,
            {
                "prefix": "HIDDEN-",
                "count": 1,
                "voucher_type": "comp",
                "discount_value": "0.00",
                "max_uses": 1,
                "unlocks_hidden_tickets": True,
            },
        )
        assert resp.status_code == 302
        v = Voucher.objects.get(conference=conference)
        assert v.unlocks_hidden_tickets is True
