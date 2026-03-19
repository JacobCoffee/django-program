"""Tests for the analytics & KPI report functions and dashboard views."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission, User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from django_program.conference.models import Conference
from django_program.pretalx.models import Room, ScheduleSlot, Talk
from django_program.programs.models import Activity, ActivitySignup, TravelGrant
from django_program.registration.models import (
    Attendee,
    Cart,
    Order,
)
from django_program.sponsors.models import Sponsor, SponsorBenefit, SponsorLevel

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
    """A user with the view_reports permission via the Reports Viewer group."""
    user = User.objects.create_user(username="reporter", password="password", email="reporter@test.com")
    group, _created = Group.objects.get_or_create(name="Reports Viewer")
    perm = Permission.objects.get(content_type__app_label="program_conference", codename="view_reports")
    group.permissions.add(perm)
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
        revenue_budget=Decimal("100000.00"),
        target_attendance=500,
        grant_budget=Decimal("50000.00"),
    )


@pytest.fixture
def previous_conference(db):
    return Conference.objects.create(
        name="Previous Conf",
        slug="prev-conf",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 3),
        timezone="UTC",
        is_active=False,
    )


@pytest.fixture
def client_logged_in_super(superuser):
    c = Client()
    c.login(username="admin", password="password")
    return c


@pytest.fixture
def client_logged_in_reports(reports_user):
    c = Client()
    c.login(username="reporter", password="password")
    return c


@pytest.fixture
def client_logged_in_regular(regular_user):
    c = Client()
    c.login(username="regular", password="password")
    return c


def _analytics_url(conference):
    return reverse("manage:analytics-dashboard", kwargs={"conference_slug": conference.slug})


def _cross_event_url(conference):
    return reverse("manage:cross-event-dashboard", kwargs={"conference_slug": conference.slug})


# ---------------------------------------------------------------------------
# Tier 1: Revenue per attendee
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRevenuePerAttendee:
    """Tests for get_revenue_per_attendee report function."""

    def test_zero_with_no_data(self, conference):
        from django_program.manage.reports import get_revenue_per_attendee

        result = get_revenue_per_attendee(conference)
        assert result["net_revenue"] == Decimal("0.00")
        assert result["attendee_count"] == 0
        assert result["revenue_per_attendee"] == Decimal("0.00")

    def test_calculates_correctly(self, conference, superuser):
        from django_program.manage.reports import get_revenue_per_attendee

        Order.objects.create(
            conference=conference,
            user=superuser,
            status=Order.Status.PAID,
            total=Decimal("200.00"),
            subtotal=Decimal("200.00"),
            reference="ORD-RPA-1",
        )
        Attendee.objects.create(conference=conference, user=superuser)

        user2 = User.objects.create_user(username="u2", password="p", email="u2@test.com")
        Order.objects.create(
            conference=conference,
            user=user2,
            status=Order.Status.PAID,
            total=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            reference="ORD-RPA-2",
        )
        Attendee.objects.create(conference=conference, user=user2)

        result = get_revenue_per_attendee(conference)
        assert result["net_revenue"] == Decimal("300.00")
        assert result["attendee_count"] == 2
        assert result["revenue_per_attendee"] == Decimal("150.00")


# ---------------------------------------------------------------------------
# Tier 1: Cart funnel
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCartFunnel:
    """Tests for get_cart_funnel report function."""

    def test_empty_conference(self, conference):
        from django_program.manage.reports import get_cart_funnel

        result = get_cart_funnel(conference)
        assert result["total_carts"] == 0
        assert result["abandonment_rate"] == Decimal("0.00")
        assert result["conversion_rate"] == Decimal("0.00")

    def test_calculates_rates(self, conference, superuser):
        from django_program.manage.reports import get_cart_funnel

        Cart.objects.create(conference=conference, user=superuser, status=Cart.Status.OPEN)
        Cart.objects.create(conference=conference, user=superuser, status=Cart.Status.CHECKED_OUT)
        Cart.objects.create(conference=conference, user=superuser, status=Cart.Status.ABANDONED)
        Cart.objects.create(conference=conference, user=superuser, status=Cart.Status.EXPIRED)

        result = get_cart_funnel(conference)
        assert result["total_carts"] == 4
        assert result["completed"] == 1
        assert result["abandoned"] == 1
        assert result["expired"] == 1
        assert result["conversion_rate"] == Decimal("25.00")
        assert result["abandonment_rate"] == Decimal("50.00")


# ---------------------------------------------------------------------------
# Tier 1: Room utilization
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRoomUtilization:
    """Tests for get_room_utilization report function."""

    def test_empty_conference(self, conference):
        from django_program.manage.reports import get_room_utilization

        result = get_room_utilization(conference)
        assert result == []

    def test_room_with_talks(self, conference):
        from django_program.manage.reports import get_room_utilization

        room = Room.objects.create(conference=conference, name="Main Hall", capacity=500)
        talk = Talk.objects.create(
            conference=conference,
            pretalx_code="ABC",
            title="Test Talk",
            state="confirmed",
        )
        now = timezone.now()
        ScheduleSlot.objects.create(
            conference=conference,
            room=room,
            talk=talk,
            start=now,
            end=now + timedelta(hours=1),
            slot_type=ScheduleSlot.SlotType.TALK,
        )
        ScheduleSlot.objects.create(
            conference=conference,
            room=room,
            start=now + timedelta(hours=1),
            end=now + timedelta(hours=1, minutes=30),
            slot_type=ScheduleSlot.SlotType.BREAK,
            title="Coffee Break",
        )

        result = get_room_utilization(conference)
        assert len(result) == 1
        assert result[0]["room_name"] == "Main Hall"
        assert result[0]["total_slots"] == 2
        assert result[0]["talk_slots"] == 1
        assert result[0]["utilization_pct"] == Decimal("50.00")


# ---------------------------------------------------------------------------
# Tier 1: Travel grant analytics
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTravelGrantAnalytics:
    """Tests for get_travel_grant_analytics report function."""

    def test_empty_conference(self, conference):
        from django_program.manage.reports import get_travel_grant_analytics

        result = get_travel_grant_analytics(conference)
        assert result["total_applications"] == 0
        assert result["approval_rate"] == Decimal("0.00")

    def test_calculates_rates(self, conference, superuser):
        from django_program.manage.reports import get_travel_grant_analytics

        TravelGrant.objects.create(
            conference=conference,
            user=superuser,
            status=TravelGrant.GrantStatus.ACCEPTED,
            requested_amount=Decimal("2000.00"),
            approved_amount=Decimal("1500.00"),
            disbursed_amount=Decimal("1500.00"),
        )
        user2 = User.objects.create_user(username="u2g", password="p", email="u2g@test.com")
        TravelGrant.objects.create(
            conference=conference,
            user=user2,
            status=TravelGrant.GrantStatus.REJECTED,
            requested_amount=Decimal("3000.00"),
        )

        result = get_travel_grant_analytics(conference)
        assert result["total_applications"] == 2
        assert result["total_requested"] == Decimal("5000.00")
        assert result["total_approved"] == Decimal("1500.00")


# ---------------------------------------------------------------------------
# Tier 1: Activity utilization
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestActivityUtilization:
    """Tests for get_activity_utilization report function."""

    def test_empty_conference(self, conference):
        from django_program.manage.reports import get_activity_utilization

        result = get_activity_utilization(conference)
        assert result == []

    def test_activity_with_signups(self, conference, superuser):
        from django_program.manage.reports import get_activity_utilization

        activity = Activity.objects.create(
            conference=conference,
            name="Sprint",
            slug="sprint",
            max_participants=10,
            is_active=True,
        )
        ActivitySignup.objects.create(
            activity=activity,
            user=superuser,
            status=ActivitySignup.SignupStatus.CONFIRMED,
        )
        user2 = User.objects.create_user(username="u2a", password="p", email="u2a@test.com")
        ActivitySignup.objects.create(
            activity=activity,
            user=user2,
            status=ActivitySignup.SignupStatus.WAITLISTED,
        )

        result = get_activity_utilization(conference)
        assert len(result) == 1
        assert result[0]["confirmed"] == 1
        assert result[0]["waitlisted"] == 1
        assert result[0]["utilization_pct"] == Decimal("10.00")


# ---------------------------------------------------------------------------
# Tier 1: Sponsor benefit fulfillment
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSponsorBenefitFulfillment:
    """Tests for get_sponsor_benefit_fulfillment report function."""

    def test_empty_conference(self, conference):
        from django_program.manage.reports import get_sponsor_benefit_fulfillment

        result = get_sponsor_benefit_fulfillment(conference)
        assert result["total_benefits"] == 0
        assert result["fulfillment_rate"] == Decimal("0.00")

    def test_calculates_fulfillment(self, conference):
        from django_program.manage.reports import get_sponsor_benefit_fulfillment

        level = SponsorLevel.objects.create(conference=conference, name="Gold", slug="gold", cost=Decimal("10000.00"))
        sponsor = Sponsor.objects.create(
            conference=conference, name="Acme Corp", slug="acme", level=level, is_active=True
        )
        SponsorBenefit.objects.create(sponsor=sponsor, name="Logo on website", is_complete=True)
        SponsorBenefit.objects.create(sponsor=sponsor, name="Booth space", is_complete=False)
        SponsorBenefit.objects.create(sponsor=sponsor, name="Talk slot", is_complete=True)

        result = get_sponsor_benefit_fulfillment(conference)
        assert result["total_benefits"] == 3
        assert result["completed"] == 2
        assert result["pending"] == 1
        # 2/3 * 100 = 66.67
        assert round(result["fulfillment_rate"], 2) == Decimal("66.67")


# ---------------------------------------------------------------------------
# Tier 1: Content analytics
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestContentAnalytics:
    """Tests for get_content_analytics report function."""

    def test_empty_conference(self, conference):
        from django_program.manage.reports import get_content_analytics

        result = get_content_analytics(conference)
        assert result["total_talks"] == 0
        assert result["total_rooms"] == 0

    def test_counts_talks_by_state(self, conference):
        from django_program.manage.reports import get_content_analytics

        Talk.objects.create(conference=conference, pretalx_code="T1", title="Talk 1", state="confirmed")
        Talk.objects.create(conference=conference, pretalx_code="T2", title="Talk 2", state="confirmed")
        Talk.objects.create(conference=conference, pretalx_code="T3", title="Talk 3", state="withdrawn")

        result = get_content_analytics(conference)
        assert result["total_talks"] == 3
        assert result["by_state"]["confirmed"] == 2
        assert result["by_state"]["withdrawn"] == 1


# ---------------------------------------------------------------------------
# Analytics Dashboard View
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAnalyticsDashboardView:
    """Tests for the analytics dashboard view."""

    def test_unauthenticated_redirects(self, conference):
        c = Client()
        resp = c.get(_analytics_url(conference))
        assert resp.status_code == 302
        assert "login" in resp.url

    def test_regular_user_403(self, client_logged_in_regular, conference):
        resp = client_logged_in_regular.get(_analytics_url(conference))
        assert resp.status_code == 403

    def test_superuser_can_access(self, client_logged_in_super, conference):
        resp = client_logged_in_super.get(_analytics_url(conference))
        assert resp.status_code == 200

    def test_reports_group_can_access(self, client_logged_in_reports, conference):
        resp = client_logged_in_reports.get(_analytics_url(conference))
        assert resp.status_code == 200

    def test_empty_conference_loads(self, client_logged_in_super, conference):
        resp = client_logged_in_super.get(_analytics_url(conference))
        assert resp.status_code == 200
        ctx = resp.context
        assert "kpi_summary" in ctx
        assert "cart_funnel" in ctx
        assert "revenue_breakdown" in ctx

    def test_kpi_summary_present(self, client_logged_in_super, conference, superuser):
        Order.objects.create(
            conference=conference,
            user=superuser,
            status=Order.Status.PAID,
            total=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            reference="ORD-KPI-1",
        )
        Attendee.objects.create(conference=conference, user=superuser)

        resp = client_logged_in_super.get(_analytics_url(conference))
        kpi = resp.context["kpi_summary"]
        assert kpi["revenue_per_attendee"] == Decimal("100.00")


# ---------------------------------------------------------------------------
# Cross-Event Dashboard View
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCrossEventDashboardView:
    """Tests for the cross-event intelligence dashboard view."""

    def test_unauthenticated_redirects(self, conference):
        c = Client()
        resp = c.get(_cross_event_url(conference))
        assert resp.status_code == 302

    def test_regular_user_403(self, client_logged_in_regular, conference):
        resp = client_logged_in_regular.get(_cross_event_url(conference))
        assert resp.status_code == 403

    def test_superuser_can_access(self, client_logged_in_super, conference):
        resp = client_logged_in_super.get(_cross_event_url(conference))
        assert resp.status_code == 200

    def test_empty_conference_loads(self, client_logged_in_super, conference):
        resp = client_logged_in_super.get(_cross_event_url(conference))
        assert resp.status_code == 200
        ctx = resp.context
        assert "retention" in ctx
        assert "ltv" in ctx

    def test_yoy_retention_with_returning_attendee(
        self, client_logged_in_super, conference, previous_conference, superuser
    ):
        # Same user attended both conferences
        Attendee.objects.create(conference=previous_conference, user=superuser)
        Attendee.objects.create(conference=conference, user=superuser)

        resp = client_logged_in_super.get(_cross_event_url(conference))
        retention = resp.context["retention"]
        assert retention["returning_count"] == 1
        assert retention["current_attendee_count"] == 1


# ---------------------------------------------------------------------------
# URL Resolution
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAnalyticsURLs:
    """URL pattern tests."""

    def test_analytics_dashboard_url(self):
        url = reverse("manage:analytics-dashboard", kwargs={"conference_slug": "test-conf"})
        assert url == "/manage/test-conf/analytics/"

    def test_cross_event_dashboard_url(self):
        url = reverse("manage:cross-event-dashboard", kwargs={"conference_slug": "test-conf"})
        assert url == "/manage/test-conf/analytics/cross-event/"


# ---------------------------------------------------------------------------
# KPI Targets (#49)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestKPITargets:
    """Tests for the KPITargets model and integration."""

    def test_create_kpi_targets(self, conference):
        """KPITargets can be created for a conference."""
        from django_program.conference.models import KPITargets

        targets = KPITargets.objects.create(
            conference=conference,
            target_conversion_rate=Decimal("5.0"),
            target_refund_rate=Decimal("3.0"),
            target_checkin_rate=Decimal("85.0"),
            target_fulfillment_rate=Decimal("95.0"),
            target_revenue_per_attendee=Decimal("150.00"),
            target_room_utilization=Decimal("35.0"),
        )
        assert str(targets) == f"KPI targets for {conference}"
        assert targets.target_conversion_rate == Decimal("5.0")

    def test_defaults_used_without_targets(self, client_logged_in_super, conference):
        """Dashboard loads with default targets when no KPITargets exist."""
        resp = client_logged_in_super.get(_analytics_url(conference))
        assert resp.status_code == 200
        ctx = resp.context
        assert "kpi_targets" in ctx
        # Default conversion rate target should be 3.0
        assert ctx["kpi_targets"]["target_conversion_rate"] == Decimal("3.0")

    def test_custom_targets_override_defaults(self, client_logged_in_super, conference):
        """Custom KPITargets override the defaults."""
        from django_program.conference.models import KPITargets

        KPITargets.objects.create(
            conference=conference,
            target_conversion_rate=Decimal("10.0"),
        )
        resp = client_logged_in_super.get(_analytics_url(conference))
        ctx = resp.context
        assert ctx["kpi_targets"]["target_conversion_rate"] == Decimal("10.0")
        # Non-overridden fields should still use defaults
        assert ctx["kpi_targets"]["target_refund_rate"] == Decimal("5.0")

    def test_refund_rate_in_kpi_summary(self, client_logged_in_super, conference):
        """Refund rate is included in the KPI summary."""
        resp = client_logged_in_super.get(_analytics_url(conference))
        assert "refund_rate" in resp.context["kpi_summary"]


# ---------------------------------------------------------------------------
# Sponsor Analytics (#48)
# ---------------------------------------------------------------------------


def _sponsor_analytics_url(conference):
    return reverse("manage:sponsor-analytics", kwargs={"conference_slug": conference.slug})


@pytest.mark.django_db
class TestSponsorAnalyticsReport:
    """Tests for get_sponsor_analytics report function."""

    def test_empty_conference(self, conference):
        from django_program.manage.reports_analytics import get_sponsor_analytics

        result = get_sponsor_analytics(conference)
        assert result["total_sponsors"] == 0
        assert result["total_sponsor_revenue"] == Decimal("0.00")
        assert result["by_level"] == []

    def test_with_sponsors(self, conference):
        from django_program.manage.reports_analytics import get_sponsor_analytics

        level = SponsorLevel.objects.create(conference=conference, name="Gold", slug="gold", cost=Decimal("10000.00"))
        Sponsor.objects.create(conference=conference, name="Acme", slug="acme", level=level, is_active=True)
        Sponsor.objects.create(conference=conference, name="Beta Inc", slug="beta", level=level, is_active=True)
        result = get_sponsor_analytics(conference)
        assert result["total_sponsors"] == 2
        assert result["total_sponsor_revenue"] == Decimal("20000.00")
        assert len(result["by_level"]) == 1
        assert result["by_level"][0]["sponsor_count"] == 2


@pytest.mark.django_db
class TestSponsorAnalyticsView:
    """Tests for the sponsor analytics dashboard view."""

    def test_unauthenticated_redirects(self, conference):
        c = Client()
        resp = c.get(_sponsor_analytics_url(conference))
        assert resp.status_code == 302
        assert "login" in resp.url

    def test_regular_user_403(self, client_logged_in_regular, conference):
        resp = client_logged_in_regular.get(_sponsor_analytics_url(conference))
        assert resp.status_code == 403

    def test_superuser_can_access(self, client_logged_in_super, conference):
        resp = client_logged_in_super.get(_sponsor_analytics_url(conference))
        assert resp.status_code == 200

    def test_context_keys(self, client_logged_in_super, conference):
        resp = client_logged_in_super.get(_sponsor_analytics_url(conference))
        ctx = resp.context
        assert "sponsor_analytics" in ctx
        assert "sponsor_fulfillment" in ctx
        assert "sponsor_renewal" in ctx


# ---------------------------------------------------------------------------
# Clickable Charts / Drill-down Data (#47)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDrilldownData:
    """Tests for drill-down data in report functions."""

    def test_room_utilization_includes_room_id(self, conference):
        from django_program.manage.reports import get_room_utilization

        room = Room.objects.create(conference=conference, name="Main", capacity=100)
        ScheduleSlot.objects.create(
            conference=conference,
            room=room,
            start=timezone.now(),
            end=timezone.now() + timedelta(hours=1),
            slot_type=ScheduleSlot.SlotType.TALK,
            title="Test",
        )
        result = get_room_utilization(conference)
        assert len(result) == 1
        assert "room_id" in result[0]
        assert result[0]["room_id"] == room.pk

    def test_activity_utilization_includes_activity_id(self, conference, superuser):
        from django_program.manage.reports import get_activity_utilization

        activity = Activity.objects.create(
            conference=conference,
            name="Sprint",
            slug="sprint",
            max_participants=10,
            is_active=True,
        )
        ActivitySignup.objects.create(
            activity=activity,
            user=superuser,
            status=ActivitySignup.SignupStatus.CONFIRMED,
        )
        result = get_activity_utilization(conference)
        assert len(result) == 1
        assert "activity_id" in result[0]
        assert result[0]["activity_id"] == activity.pk


@pytest.mark.django_db
class TestAnalyticsURLPatterns:
    """URL pattern tests for new analytics routes."""

    def test_sponsor_analytics_url(self):
        url = reverse("manage:sponsor-analytics", kwargs={"conference_slug": "test-conf"})
        assert url == "/manage/test-conf/analytics/sponsors/"
