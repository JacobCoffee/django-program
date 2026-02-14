"""Tests for the financial overview dashboard view."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from django_program.conference.models import Conference
from django_program.registration.models import (
    Cart,
    Credit,
    Order,
    OrderLineItem,
    Payment,
    TicketType,
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


def _dashboard_url(conference: Conference) -> str:
    return reverse("manage:financial-dashboard", kwargs={"conference_slug": conference.slug})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFinancialDashboardPermissions:
    """Access control for the financial dashboard."""

    def test_unauthenticated_redirects_to_login(self, conference):
        c = Client()
        resp = c.get(_dashboard_url(conference))
        assert resp.status_code == 302
        assert "login" in resp.url

    def test_regular_user_gets_403(self, client_logged_in_regular, conference):
        resp = client_logged_in_regular.get(_dashboard_url(conference))
        assert resp.status_code == 403

    def test_superuser_has_access(self, client_logged_in_super, conference):
        resp = client_logged_in_super.get(_dashboard_url(conference))
        assert resp.status_code == 200


@pytest.mark.django_db
class TestFinancialDashboardEmptyConference:
    """Dashboard loads correctly when conference has no data."""

    def test_loads_with_no_data(self, client_logged_in_super, conference):
        resp = client_logged_in_super.get(_dashboard_url(conference))
        assert resp.status_code == 200

        ctx = resp.context
        revenue = ctx["revenue"]
        assert revenue["total"] == Decimal("0.00")
        assert revenue["refunded"] == Decimal("0.00")
        assert revenue["net"] == Decimal("0.00")
        assert revenue["credits_issued"] == Decimal("0.00")
        assert revenue["credits_outstanding"] == Decimal("0.00")
        assert revenue["credits_applied"] == Decimal("0.00")

        assert ctx["total_orders"] == 0
        assert all(v == 0 for v in ctx["orders_by_status"].values())

        assert ctx["carts_by_status"]["active"] == 0
        assert ctx["carts_by_status"]["expired"] == 0
        assert ctx["carts_by_status"]["checked_out"] == 0
        assert ctx["carts_by_status"]["abandoned"] == 0

        assert ctx["total_payments"] == 0
        assert all(v == 0 for v in ctx["payments_by_status"].values())

    def test_empty_payments_shows_empty_state(self, client_logged_in_super, conference):
        resp = client_logged_in_super.get(_dashboard_url(conference))
        content = resp.content.decode()
        assert "No payments recorded." in content


@pytest.mark.django_db
class TestFinancialDashboardRevenue:
    """Revenue calculations including refund via Credits."""

    def test_revenue_from_paid_orders(self, client_logged_in_super, conference, superuser):
        Order.objects.create(
            conference=conference,
            user=superuser,
            status=Order.Status.PAID,
            total=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            reference="ORD-001",
        )
        Order.objects.create(
            conference=conference,
            user=superuser,
            status=Order.Status.PAID,
            total=Decimal("50.00"),
            subtotal=Decimal("50.00"),
            reference="ORD-002",
        )
        resp = client_logged_in_super.get(_dashboard_url(conference))
        revenue = resp.context["revenue"]
        assert revenue["total"] == Decimal("150.00")
        assert revenue["net"] == Decimal("150.00")

    def test_refunded_amount_from_credits(self, client_logged_in_super, conference, superuser):
        paid = Order.objects.create(
            conference=conference,
            user=superuser,
            status=Order.Status.PAID,
            total=Decimal("200.00"),
            subtotal=Decimal("200.00"),
            reference="ORD-PAID",
        )
        refunded = Order.objects.create(
            conference=conference,
            user=superuser,
            status=Order.Status.REFUNDED,
            total=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            reference="ORD-REF",
        )
        # Partial refund: $30 credit issued from that refunded order
        Credit.objects.create(
            user=superuser,
            conference=conference,
            amount=Decimal("30.00"),
            status=Credit.Status.AVAILABLE,
            source_order=refunded,
        )

        resp = client_logged_in_super.get(_dashboard_url(conference))
        revenue = resp.context["revenue"]
        assert revenue["total"] == Decimal("200.00")
        assert revenue["refunded"] == Decimal("30.00")
        assert revenue["net"] == Decimal("170.00")

    def test_credits_outstanding_uses_remaining_amount(self, client_logged_in_super, conference, superuser):
        order = Order.objects.create(
            conference=conference,
            user=superuser,
            status=Order.Status.REFUNDED,
            total=Decimal("50.00"),
            subtotal=Decimal("50.00"),
            reference="ORD-CR",
        )
        # Available credit with partial spend
        credit = Credit.objects.create(
            user=superuser,
            conference=conference,
            amount=Decimal("50.00"),
            status=Credit.Status.AVAILABLE,
            source_order=order,
        )
        # remaining_amount is initialized by save() to match amount; simulate partial use
        credit.remaining_amount = Decimal("20.00")
        credit.save()

        # Applied credit
        Credit.objects.create(
            user=superuser,
            conference=conference,
            amount=Decimal("10.00"),
            remaining_amount=Decimal("0.00"),
            status=Credit.Status.APPLIED,
            source_order=order,
        )

        resp = client_logged_in_super.get(_dashboard_url(conference))
        revenue = resp.context["revenue"]
        assert revenue["credits_outstanding"] == Decimal("20.00")
        assert revenue["credits_applied"] == Decimal("10.00")
        assert revenue["credits_issued"] == Decimal("60.00")

    def test_credits_outstanding_in_template(self, client_logged_in_super, conference, superuser):
        order = Order.objects.create(
            conference=conference,
            user=superuser,
            status=Order.Status.REFUNDED,
            total=Decimal("75.00"),
            subtotal=Decimal("75.00"),
            reference="ORD-TMPL",
        )
        Credit.objects.create(
            user=superuser,
            conference=conference,
            amount=Decimal("75.00"),
            status=Credit.Status.AVAILABLE,
            source_order=order,
        )
        resp = client_logged_in_super.get(_dashboard_url(conference))
        content = resp.content.decode()
        assert "$75.00" in content
        assert "Credits Outstanding" in content


@pytest.mark.django_db
class TestFinancialDashboardOrdersByStatus:
    """Order breakdown by status uses aggregated query."""

    def test_orders_counted_by_status(self, client_logged_in_super, conference, superuser):
        Order.objects.create(
            conference=conference,
            user=superuser,
            status=Order.Status.PAID,
            total=Decimal("10.00"),
            subtotal=Decimal("10.00"),
            reference="ORD-P1",
        )
        Order.objects.create(
            conference=conference,
            user=superuser,
            status=Order.Status.PAID,
            total=Decimal("20.00"),
            subtotal=Decimal("20.00"),
            reference="ORD-P2",
        )
        Order.objects.create(
            conference=conference,
            user=superuser,
            status=Order.Status.PENDING,
            total=Decimal("15.00"),
            subtotal=Decimal("15.00"),
            reference="ORD-PE1",
        )
        Order.objects.create(
            conference=conference,
            user=superuser,
            status=Order.Status.CANCELLED,
            total=Decimal("5.00"),
            subtotal=Decimal("5.00"),
            reference="ORD-C1",
        )
        resp = client_logged_in_super.get(_dashboard_url(conference))
        ctx = resp.context
        assert ctx["orders_by_status"]["paid"] == 2
        assert ctx["orders_by_status"]["pending"] == 1
        assert ctx["orders_by_status"]["cancelled"] == 1
        assert ctx["orders_by_status"]["refunded"] == 0
        assert ctx["orders_by_status"]["partially_refunded"] == 0
        assert ctx["total_orders"] == 4


@pytest.mark.django_db
class TestFinancialDashboardCartsByStatus:
    """Cart breakdown by status."""

    def test_active_carts_filter(self, client_logged_in_super, conference, superuser):
        now = timezone.now()
        # Active: open, no expiry
        Cart.objects.create(
            conference=conference,
            user=superuser,
            status=Cart.Status.OPEN,
        )
        # Active: open, expires in the future
        Cart.objects.create(
            conference=conference,
            user=superuser,
            status=Cart.Status.OPEN,
            expires_at=now + timedelta(hours=1),
        )
        # Not active: open but expired
        Cart.objects.create(
            conference=conference,
            user=superuser,
            status=Cart.Status.OPEN,
            expires_at=now - timedelta(hours=1),
        )
        # Expired status
        Cart.objects.create(
            conference=conference,
            user=superuser,
            status=Cart.Status.EXPIRED,
        )
        # Checked out
        Cart.objects.create(
            conference=conference,
            user=superuser,
            status=Cart.Status.CHECKED_OUT,
        )
        # Abandoned
        Cart.objects.create(
            conference=conference,
            user=superuser,
            status=Cart.Status.ABANDONED,
        )

        resp = client_logged_in_super.get(_dashboard_url(conference))
        carts = resp.context["carts_by_status"]
        assert carts["active"] == 2
        assert carts["expired"] == 1
        assert carts["checked_out"] == 1
        assert carts["abandoned"] == 1

    def test_active_carts_list(self, client_logged_in_super, conference, superuser):
        Cart.objects.create(
            conference=conference,
            user=superuser,
            status=Cart.Status.OPEN,
        )
        resp = client_logged_in_super.get(_dashboard_url(conference))
        active_carts = resp.context["active_carts"]
        assert len(active_carts) == 1


@pytest.mark.django_db
class TestFinancialDashboardPayments:
    """Payment breakdown by status and method."""

    def test_payments_by_status(self, client_logged_in_super, conference, superuser):
        order = Order.objects.create(
            conference=conference,
            user=superuser,
            status=Order.Status.PAID,
            total=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            reference="ORD-PAY",
        )
        Payment.objects.create(
            order=order,
            method=Payment.Method.STRIPE,
            status=Payment.Status.SUCCEEDED,
            amount=Decimal("100.00"),
        )
        Payment.objects.create(
            order=order,
            method=Payment.Method.MANUAL,
            status=Payment.Status.PENDING,
            amount=Decimal("25.00"),
        )

        resp = client_logged_in_super.get(_dashboard_url(conference))
        ctx = resp.context
        assert ctx["payments_by_status"]["succeeded"] == 1
        assert ctx["payments_by_status"]["pending"] == 1
        assert ctx["total_payments"] == 2

    def test_payments_by_method(self, client_logged_in_super, conference, superuser):
        order = Order.objects.create(
            conference=conference,
            user=superuser,
            status=Order.Status.PAID,
            total=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            reference="ORD-PM",
        )
        Payment.objects.create(
            order=order,
            method=Payment.Method.STRIPE,
            status=Payment.Status.SUCCEEDED,
            amount=Decimal("80.00"),
        )
        Payment.objects.create(
            order=order,
            method=Payment.Method.CREDIT,
            status=Payment.Status.SUCCEEDED,
            amount=Decimal("20.00"),
        )

        resp = client_logged_in_super.get(_dashboard_url(conference))
        methods = resp.context["payments_by_method"]
        assert methods["stripe"]["count"] == 1
        assert methods["stripe"]["total_amount"] == Decimal("80.00")
        assert methods["credit"]["count"] == 1
        assert methods["credit"]["total_amount"] == Decimal("20.00")

    def test_payments_table_shown_when_payments_exist(self, client_logged_in_super, conference, superuser):
        order = Order.objects.create(
            conference=conference,
            user=superuser,
            status=Order.Status.PAID,
            total=Decimal("50.00"),
            subtotal=Decimal("50.00"),
            reference="ORD-TBL",
        )
        Payment.objects.create(
            order=order,
            method=Payment.Method.STRIPE,
            status=Payment.Status.SUCCEEDED,
            amount=Decimal("50.00"),
        )
        resp = client_logged_in_super.get(_dashboard_url(conference))
        content = resp.content.decode()
        assert "No payments recorded." not in content


@pytest.mark.django_db
class TestFinancialDashboardTicketSales:
    """Ticket sales annotations use Sum of quantity and include PARTIALLY_REFUNDED."""

    def test_sold_count_uses_quantity(self, client_logged_in_super, conference, superuser):
        ticket = TicketType.objects.create(
            conference=conference,
            name="General",
            slug="general",
            price=Decimal("50.00"),
            order=0,
        )
        order = Order.objects.create(
            conference=conference,
            user=superuser,
            status=Order.Status.PAID,
            total=Decimal("150.00"),
            subtotal=Decimal("150.00"),
            reference="ORD-TIX",
        )
        OrderLineItem.objects.create(
            order=order,
            description="General",
            quantity=3,
            unit_price=Decimal("50.00"),
            line_total=Decimal("150.00"),
            ticket_type=ticket,
        )

        resp = client_logged_in_super.get(_dashboard_url(conference))
        sales = list(resp.context["ticket_sales"])
        assert len(sales) == 1
        assert sales[0].sold_count == 3
        assert sales[0].ticket_revenue == Decimal("150.00")

    def test_partially_refunded_orders_included(self, client_logged_in_super, conference, superuser):
        ticket = TicketType.objects.create(
            conference=conference,
            name="VIP",
            slug="vip",
            price=Decimal("100.00"),
            order=0,
        )
        order = Order.objects.create(
            conference=conference,
            user=superuser,
            status=Order.Status.PARTIALLY_REFUNDED,
            total=Decimal("200.00"),
            subtotal=Decimal("200.00"),
            reference="ORD-PR",
        )
        OrderLineItem.objects.create(
            order=order,
            description="VIP",
            quantity=2,
            unit_price=Decimal("100.00"),
            line_total=Decimal("200.00"),
            ticket_type=ticket,
        )

        resp = client_logged_in_super.get(_dashboard_url(conference))
        sales = list(resp.context["ticket_sales"])
        assert len(sales) == 1
        assert sales[0].sold_count == 2

    def test_ticket_with_no_sales_shows_zero(self, client_logged_in_super, conference):
        TicketType.objects.create(
            conference=conference,
            name="Student",
            slug="student",
            price=Decimal("25.00"),
            order=0,
        )
        resp = client_logged_in_super.get(_dashboard_url(conference))
        sales = list(resp.context["ticket_sales"])
        assert len(sales) == 1
        assert sales[0].sold_count == 0


@pytest.mark.django_db
class TestFinancialDashboardRecentOrders:
    """Recent orders limited to 20."""

    def test_recent_orders_limited_to_20(self, client_logged_in_super, conference, superuser):
        for i in range(25):
            Order.objects.create(
                conference=conference,
                user=superuser,
                status=Order.Status.PAID,
                total=Decimal("10.00"),
                subtotal=Decimal("10.00"),
                reference=f"ORD-RECENT-{i:03d}",
            )
        resp = client_logged_in_super.get(_dashboard_url(conference))
        assert len(resp.context["recent_orders"]) == 20


@pytest.mark.django_db
class TestFinancialDashboardSidebarNavigation:
    """Sidebar contains a link to the financial dashboard."""

    def test_sidebar_has_financial_link(self, client_logged_in_super, conference):
        resp = client_logged_in_super.get(_dashboard_url(conference))
        content = resp.content.decode()
        expected_url = reverse("manage:financial-dashboard", kwargs={"conference_slug": conference.slug})
        assert expected_url in content
        assert "Financial" in content

    def test_active_nav_set_to_financial(self, client_logged_in_super, conference):
        resp = client_logged_in_super.get(_dashboard_url(conference))
        assert resp.context["active_nav"] == "financial"


@pytest.mark.django_db
class TestFinancialDashboardPaymentMethodsZeroFill:
    """payments_by_method has entries for all methods, even with no data."""

    def test_unused_methods_have_zero_count(self, client_logged_in_super, conference, superuser):
        order = Order.objects.create(
            conference=conference,
            user=superuser,
            status=Order.Status.PAID,
            total=Decimal("50.00"),
            subtotal=Decimal("50.00"),
            reference="ORD-ZERO",
        )
        Payment.objects.create(
            order=order,
            method=Payment.Method.STRIPE,
            status=Payment.Status.SUCCEEDED,
            amount=Decimal("50.00"),
        )
        resp = client_logged_in_super.get(_dashboard_url(conference))
        methods = resp.context["payments_by_method"]
        for method_value, _label in Payment.Method.choices:
            assert method_value in methods
        assert methods["comp"]["count"] == 0
        assert methods["comp"]["total_amount"] == Decimal("0.00")
        assert methods["manual"]["count"] == 0


@pytest.mark.django_db
class TestFinancialDashboardURLResolution:
    """URL pattern resolves correctly."""

    def test_financial_dashboard_url(self):
        url = reverse("manage:financial-dashboard", kwargs={"conference_slug": "test-conf"})
        assert url == "/manage/test-conf/financial/"
