"""Tests for the admin reports dashboard and report views."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker

from django_program.conference.models import Conference
from django_program.pretalx.models import Speaker
from django_program.registration.conditions import TimeOrStockLimitCondition
from django_program.registration.models import (
    AddOn,
    Attendee,
    Credit,
    Order,
    OrderLineItem,
    Payment,
    TicketType,
    Voucher,
)

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
def reports_user(db):
    """A user belonging to the 'Program: Reports' group."""
    user = User.objects.create_user(username="reporter", password="password", email="reporter@test.com")
    group, _created = Group.objects.get_or_create(name="Program: Reports")
    user.groups.add(group)
    return user


@pytest.fixture
def conference(db):
    return Conference.objects.create(
        name="Test Conf",
        slug="test-conf",
        start_date=date(2027, 5, 1),
        end_date=date(2027, 5, 3),
        timezone="UTC",
        is_active=True,
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
def client_logged_in_reports(reports_user):
    c = Client()
    c.login(username="reporter", password="password")
    return c


@pytest.fixture
def ticket_general(conference):
    return TicketType.objects.create(
        conference=conference,
        name="General",
        slug="general",
        price=Decimal("100.00"),
        total_quantity=200,
        order=0,
    )


@pytest.fixture
def ticket_vip(conference):
    return TicketType.objects.create(
        conference=conference,
        name="VIP",
        slug="vip",
        price=Decimal("200.00"),
        total_quantity=50,
        order=1,
    )


@pytest.fixture
def addon_tutorial(conference):
    return AddOn.objects.create(
        conference=conference,
        name="Tutorial",
        slug="tutorial",
        price=Decimal("50.00"),
        total_quantity=100,
        order=0,
    )


@pytest.fixture
def users(db):
    """Three regular users for order/attendee data."""
    return [
        User.objects.create_user(username=f"user{i}", password="password", email=f"user{i}@test.com") for i in range(3)
    ]


@pytest.fixture
def voucher_used(conference):
    return Voucher.objects.create(
        conference=conference,
        code="USED10",
        voucher_type=Voucher.VoucherType.PERCENTAGE,
        discount_value=Decimal("10.00"),
        max_uses=5,
        times_used=3,
        is_active=True,
    )


@pytest.fixture
def voucher_unused(conference):
    return Voucher.objects.create(
        conference=conference,
        code="FRESH20",
        voucher_type=Voucher.VoucherType.FIXED_AMOUNT,
        discount_value=Decimal("20.00"),
        max_uses=10,
        times_used=0,
        is_active=True,
    )


@pytest.fixture
def paid_order(conference, users, ticket_general, addon_tutorial):
    """A paid order with line items for user0."""
    order = Order.objects.create(
        conference=conference,
        user=users[0],
        status=Order.Status.PAID,
        subtotal=Decimal("150.00"),
        total=Decimal("150.00"),
        voucher_code="USED10",
        discount_amount=Decimal("10.00"),
        reference="ORD-001",
    )
    OrderLineItem.objects.create(
        order=order,
        description="General",
        quantity=1,
        unit_price=Decimal("100.00"),
        line_total=Decimal("100.00"),
        ticket_type=ticket_general,
    )
    OrderLineItem.objects.create(
        order=order,
        description="Tutorial",
        quantity=1,
        unit_price=Decimal("50.00"),
        line_total=Decimal("50.00"),
        addon=addon_tutorial,
    )
    return order


@pytest.fixture
def pending_order(conference, users, ticket_vip):
    """A pending order with a valid hold for user1."""
    order = Order.objects.create(
        conference=conference,
        user=users[1],
        status=Order.Status.PENDING,
        subtotal=Decimal("200.00"),
        total=Decimal("200.00"),
        reference="ORD-002",
        hold_expires_at=timezone.now() + timedelta(hours=1),
    )
    OrderLineItem.objects.create(
        order=order,
        description="VIP",
        quantity=1,
        unit_price=Decimal("200.00"),
        line_total=Decimal("200.00"),
        ticket_type=ticket_vip,
    )
    return order


@pytest.fixture
def attendee_checked_in(conference, users, paid_order):
    """An attendee who has checked in."""
    return Attendee.objects.create(
        user=users[0],
        conference=conference,
        order=paid_order,
        checked_in_at=timezone.now(),
        completed_registration=True,
    )


@pytest.fixture
def attendee_not_checked_in(conference, users, pending_order):
    """An attendee who has not checked in."""
    return Attendee.objects.create(
        user=users[1],
        conference=conference,
        order=pending_order,
        checked_in_at=None,
        completed_registration=False,
    )


@pytest.fixture
def time_condition(conference):
    """A TimeOrStockLimitCondition for the conference."""
    return TimeOrStockLimitCondition.objects.create(
        conference=conference,
        name="Early Bird",
        is_active=True,
        priority=10,
        discount_type=TimeOrStockLimitCondition.DiscountType.PERCENTAGE,
        discount_value=Decimal("15.00"),
        limit=100,
        times_used=42,
        start_time=timezone.now() - timedelta(days=30),
        end_time=timezone.now() + timedelta(days=30),
    )


@pytest.fixture
def report_data(
    conference,
    ticket_general,
    ticket_vip,
    addon_tutorial,
    voucher_used,
    voucher_unused,
    paid_order,
    pending_order,
    attendee_checked_in,
    attendee_not_checked_in,
    time_condition,
):
    """Aggregate fixture that sets up the full report test dataset."""
    return {
        "conference": conference,
        "ticket_general": ticket_general,
        "ticket_vip": ticket_vip,
        "addon_tutorial": addon_tutorial,
        "voucher_used": voucher_used,
        "voucher_unused": voucher_unused,
        "paid_order": paid_order,
        "pending_order": pending_order,
        "attendee_checked_in": attendee_checked_in,
        "attendee_not_checked_in": attendee_not_checked_in,
        "time_condition": time_condition,
    }


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def _url(name: str, conference: Conference) -> str:
    return reverse(f"manage:{name}", kwargs={"conference_slug": conference.slug})


# ---------------------------------------------------------------------------
# Permission tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReportPermissions:
    """Access control for all report views."""

    VIEW_NAMES = [
        "reports-dashboard",
        "report-attendee-manifest",
        "report-attendee-export",
        "report-inventory",
        "report-inventory-export",
        "report-voucher-usage",
        "report-voucher-export",
        "report-discount-effectiveness",
        "report-discount-export",
    ]

    def test_anonymous_redirects_to_login(self, conference):
        c = Client()
        for name in self.VIEW_NAMES:
            resp = c.get(_url(name, conference))
            assert resp.status_code == 302, f"{name} should redirect anonymous users"
            assert "login" in resp.url

    def test_regular_user_gets_403(self, client_logged_in_regular, conference):
        for name in self.VIEW_NAMES:
            resp = client_logged_in_regular.get(_url(name, conference))
            assert resp.status_code == 403, f"{name} should deny non-staff users"

    def test_superuser_has_access(self, client_logged_in_super, conference):
        for name in self.VIEW_NAMES:
            resp = client_logged_in_super.get(_url(name, conference))
            assert resp.status_code == 200, f"{name} should allow superuser"

    def test_reports_group_has_access(self, client_logged_in_reports, conference):
        for name in self.VIEW_NAMES:
            resp = client_logged_in_reports.get(_url(name, conference))
            assert resp.status_code == 200, f"{name} should allow reports group"


# ---------------------------------------------------------------------------
# Reports Dashboard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReportsDashboard:
    """Reports dashboard landing page."""

    def test_loads_empty_conference(self, client_logged_in_super, conference):
        resp = client_logged_in_super.get(_url("reports-dashboard", conference))
        assert resp.status_code == 200
        ctx = resp.context
        assert ctx["conference"] == conference
        assert ctx["active_nav"] == "reports"

    def test_contains_attendee_summary(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("reports-dashboard", conference))
        summary = resp.context["attendee_summary"]
        assert summary["total"] == 2
        assert summary["checked_in"] == 1
        assert summary["completed"] == 1

    def test_contains_voucher_summary(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("reports-dashboard", conference))
        summary = resp.context["voucher_summary"]
        assert summary["total"] == 2
        assert summary["active"] == 2
        assert summary["used"] == 1

    def test_contains_ticket_inventory(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("reports-dashboard", conference))
        ticket_types = list(resp.context["ticket_types"])
        assert len(ticket_types) == 2

    def test_contains_discount_summary(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("reports-dashboard", conference))
        summary = resp.context["discount_summary"]
        assert summary["total"] >= 1
        assert summary["active"] >= 1


# ---------------------------------------------------------------------------
# Attendee Manifest
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAttendeeManifest:
    """Attendee manifest view with filtering and pagination."""

    def test_returns_attendee_list(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-attendee-manifest", conference))
        assert resp.status_code == 200
        attendees = list(resp.context["attendees"])
        assert len(attendees) == 2

    def test_filter_by_ticket_type(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        ticket = report_data["ticket_general"]
        url = _url("report-attendee-manifest", conference) + f"?ticket_type={ticket.pk}"
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200
        attendees = list(resp.context["attendees"])
        # Only the paid order has a General ticket line item
        assert len(attendees) == 1

    def test_filter_checked_in_yes(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        url = _url("report-attendee-manifest", conference) + "?checked_in=yes"
        resp = client_logged_in_super.get(url)
        attendees = list(resp.context["attendees"])
        assert len(attendees) == 1
        assert attendees[0].checked_in_at is not None

    def test_filter_checked_in_no(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        url = _url("report-attendee-manifest", conference) + "?checked_in=no"
        resp = client_logged_in_super.get(url)
        attendees = list(resp.context["attendees"])
        assert len(attendees) == 1
        assert attendees[0].checked_in_at is None

    def test_filter_completed_yes(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        url = _url("report-attendee-manifest", conference) + "?completed=yes"
        resp = client_logged_in_super.get(url)
        attendees = list(resp.context["attendees"])
        assert len(attendees) == 1

    def test_filter_completed_no(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        url = _url("report-attendee-manifest", conference) + "?completed=no"
        resp = client_logged_in_super.get(url)
        attendees = list(resp.context["attendees"])
        assert len(attendees) == 1

    def test_context_includes_ticket_types_for_filter(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-attendee-manifest", conference))
        ticket_types = list(resp.context["ticket_types"])
        assert len(ticket_types) == 2

    def test_context_preserves_filter_params(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        ticket = report_data["ticket_general"]
        url = _url("report-attendee-manifest", conference) + f"?ticket_type={ticket.pk}&checked_in=yes"
        resp = client_logged_in_super.get(url)
        assert resp.context["current_ticket_type"] == str(ticket.pk)
        assert resp.context["current_checked_in"] == "yes"


# ---------------------------------------------------------------------------
# Attendee Manifest CSV Export
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAttendeeManifestExport:
    """CSV export of the attendee manifest."""

    def test_csv_content_type(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-attendee-export", conference))
        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/csv"

    def test_csv_filename(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-attendee-export", conference))
        assert f"{conference.slug}-attendees.csv" in resp["Content-Disposition"]

    def test_csv_has_header_row(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-attendee-export", conference))
        content = resp.content.decode()
        lines = content.strip().split("\n")
        header = lines[0]
        assert "Username" in header
        assert "Email" in header
        assert "Ticket Type" in header
        assert "Check-in Time" in header
        assert "Access Code" in header

    def test_csv_contains_attendee_rows(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-attendee-export", conference))
        content = resp.content.decode()
        lines = content.strip().split("\n")
        # header + 2 attendees
        assert len(lines) == 3

    def test_csv_respects_filters(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        url = _url("report-attendee-export", conference) + "?checked_in=yes"
        resp = client_logged_in_super.get(url)
        content = resp.content.decode()
        lines = content.strip().split("\n")
        # header + 1 checked-in attendee
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# Inventory Report
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestInventoryReport:
    """Product inventory and stock status report."""

    def test_returns_200(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-inventory", conference))
        assert resp.status_code == 200

    def test_contains_ticket_types(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-inventory", conference))
        ticket_types = list(resp.context["ticket_types"])
        assert len(ticket_types) == 2

    def test_contains_addons(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-inventory", conference))
        addons = list(resp.context["addons"])
        assert len(addons) == 1

    def test_sold_count_from_paid_orders(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-inventory", conference))
        ticket_types = list(resp.context["ticket_types"])
        general = next(tt for tt in ticket_types if str(tt.name) == "General")
        assert general.sold_count == 1

    def test_reserved_count_from_pending_with_hold(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-inventory", conference))
        ticket_types = list(resp.context["ticket_types"])
        vip = next(tt for tt in ticket_types if str(tt.name) == "VIP")
        assert vip.reserved_count == 1


# ---------------------------------------------------------------------------
# Inventory Report CSV Export
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestInventoryReportExport:
    """CSV export of inventory data."""

    def test_csv_content_type(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-inventory-export", conference))
        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/csv"

    def test_csv_filename(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-inventory-export", conference))
        assert f"{conference.slug}-inventory.csv" in resp["Content-Disposition"]

    def test_csv_has_ticket_and_addon_rows(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-inventory-export", conference))
        content = resp.content.decode()
        lines = content.strip().split("\n")
        # header + 2 tickets + 1 addon = 4
        assert len(lines) == 4


# ---------------------------------------------------------------------------
# Voucher Usage Report
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestVoucherUsageReport:
    """Voucher usage and redemption rates report."""

    def test_returns_200(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-voucher-usage", conference))
        assert resp.status_code == 200

    def test_contains_voucher_list(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-voucher-usage", conference))
        vouchers = list(resp.context["vouchers"])
        assert len(vouchers) == 2

    def test_voucher_summary_stats(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-voucher-usage", conference))
        summary = resp.context["voucher_summary"]
        assert summary["total"] == 2
        assert summary["used"] == 1

    def test_revenue_impact_annotation(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-voucher-usage", conference))
        vouchers = list(resp.context["vouchers"])
        # USED10 voucher was applied to the paid_order with discount_amount=10
        used_voucher = next(v for v in vouchers if str(v.code) == "USED10")
        assert used_voucher.revenue_impact == Decimal("10.00")


# ---------------------------------------------------------------------------
# Voucher Usage CSV Export
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestVoucherUsageExport:
    """CSV export of voucher usage data."""

    def test_csv_content_type(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-voucher-export", conference))
        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/csv"

    def test_csv_filename(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-voucher-export", conference))
        assert f"{conference.slug}-vouchers.csv" in resp["Content-Disposition"]

    def test_csv_has_header_and_rows(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-voucher-export", conference))
        content = resp.content.decode()
        lines = content.strip().split("\n")
        # header + 2 vouchers
        assert len(lines) == 3

    def test_csv_header_fields(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-voucher-export", conference))
        content = resp.content.decode()
        header = content.split("\n")[0]
        assert "Code" in header
        assert "Redemption Rate" in header
        assert "Revenue Impact" in header


# ---------------------------------------------------------------------------
# Discount Effectiveness Report
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDiscountEffectivenessReport:
    """Discount conditions overview and effectiveness report."""

    def test_returns_200(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-discount-effectiveness", conference))
        assert resp.status_code == 200

    def test_conditions_grouped_by_type(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-discount-effectiveness", conference))
        conditions = resp.context["conditions_by_type"]
        assert "Time/Stock Limit" in conditions
        assert len(conditions["Time/Stock Limit"]) == 1

    def test_condition_data_fields(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-discount-effectiveness", conference))
        conditions = resp.context["conditions_by_type"]
        cond = conditions["Time/Stock Limit"][0]
        assert cond["name"] == "Early Bird"
        assert cond["is_active"] is True
        assert cond["priority"] == 10
        assert cond["times_used"] == 42
        assert cond["limit"] == 100

    def test_discount_summary(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-discount-effectiveness", conference))
        summary = resp.context["discount_summary"]
        assert summary["total"] >= 1
        assert summary["active"] >= 1


# ---------------------------------------------------------------------------
# Discount Effectiveness CSV Export
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDiscountEffectivenessExport:
    """CSV export of discount effectiveness data."""

    def test_csv_content_type(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-discount-export", conference))
        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/csv"

    def test_csv_filename(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-discount-export", conference))
        assert f"{conference.slug}-discounts.csv" in resp["Content-Disposition"]

    def test_csv_has_header_and_rows(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-discount-export", conference))
        content = resp.content.decode()
        lines = content.strip().split("\n")
        # header + 1 condition
        assert len(lines) == 2

    def test_csv_header_fields(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-discount-export", conference))
        content = resp.content.decode()
        header = content.split("\n")[0]
        assert "Name" in header
        assert "Type" in header
        assert "Discount Value" in header
        assert "Times Used" in header


# ---------------------------------------------------------------------------
# URL Resolution
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReportURLResolution:
    """URL patterns resolve correctly for all report views."""

    def test_dashboard_url(self):
        url = reverse("manage:reports-dashboard", kwargs={"conference_slug": "test-conf"})
        assert "/reports/" in url

    def test_attendee_manifest_url(self):
        url = reverse("manage:report-attendee-manifest", kwargs={"conference_slug": "test-conf"})
        assert "/reports/attendees/" in url

    def test_attendee_export_url(self):
        url = reverse("manage:report-attendee-export", kwargs={"conference_slug": "test-conf"})
        assert "/reports/attendees/export/" in url

    def test_inventory_url(self):
        url = reverse("manage:report-inventory", kwargs={"conference_slug": "test-conf"})
        assert "/reports/inventory/" in url

    def test_voucher_usage_url(self):
        url = reverse("manage:report-voucher-usage", kwargs={"conference_slug": "test-conf"})
        assert "/reports/vouchers/" in url

    def test_discount_effectiveness_url(self):
        url = reverse("manage:report-discount-effectiveness", kwargs={"conference_slug": "test-conf"})
        assert "/reports/discounts/" in url


# ---------------------------------------------------------------------------
# CSV injection safety
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCSVInjectionSafety:
    """Verify that _safe_csv_cell prevents formula injection in exports."""

    def test_attendee_export_escapes_formula_in_username(self, client_logged_in_super, conference):
        evil_user = User.objects.create_user(
            username="=CMD('calc')",
            password="password",
            email="evil@test.com",
        )
        Attendee.objects.create(
            user=evil_user,
            conference=conference,
            completed_registration=False,
        )
        resp = client_logged_in_super.get(_url("report-attendee-export", conference))
        content = resp.content.decode()
        # The leading '=' should be escaped with a preceding apostrophe
        assert "'=CMD" in content


# ---------------------------------------------------------------------------
# Sales by Date Report
# ---------------------------------------------------------------------------


@pytest.fixture
def sales_data(conference, users, ticket_general, paid_order):
    """Set up paid orders for sales-by-date testing.

    The ``paid_order`` fixture already creates a single paid order.
    This fixture just ensures the necessary objects are materialised.
    """
    return {"conference": conference, "paid_order": paid_order}


@pytest.mark.django_db
class TestSalesByDateReport:
    """Tests for the Sales by Date report."""

    def test_returns_200(self, client_logged_in_super, conference):
        client_logged_in_super.get(_url("report-sales-by-date", conference))
        resp = client_logged_in_super.get(_url("report-sales-by-date", conference))
        assert resp.status_code == 200

    def test_contains_sales_rows(self, client_logged_in_super, sales_data):
        conference = sales_data["conference"]
        resp = client_logged_in_super.get(_url("report-sales-by-date", conference))
        assert "sales_rows" in resp.context
        assert "total_orders" in resp.context
        assert "total_revenue" in resp.context

    def test_sales_rows_reflect_paid_orders(self, client_logged_in_super, sales_data):
        conference = sales_data["conference"]
        resp = client_logged_in_super.get(_url("report-sales-by-date", conference))
        assert resp.context["total_orders"] >= 1
        assert resp.context["total_revenue"] >= Decimal("0.01")

    def test_date_filtering(self, client_logged_in_super, sales_data):
        conference = sales_data["conference"]
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        url = _url("report-sales-by-date", conference) + f"?date_from={tomorrow}"
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200
        assert resp.context["total_orders"] == 0

    def test_date_until_filtering(self, client_logged_in_super, sales_data):
        conference = sales_data["conference"]
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        url = _url("report-sales-by-date", conference) + f"?date_until={yesterday}"
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200
        # Order created today should be excluded
        assert resp.context["total_orders"] == 0


@pytest.mark.django_db
class TestSalesByDateExport:
    """CSV export tests for the Sales by Date report."""

    def test_csv_content_type(self, client_logged_in_super, sales_data):
        conference = sales_data["conference"]
        resp = client_logged_in_super.get(_url("report-sales-export", conference))
        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/csv"

    def test_csv_header_fields(self, client_logged_in_super, sales_data):
        conference = sales_data["conference"]
        resp = client_logged_in_super.get(_url("report-sales-export", conference))
        content = resp.content.decode()
        header = content.split("\n")[0]
        assert "Date" in header
        assert "Orders" in header
        assert "Revenue" in header

    def test_csv_contains_data_rows(self, client_logged_in_super, sales_data):
        conference = sales_data["conference"]
        resp = client_logged_in_super.get(_url("report-sales-export", conference))
        content = resp.content.decode()
        lines = content.strip().split("\n")
        # header + at least 1 data row from the paid order
        assert len(lines) >= 2


# ---------------------------------------------------------------------------
# Credit Notes Report
# ---------------------------------------------------------------------------


@pytest.fixture
def credit_data(conference, users, paid_order):
    """Create credit records for credit note report testing."""
    credit = baker.make(
        Credit,
        conference=conference,
        user=users[0],
        amount=Decimal("25.00"),
        remaining_amount=Decimal("25.00"),
        status=Credit.Status.AVAILABLE,
        source_order=paid_order,
        note="Test refund credit",
    )
    return {"conference": conference, "credit": credit}


@pytest.mark.django_db
class TestCreditNotesReport:
    """Tests for the Credit Notes report."""

    def test_returns_200(self, client_logged_in_super, credit_data):
        conference = credit_data["conference"]
        resp = client_logged_in_super.get(_url("report-credit-notes", conference))
        assert resp.status_code == 200

    def test_contains_credits_in_context(self, client_logged_in_super, credit_data):
        conference = credit_data["conference"]
        resp = client_logged_in_super.get(_url("report-credit-notes", conference))
        credits = list(resp.context["credits"])
        assert len(credits) == 1
        assert credits[0].amount == Decimal("25.00")

    def test_contains_credit_summary(self, client_logged_in_super, credit_data):
        conference = credit_data["conference"]
        resp = client_logged_in_super.get(_url("report-credit-notes", conference))
        summary = resp.context["credit_summary"]
        assert summary["count"] == 1
        assert summary["total_issued"] == Decimal("25.00")

    def test_empty_conference_returns_200(self, client_logged_in_super, conference):
        resp = client_logged_in_super.get(_url("report-credit-notes", conference))
        assert resp.status_code == 200
        assert resp.context["credit_summary"]["count"] == 0


@pytest.mark.django_db
class TestCreditNotesExport:
    """CSV export tests for the Credit Notes report."""

    def test_csv_content_type(self, client_logged_in_super, credit_data):
        conference = credit_data["conference"]
        resp = client_logged_in_super.get(_url("report-credit-export", conference))
        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/csv"

    def test_csv_has_header_and_rows(self, client_logged_in_super, credit_data):
        conference = credit_data["conference"]
        resp = client_logged_in_super.get(_url("report-credit-export", conference))
        content = resp.content.decode()
        lines = content.strip().split("\n")
        # header + 1 credit
        assert len(lines) == 2

    def test_csv_header_fields(self, client_logged_in_super, credit_data):
        conference = credit_data["conference"]
        resp = client_logged_in_super.get(_url("report-credit-export", conference))
        content = resp.content.decode()
        header = content.split("\n")[0]
        assert "User" in header
        assert "Amount" in header
        assert "Status" in header


# ---------------------------------------------------------------------------
# Speaker Registration Report
# ---------------------------------------------------------------------------


@pytest.fixture
def speaker_data(conference, users):
    """Create speaker records for speaker registration report testing."""
    # Speaker with a linked user who has a paid order
    speaker_registered = baker.make(
        Speaker,
        conference=conference,
        name="Alice Speaker",
        email="alice@example.com",
        pretalx_code="ALICE1",
        user=users[0],
    )
    # Speaker with a linked user who does NOT have a paid order
    speaker_unregistered = baker.make(
        Speaker,
        conference=conference,
        name="Bob Speaker",
        email="bob@example.com",
        pretalx_code="BOB2",
        user=users[2],
    )
    return {
        "conference": conference,
        "speaker_registered": speaker_registered,
        "speaker_unregistered": speaker_unregistered,
    }


@pytest.mark.django_db
class TestSpeakerRegistrationReport:
    """Tests for the Speaker Registration report."""

    def test_returns_200(self, client_logged_in_super, speaker_data):
        conference = speaker_data["conference"]
        resp = client_logged_in_super.get(_url("report-speaker-registration", conference))
        assert resp.status_code == 200

    def test_contains_speakers_in_context(self, client_logged_in_super, speaker_data):
        conference = speaker_data["conference"]
        resp = client_logged_in_super.get(_url("report-speaker-registration", conference))
        speakers = list(resp.context["speakers"])
        assert len(speakers) == 2

    def test_speakers_annotated_with_has_paid_order(self, client_logged_in_super, speaker_data, paid_order):
        conference = speaker_data["conference"]
        resp = client_logged_in_super.get(_url("report-speaker-registration", conference))
        speakers = list(resp.context["speakers"])
        # users[0] has paid_order, so the speaker linked to users[0] should show as registered
        registered = next(s for s in speakers if str(s.name) == "Alice Speaker")
        unregistered = next(s for s in speakers if str(s.name) == "Bob Speaker")
        assert registered.has_paid_order is True
        assert unregistered.has_paid_order is False

    def test_speaker_counts(self, client_logged_in_super, speaker_data, paid_order):
        conference = speaker_data["conference"]
        resp = client_logged_in_super.get(_url("report-speaker-registration", conference))
        assert resp.context["total_speakers"] == 2
        assert resp.context["registered_count"] == 1
        assert resp.context["unregistered_count"] == 1


@pytest.mark.django_db
class TestSpeakerRegistrationExport:
    """CSV export tests for the Speaker Registration report."""

    def test_csv_content_type(self, client_logged_in_super, speaker_data):
        conference = speaker_data["conference"]
        resp = client_logged_in_super.get(_url("report-speaker-export", conference))
        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/csv"

    def test_csv_header_fields(self, client_logged_in_super, speaker_data):
        conference = speaker_data["conference"]
        resp = client_logged_in_super.get(_url("report-speaker-export", conference))
        content = resp.content.decode()
        header = content.split("\n")[0]
        assert "Name" in header
        assert "Email" in header
        assert "Registered" in header

    def test_csv_has_data_rows(self, client_logged_in_super, speaker_data):
        conference = speaker_data["conference"]
        resp = client_logged_in_super.get(_url("report-speaker-export", conference))
        content = resp.content.decode()
        lines = content.strip().split("\n")
        # header + 2 speakers
        assert len(lines) == 3


# ---------------------------------------------------------------------------
# Reconciliation Report
# ---------------------------------------------------------------------------


@pytest.fixture
def reconciliation_data(conference, users, ticket_general, paid_order):
    """Set up payment data for reconciliation report testing."""
    payment = baker.make(
        Payment,
        order=paid_order,
        method=Payment.Method.STRIPE,
        status=Payment.Status.SUCCEEDED,
        amount=Decimal("150.00"),
    )
    return {"conference": conference, "paid_order": paid_order, "payment": payment}


@pytest.mark.django_db
class TestReconciliationReport:
    """Tests for the Reconciliation report."""

    def test_returns_200(self, client_logged_in_super, reconciliation_data):
        conference = reconciliation_data["conference"]
        resp = client_logged_in_super.get(_url("report-reconciliation", conference))
        assert resp.status_code == 200

    def test_contains_recon_in_context(self, client_logged_in_super, reconciliation_data):
        conference = reconciliation_data["conference"]
        resp = client_logged_in_super.get(_url("report-reconciliation", conference))
        recon = resp.context["recon"]
        assert "sales_total" in recon
        assert "payments_total" in recon
        assert "refunds_total" in recon
        assert "credits_outstanding" in recon
        assert "discrepancy" in recon

    def test_sales_total_matches_paid_orders(self, client_logged_in_super, reconciliation_data):
        conference = reconciliation_data["conference"]
        resp = client_logged_in_super.get(_url("report-reconciliation", conference))
        recon = resp.context["recon"]
        assert recon["sales_total"] == Decimal("150.00")

    def test_payments_total_matches_succeeded(self, client_logged_in_super, reconciliation_data):
        conference = reconciliation_data["conference"]
        resp = client_logged_in_super.get(_url("report-reconciliation", conference))
        recon = resp.context["recon"]
        assert recon["payments_total"] == Decimal("150.00")

    def test_has_payment_method_breakdown(self, client_logged_in_super, reconciliation_data):
        conference = reconciliation_data["conference"]
        resp = client_logged_in_super.get(_url("report-reconciliation", conference))
        recon = resp.context["recon"]
        assert len(recon["by_payment_method"]) >= 1


@pytest.mark.django_db
class TestReconciliationExport:
    """CSV export tests for the Reconciliation report."""

    def test_csv_content_type(self, client_logged_in_super, reconciliation_data):
        conference = reconciliation_data["conference"]
        resp = client_logged_in_super.get(_url("report-reconciliation-export", conference))
        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/csv"

    def test_csv_contains_summary_rows(self, client_logged_in_super, reconciliation_data):
        conference = reconciliation_data["conference"]
        resp = client_logged_in_super.get(_url("report-reconciliation-export", conference))
        content = resp.content.decode()
        assert "Total Sales" in content
        assert "Total Payments" in content
        assert "Discrepancy" in content


# ---------------------------------------------------------------------------
# Registration Flow Report
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRegistrationFlowReport:
    """Tests for the Registration Flow report."""

    def test_returns_200(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-registration-flow", conference))
        assert resp.status_code == 200

    def test_contains_flow_rows(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-registration-flow", conference))
        assert "flow_rows" in resp.context
        assert "total_registrations" in resp.context
        assert "total_cancellations" in resp.context

    def test_registrations_counted(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-registration-flow", conference))
        # report_data creates 2 attendees
        assert resp.context["total_registrations"] == 2

    def test_date_filtering(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        url = _url("report-registration-flow", conference) + f"?date_from={tomorrow}"
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200
        assert resp.context["total_registrations"] == 0

    def test_date_until_filtering(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        url = _url("report-registration-flow", conference) + f"?date_until={yesterday}"
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200
        assert resp.context["total_registrations"] == 0


@pytest.mark.django_db
class TestRegistrationFlowExport:
    """CSV export tests for the Registration Flow report."""

    def test_csv_content_type(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-registration-flow-export", conference))
        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/csv"

    def test_csv_header_fields(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-registration-flow-export", conference))
        content = resp.content.decode()
        header = content.split("\n")[0]
        assert "Date" in header
        assert "Registrations" in header
        assert "Cancellations" in header
        assert "Net" in header

    def test_csv_has_data_rows(self, client_logged_in_super, report_data):
        conference = report_data["conference"]
        resp = client_logged_in_super.get(_url("report-registration-flow-export", conference))
        content = resp.content.decode()
        lines = content.strip().split("\n")
        # header + at least 1 row (attendees created today)
        assert len(lines) >= 2
