"""Coverage-focused tests for django_program.sponsors.views portal flows."""

import csv
import io
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from django_program.conference.models import Conference
from django_program.registration.models import TicketType, Voucher
from django_program.sponsors.models import BulkPurchase, BulkPurchaseVoucher, Sponsor, SponsorLevel

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conference() -> Conference:
    return Conference.objects.create(
        name="PortalCon",
        slug="portalcon",
        start_date=date(2027, 8, 1),
        end_date=date(2027, 8, 3),
        timezone="UTC",
    )


@pytest.fixture
def level(conference: Conference) -> SponsorLevel:
    return SponsorLevel.objects.create(
        conference=conference,
        name="Gold",
        cost=Decimal("5000.00"),
    )


@pytest.fixture
def sponsor(conference: Conference, level: SponsorLevel) -> Sponsor:
    return Sponsor.objects.create(
        conference=conference,
        level=level,
        name="PortalCo",
        is_active=True,
        contact_email="contact@portalco.test",
    )


@pytest.fixture
def ticket_type(conference: Conference) -> TicketType:
    return TicketType.objects.create(
        conference=conference,
        name="Regular",
        slug="regular",
        price=Decimal("349.00"),
        bulk_enabled=True,
    )


@pytest.fixture
def sponsor_user(sponsor: Sponsor) -> object:
    return User.objects.create_user(
        username="sponsorcontact",
        email="contact@portalco.test",
        password="testpass123",
    )


@pytest.fixture
def staff_user() -> object:
    return User.objects.create_user(
        username="staffer",
        email="staffer@example.com",
        password="testpass123",
        is_staff=True,
    )


@pytest.fixture
def unrelated_user() -> object:
    return User.objects.create_user(
        username="nobody",
        email="nobody@example.com",
        password="testpass123",
    )


@pytest.fixture
def no_email_user() -> object:
    return User.objects.create_user(
        username="noemail",
        email="",
        password="testpass123",
    )


def login(client: Client, user) -> None:
    client.force_login(user)


# ---------------------------------------------------------------------------
# SponsorPortalMixin.dispatch (lines 144-149)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDispatch:
    def test_anonymous_redirects_to_login(self, client: Client, conference: Conference):
        response = client.get(f"/{conference.slug}/sponsors/portal/")
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_authenticated_owner_reaches_view(self, client: Client, conference: Conference, sponsor_user, sponsor):
        login(client, sponsor_user)
        response = client.get(f"/{conference.slug}/sponsors/portal/")
        assert response.status_code == 200
        assert response.context["sponsor"] == sponsor
        assert response.context["conference"] == conference


# ---------------------------------------------------------------------------
# _resolve_sponsor (lines 161-179)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestResolveSponsor:
    def test_staff_without_active_sponsor_denied(self, client: Client, conference: Conference, staff_user):
        login(client, staff_user)
        response = client.get(f"/{conference.slug}/sponsors/portal/")
        assert response.status_code == 403

    def test_staff_gets_first_active_sponsor(self, client: Client, conference: Conference, staff_user, sponsor):
        login(client, staff_user)
        response = client.get(f"/{conference.slug}/sponsors/portal/")
        assert response.status_code == 200
        assert response.context["sponsor"] == sponsor

    def test_user_without_email_denied(self, client: Client, conference: Conference, no_email_user, sponsor):
        login(client, no_email_user)
        response = client.get(f"/{conference.slug}/sponsors/portal/")
        assert response.status_code == 403

    def test_matching_email_grants_access(self, client: Client, conference: Conference, sponsor_user, sponsor):
        login(client, sponsor_user)
        response = client.get(f"/{conference.slug}/sponsors/portal/")
        assert response.status_code == 200
        assert response.context["sponsor"] == sponsor

    def test_unrelated_user_denied(self, client: Client, conference: Conference, unrelated_user, sponsor):
        login(client, unrelated_user)
        response = client.get(f"/{conference.slug}/sponsors/portal/")
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# SponsorPortalMixin.get_context_data (lines 190-193) + SponsorPortalView (211-215)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_portal_home_lists_purchases(client: Client, conference: Conference, sponsor_user, sponsor, ticket_type):
    bp = BulkPurchase.objects.create(
        conference=conference,
        sponsor=sponsor,
        ticket_type=ticket_type,
        quantity=5,
        unit_price=Decimal("10.00"),
        total_amount=Decimal("50.00"),
        product_description="5x Regular voucher codes",
    )
    login(client, sponsor_user)
    response = client.get(f"/{conference.slug}/sponsors/portal/")
    assert response.status_code == 200
    assert bp in response.context["purchases"]
    assert response.context["conference"] == conference
    assert response.context["sponsor"] == sponsor


# ---------------------------------------------------------------------------
# BulkPurchaseDetailView.get_context_data (lines 233-252)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_purchase_detail_view_context(client: Client, conference: Conference, sponsor_user, sponsor, ticket_type):
    bp = BulkPurchase.objects.create(
        conference=conference,
        sponsor=sponsor,
        ticket_type=ticket_type,
        quantity=2,
        unit_price=Decimal("10.00"),
        total_amount=Decimal("20.00"),
    )
    voucher1 = Voucher.objects.create(conference=conference, code="DET1", voucher_type="comp", max_uses=2, times_used=1)
    voucher2 = Voucher.objects.create(conference=conference, code="DET2", voucher_type="comp", max_uses=3, times_used=0)
    BulkPurchaseVoucher.objects.create(bulk_purchase=bp, voucher=voucher1)
    BulkPurchaseVoucher.objects.create(bulk_purchase=bp, voucher=voucher2)

    login(client, sponsor_user)
    response = client.get(f"/{conference.slug}/sponsors/portal/purchases/{bp.pk}/")

    assert response.status_code == 200
    assert response.context["purchase"] == bp
    assert len(response.context["voucher_links"]) == 2
    assert response.context["total_uses"] == 1
    assert response.context["total_max"] == 5


@pytest.mark.django_db
def test_purchase_detail_view_404_for_other_sponsor(
    client: Client, conference: Conference, sponsor_user, sponsor, level: SponsorLevel
):
    other_sponsor = Sponsor.objects.create(conference=conference, level=level, name="Other Sponsor", is_active=True)
    other_bp = BulkPurchase.objects.create(
        conference=conference,
        sponsor=other_sponsor,
        quantity=1,
        unit_price=Decimal("5.00"),
        total_amount=Decimal("5.00"),
    )

    login(client, sponsor_user)
    response = client.get(f"/{conference.slug}/sponsors/portal/purchases/{other_bp.pk}/")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# BulkPurchaseExportCSVView.get (lines 269-299)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_export_csv_contains_voucher_rows(client: Client, conference: Conference, sponsor_user, sponsor):
    bp = BulkPurchase.objects.create(
        conference=conference,
        sponsor=sponsor,
        quantity=1,
        unit_price=Decimal("10.00"),
        total_amount=Decimal("10.00"),
    )
    voucher = Voucher.objects.create(
        conference=conference,
        code="CSVCODE1",
        voucher_type="comp",
        max_uses=1,
        times_used=0,
        is_active=True,
    )
    BulkPurchaseVoucher.objects.create(bulk_purchase=bp, voucher=voucher)

    login(client, sponsor_user)
    response = client.get(f"/{conference.slug}/sponsors/portal/purchases/{bp.pk}/export/")

    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"
    assert f"vouchers-purchase-{bp.pk}.csv" in response["Content-Disposition"]

    content = response.content.decode()
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    assert rows[0] == ["code", "times_used", "max_uses", "is_active", "valid_from", "valid_until"]
    assert rows[1][0] == "CSVCODE1"
    assert rows[1][1] == "0"
    assert rows[1][2] == "1"
    assert rows[1][3] == "True"
    assert rows[1][4] == ""
    assert rows[1][5] == ""


@pytest.mark.django_db
def test_export_csv_404_for_other_sponsor(
    client: Client, conference: Conference, sponsor_user, sponsor, level: SponsorLevel
):
    other_sponsor = Sponsor.objects.create(conference=conference, level=level, name="Other Sponsor", is_active=True)
    other_bp = BulkPurchase.objects.create(
        conference=conference,
        sponsor=other_sponsor,
        quantity=1,
        unit_price=Decimal("5.00"),
        total_amount=Decimal("5.00"),
    )

    login(client, sponsor_user)
    response = client.get(f"/{conference.slug}/sponsors/portal/purchases/{other_bp.pk}/export/")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# BulkPurchaseRequestView.form_valid (lines 320-343)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_request_view_creates_pending_purchase_and_redirects(
    client: Client, conference: Conference, sponsor_user, sponsor
):
    login(client, sponsor_user)
    response = client.post(
        f"/{conference.slug}/sponsors/portal/purchases/request/",
        data={
            "quantity": 7,
            "ticket_type_preference": "Corporate",
            "notes": "Need these for our booth staff.",
        },
    )

    assert response.status_code == 302
    assert response.url == f"/{conference.slug}/sponsors/portal/"

    bp = BulkPurchase.objects.get(sponsor=sponsor, quantity=7)
    assert bp.payment_status == BulkPurchase.PaymentStatus.PENDING
    assert bp.product_description == "Corporate"
    assert bp.unit_price == Decimal("0.00")
    assert bp.total_amount == Decimal("0.00")
    assert bp.voucher_config == {
        "notes": "Need these for our booth staff.",
        "ticket_type_preference": "Corporate",
    }
    assert bp.requested_by == sponsor_user
