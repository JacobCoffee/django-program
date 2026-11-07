"""Coverage tests for django_program.manage.reports and views_reports.

Exercises branches and functions not hit by the existing
test_report_views.py suite: the invalid-ticket-type-id fallback, the
date_until upper-bound filters, sponsor revenue in the revenue breakdown,
early-bird/capacity branches in ticket sales ratio, check-in throughput
bucketing, schedule-slot-type and letter-status aggregation loops, the
reports dashboard's budget-vs-actuals context, and the visa letter CSV
export view.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission, User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from django_program.conference.models import Conference
from django_program.manage.reports import (
    get_aov_by_date,
    get_attendee_manifest,
    get_checkin_throughput,
    get_content_analytics,
    get_letter_request_summary,
    get_revenue_breakdown,
    get_revenue_by_ticket_type,
    get_ticket_sales_ratio,
)
from django_program.pretalx.models import ScheduleSlot, Talk
from django_program.programs.models import TravelGrant
from django_program.registration.letter import LetterRequest
from django_program.registration.models import Attendee, Order, OrderLineItem, TicketType
from django_program.sponsors.models import Sponsor, SponsorLevel

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(username="admin", password="password", email="admin@test.com")


@pytest.fixture
def reports_user(db):
    """A user with view_reports and export_reports permissions via the Reports Viewer group."""
    user = User.objects.create_user(username="reporter", password="password", email="reporter@test.com")
    group, _created = Group.objects.get_or_create(name="Reports Viewer")
    for codename in ("view_reports", "export_reports"):
        perm = Permission.objects.get(content_type__app_label="program_conference", codename=codename)
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
    )


@pytest.fixture
def budgeted_conference(db):
    return Conference.objects.create(
        name="Budgeted Conf",
        slug="budgeted-conf",
        start_date=date(2027, 6, 1),
        end_date=date(2027, 6, 3),
        timezone="UTC",
        is_active=True,
        revenue_budget=Decimal("10000.00"),
        target_attendance=100,
        grant_budget=Decimal("5000.00"),
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


def _url(name: str, conference: Conference) -> str:
    return reverse(f"manage:{name}", kwargs={"conference_slug": conference.slug})


# ---------------------------------------------------------------------------
# get_attendee_manifest — invalid ticket_type_id fallback
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAttendeeManifestInvalidTicketTypeId:
    def test_non_numeric_ticket_type_id_is_ignored(self, conference, superuser):
        Attendee.objects.create(conference=conference, user=superuser)

        qs = get_attendee_manifest(conference, ticket_type_id="not-a-number")

        assert qs.count() == 1


# ---------------------------------------------------------------------------
# get_aov_by_date / get_revenue_by_ticket_type — date_until upper bound
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDateUntilFilters:
    def test_aov_by_date_respects_date_until(self, conference, superuser):
        Order.objects.create(
            conference=conference,
            user=superuser,
            status=Order.Status.PAID,
            total=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            reference="ORD-AOV-1",
        )

        yesterday = timezone.now().date() - timedelta(days=1)
        tomorrow = timezone.now().date() + timedelta(days=1)
        result = get_aov_by_date(conference, date_from=yesterday, date_until=tomorrow)

        assert len(result) == 1
        assert result[0]["count"] == 1

    def test_revenue_by_ticket_type_respects_date_until(self, conference, superuser):
        ticket = TicketType.objects.create(
            conference=conference,
            name="General",
            slug="general",
            price=Decimal("100.00"),
            total_quantity=100,
        )
        order = Order.objects.create(
            conference=conference,
            user=superuser,
            status=Order.Status.PAID,
            total=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            reference="ORD-RBT-1",
        )
        OrderLineItem.objects.create(
            order=order,
            description="General",
            quantity=1,
            unit_price=Decimal("100.00"),
            line_total=Decimal("100.00"),
            ticket_type=ticket,
        )

        yesterday = timezone.now().date() - timedelta(days=1)
        tomorrow = timezone.now().date() + timedelta(days=1)
        result = get_revenue_by_ticket_type(conference, date_from=yesterday, date_until=tomorrow)

        assert len(result) == 1
        assert result[0]["ticket_type"] == "General"
        assert result[0]["revenue"] == Decimal("100.00")


# ---------------------------------------------------------------------------
# get_revenue_breakdown — sponsor revenue loop
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRevenueBreakdownSponsorRevenue:
    def test_includes_sponsor_revenue_from_active_sponsors(self, conference):
        level = SponsorLevel.objects.create(conference=conference, name="Gold", cost=Decimal("5000.00"))
        Sponsor.objects.create(conference=conference, level=level, name="Acme Corp", is_active=True)
        Sponsor.objects.create(conference=conference, level=level, name="Inactive Co", is_active=False)

        result = get_revenue_breakdown(conference)

        assert result["sponsor_revenue"] == Decimal("5000.00")
        assert result["total_revenue"] == Decimal("5000.00")
        assert result["sponsor_pct"] == Decimal("100.00")


# ---------------------------------------------------------------------------
# get_ticket_sales_ratio — early-bird window and capacity/fill-rate
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTicketSalesRatio:
    def test_early_bird_window_and_fill_rate(self, conference, superuser):
        ticket = TicketType.objects.create(
            conference=conference,
            name="Early Bird",
            slug="early-bird",
            price=Decimal("80.00"),
            total_quantity=10,
            available_from=timezone.now() - timedelta(days=5),
            available_until=timezone.now() + timedelta(days=5),
        )
        order = Order.objects.create(
            conference=conference,
            user=superuser,
            status=Order.Status.PAID,
            total=Decimal("80.00"),
            subtotal=Decimal("80.00"),
            reference="ORD-TSR-1",
        )
        OrderLineItem.objects.create(
            order=order,
            description="Early Bird",
            quantity=1,
            unit_price=Decimal("80.00"),
            line_total=Decimal("80.00"),
            ticket_type=ticket,
        )

        result = get_ticket_sales_ratio(conference)

        assert len(result) == 1
        row = result[0]
        assert row["is_early_bird"] is True
        assert row["capacity"] == 10
        assert row["fill_rate"] == Decimal(10)
        assert row["revenue_pct"] == Decimal("100.00")


# ---------------------------------------------------------------------------
# get_checkin_throughput — time-bucketed check-ins
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCheckinThroughput:
    def test_buckets_checkin_timestamps(self, conference, superuser):
        Attendee.objects.create(
            conference=conference,
            user=superuser,
            checked_in_at=timezone.now(),
        )

        result = get_checkin_throughput(conference, bucket_minutes=15)

        assert len(result) == 1
        assert result[0]["count"] == 1
        assert result[0]["bucket_end"] - result[0]["bucket_start"] == timedelta(minutes=15)


# ---------------------------------------------------------------------------
# get_content_analytics — slot_types loop
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestContentAnalyticsSlotTypes:
    def test_counts_schedule_slots_by_type(self, conference):
        talk = Talk.objects.create(conference=conference, pretalx_code="T1", title="Talk 1")
        now = timezone.now()
        ScheduleSlot.objects.create(
            conference=conference,
            talk=talk,
            start=now,
            end=now + timedelta(minutes=30),
            slot_type=ScheduleSlot.SlotType.TALK,
        )
        ScheduleSlot.objects.create(
            conference=conference,
            start=now + timedelta(hours=1),
            end=now + timedelta(hours=1, minutes=15),
            slot_type=ScheduleSlot.SlotType.BREAK,
        )

        result = get_content_analytics(conference)

        assert result["slot_types"]["talk"] == 1
        assert result["slot_types"]["break"] == 1
        assert result["total_schedule_slots"] == 2


# ---------------------------------------------------------------------------
# get_letter_request_summary (reports.py) — by_status loop
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLetterRequestSummaryByStatus:
    def test_counts_by_status(self, conference, superuser):
        LetterRequest.objects.create(
            conference=conference,
            user=superuser,
            passport_name="Jane Doe",
            passport_number="X123456",
            nationality="Canadian",
            travel_from=date(2027, 4, 28),
            travel_until=date(2027, 5, 4),
            destination_address="123 Main St",
            status=LetterRequest.Status.SUBMITTED,
        )

        result = get_letter_request_summary(conference)

        assert result["total"] == 1
        assert result["by_status"]["submitted"] == 1
        assert result["pending_count"] == 1


# ---------------------------------------------------------------------------
# ReportsDashboardView — budget-vs-actuals context (views_reports.py)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReportsDashboardBudgetContext:
    def test_budget_fields_populate_context(self, client_logged_in_super, budgeted_conference, superuser):
        second_user = User.objects.create_user(username="second", password="password", email="second@test.com")

        Order.objects.create(
            conference=budgeted_conference,
            user=superuser,
            status=Order.Status.PAID,
            reference="ORD-DASH-BUDGET-1",
            total=Decimal("2500.00"),
            subtotal=Decimal("2500.00"),
        )
        Attendee.objects.create(user=superuser, conference=budgeted_conference)
        TravelGrant.objects.create(
            conference=budgeted_conference,
            user=superuser,
            status=TravelGrant.GrantStatus.ACCEPTED,
            requested_amount=Decimal("500.00"),
            approved_amount=Decimal("400.00"),
        )
        TravelGrant.objects.create(
            conference=budgeted_conference,
            user=second_user,
            status=TravelGrant.GrantStatus.DISBURSED,
            requested_amount=Decimal("300.00"),
            approved_amount=Decimal("300.00"),
            disbursed_amount=Decimal("300.00"),
        )

        resp = client_logged_in_super.get(_url("reports-dashboard", budgeted_conference))

        assert resp.status_code == 200
        budget = resp.context["budget"]
        assert budget["revenue_target"] == Decimal("10000.00")
        assert budget["revenue_actual"] == Decimal("2500.00")
        assert budget["attendance_target"] == 100
        assert budget["attendance_actual"] == 1
        assert budget["grant_target"] == Decimal("5000.00")
        assert budget["grant_committed"] == Decimal("400.00")
        assert budget["grant_disbursed"] == Decimal("300.00")
        assert "chart_budget_json" in resp.context


# ---------------------------------------------------------------------------
# VisaLetterExportView — CSV export
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestVisaLetterExportView:
    def test_exports_csv_with_reviewer_info(self, client_logged_in_reports, conference, reports_user, superuser):
        LetterRequest.objects.create(
            conference=conference,
            user=superuser,
            passport_name="Jane Doe",
            passport_number="X123456",
            nationality="Canadian",
            travel_from=date(2027, 4, 28),
            travel_until=date(2027, 5, 4),
            destination_address="123 Main St",
            embassy_name="Canadian Embassy",
            status=LetterRequest.Status.APPROVED,
            reviewed_by=reports_user,
            reviewed_at=timezone.now(),
        )

        resp = client_logged_in_reports.get(_url("report-visa-letters-export", conference))

        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/csv"
        content = resp.content.decode()
        assert "Jane Doe" in content
        assert "Canadian" in content
        assert "reporter" in content or reports_user.get_full_name() in content


# ---------------------------------------------------------------------------
# VisaLetterReportView — dashboard context
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestVisaLetterReportView:
    def test_builds_summary_and_chart_context(self, client_logged_in_reports, conference, superuser):
        LetterRequest.objects.create(
            conference=conference,
            user=superuser,
            passport_name="Jane Doe",
            passport_number="X123456",
            nationality="Canadian",
            travel_from=date(2027, 4, 28),
            travel_until=date(2027, 5, 4),
            destination_address="123 Main St",
            status=LetterRequest.Status.SUBMITTED,
        )

        resp = client_logged_in_reports.get(_url("report-visa-letters", conference))

        assert resp.status_code == 200
        assert resp.context["letter_summary"]["total"] == 1
        assert next(iter(resp.context["letter_requests"])).passport_name == "Jane Doe"
        assert "chart_data" in resp.context
