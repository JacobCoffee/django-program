"""Coverage backfill tests for django_program.manage.views / views_analytics / forms.

Targets the dashboard budget helper, ConferenceEditView's invalid-form branch,
TravelGrantManageListView's budget tracking block, the expense management CRUD
views (previously untested), and the analytics JSON-serialization helper.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from django_program.conference.models import Conference, Expense, ExpenseCategory
from django_program.manage.views_analytics import _decimal_to_float
from django_program.programs.models import TravelGrant
from django_program.registration.models import Order

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
def second_user(db):
    return User.objects.create_user(username="second", password="password", email="second@test.com")


@pytest.fixture
def client_logged_in_super(superuser):
    c = Client()
    c.login(username="admin", password="password")
    return c


@pytest.fixture
def conference(db):
    return Conference.objects.create(
        name="Test Conf",
        slug="test-conf",
        start_date=date(2027, 5, 1),
        end_date=date(2027, 5, 3),
        timezone="UTC",
        pretalx_event_slug="test-event",
        is_active=True,
    )


@pytest.fixture
def budgeted_conference(db):
    """A conference with all three budget fields set, for dashboard budget coverage."""
    return Conference.objects.create(
        name="Budgeted Conf",
        slug="budgeted-conf",
        start_date=date(2027, 5, 1),
        end_date=date(2027, 5, 3),
        timezone="UTC",
        pretalx_event_slug="budgeted-event",
        is_active=True,
        revenue_budget=Decimal("10000.00"),
        target_attendance=100,
        grant_budget=Decimal("5000.00"),
    )


@pytest.fixture
def expense_category(conference):
    return ExpenseCategory.objects.create(
        conference=conference,
        name="Venue",
        slug="venue",
        budget_amount="1000.00",
        order=1,
    )


# ---------------------------------------------------------------------------
# _build_dashboard_budget_context / DashboardView (views.py 745-777, 833-834)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDashboardBudgetContext:
    def test_dashboard_includes_budget_when_fields_set(
        self, client_logged_in_super, budgeted_conference, superuser, second_user
    ):
        from django_program.registration.attendee import Attendee

        Order.objects.create(
            conference=budgeted_conference,
            user=superuser,
            status=Order.Status.PAID,
            reference="ORD-BUDGET-1",
            total="2500.00",
        )
        Attendee.objects.create(user=superuser, conference=budgeted_conference)
        TravelGrant.objects.create(
            conference=budgeted_conference,
            user=superuser,
            status=TravelGrant.GrantStatus.ACCEPTED,
            requested_amount="500.00",
            approved_amount="400.00",
        )
        TravelGrant.objects.create(
            conference=budgeted_conference,
            user=second_user,
            status=TravelGrant.GrantStatus.DISBURSED,
            requested_amount="300.00",
            approved_amount="300.00",
            disbursed_amount="300.00",
        )

        url = reverse("manage:dashboard", kwargs={"conference_slug": budgeted_conference.slug})
        resp = client_logged_in_super.get(url)

        assert resp.status_code == 200
        budget = resp.context["budget"]
        assert budget["revenue_target"] == budgeted_conference.revenue_budget
        assert budget["revenue_actual"] == 2500
        assert budget["revenue_pct"] == 25.0
        assert budget["attendance_target"] == 100
        assert budget["attendance_actual"] == 1
        assert budget["attendance_pct"] == 1.0
        assert budget["grant_target"] == budgeted_conference.grant_budget
        assert budget["grant_committed"] == 400
        assert budget["grant_disbursed"] == 300
        assert budget["grant_pct"] == 8.0
        assert "chart_budget_json" in resp.context

    def test_dashboard_no_budget_when_fields_unset(self, client_logged_in_super, conference):
        """Conference without budget fields gets an empty budget dict (falsy)."""
        url = reverse("manage:dashboard", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200
        assert "budget" not in resp.context


# ---------------------------------------------------------------------------
# ConferenceEditView invalid-form branch (views.py 910)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestConferenceEditViewInvalidPost:
    def test_post_invalid_form_rerenders_with_errors(self, client_logged_in_super, conference):
        url = reverse("manage:conference-edit", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.post(
            url,
            {
                # "name" omitted -> required field missing, form invalid.
                "start_date": "2027-05-01",
                "end_date": "2027-05-03",
                "timezone": "UTC",
                "total_capacity": 0,
            },
        )
        assert resp.status_code == 200
        assert resp.context["form"].is_valid() is False
        conference.refresh_from_db()
        assert conference.name == "Test Conf"


# ---------------------------------------------------------------------------
# TravelGrantManageListView budget tracking (views.py 2004-2015)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTravelGrantListBudgetTracking:
    def test_grant_budget_context_present_when_set(
        self, client_logged_in_super, budgeted_conference, regular_user, second_user
    ):
        TravelGrant.objects.create(
            conference=budgeted_conference,
            user=regular_user,
            status=TravelGrant.GrantStatus.ACCEPTED,
            requested_amount="1000.00",
            approved_amount="800.00",
        )
        TravelGrant.objects.create(
            conference=budgeted_conference,
            user=second_user,
            status=TravelGrant.GrantStatus.DISBURSED,
            requested_amount="200.00",
            approved_amount="200.00",
            disbursed_amount="200.00",
        )

        url = reverse("manage:travel-grant-list", kwargs={"conference_slug": budgeted_conference.slug})
        resp = client_logged_in_super.get(url)

        assert resp.status_code == 200
        grant_budget = resp.context["grant_budget"]
        assert grant_budget["budget"] == 5000.0
        assert grant_budget["committed"] == 1000.0
        assert grant_budget["disbursed"] == 200.0
        assert grant_budget["remaining"] == 4000.0
        assert grant_budget["pct_committed"] == 20.0
        assert grant_budget["pct_disbursed"] == 4.0
        assert "chart_grant_budget_json" in resp.context

    def test_no_grant_budget_context_when_unset(self, client_logged_in_super, conference, regular_user):
        TravelGrant.objects.create(
            conference=conference,
            user=regular_user,
            status=TravelGrant.GrantStatus.SUBMITTED,
            requested_amount="100.00",
        )
        url = reverse("manage:travel-grant-list", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200
        assert "grant_budget" not in resp.context


# ---------------------------------------------------------------------------
# Expense Category CRUD views (views.py 3818-3987, forms.py 778-781)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExpenseCategoryViews:
    def test_list_view_annotates_budget_and_spent(self, client_logged_in_super, conference, expense_category):
        Expense.objects.create(
            conference=conference,
            category=expense_category,
            description="Deposit",
            amount="250.00",
            date=date(2027, 4, 1),
        )
        url = reverse("manage:expense-category-list", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200
        assert resp.context["active_nav"] == "expenses"
        assert resp.context["total_budget"] == Decimal("1000.00")
        assert resp.context["total_spent"] == 250

    def test_list_view_with_no_categories(self, client_logged_in_super, conference):
        url = reverse("manage:expense-category-list", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200
        assert resp.context["total_budget"] == 0
        assert resp.context["total_spent"] == 0

    def test_create_view_get(self, client_logged_in_super, conference):
        url = reverse("manage:expense-category-add", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200
        assert resp.context["active_nav"] == "expenses"
        assert resp.context["is_create"] is True

    def test_create_view_post(self, client_logged_in_super, conference):
        url = reverse("manage:expense-category-add", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.post(
            url,
            {
                "name": "Catering",
                "slug": "catering",
                "description": "Food and drink",
                "budget_amount": "2000.00",
                "order": 2,
            },
        )
        assert resp.status_code == 302
        assert resp.url == reverse("manage:expense-category-list", kwargs={"conference_slug": conference.slug})
        category = ExpenseCategory.objects.get(conference=conference, slug="catering")
        assert category.conference == conference

    def test_edit_view_get(self, client_logged_in_super, conference, expense_category):
        url = reverse(
            "manage:expense-category-edit",
            kwargs={"conference_slug": conference.slug, "pk": expense_category.pk},
        )
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200
        assert resp.context["active_nav"] == "expenses"
        assert resp.context["is_create"] is False

    def test_edit_view_post(self, client_logged_in_super, conference, expense_category):
        url = reverse(
            "manage:expense-category-edit",
            kwargs={"conference_slug": conference.slug, "pk": expense_category.pk},
        )
        resp = client_logged_in_super.post(
            url,
            {
                "name": "Venue & AV",
                "slug": "venue",
                "description": "",
                "budget_amount": "1200.00",
                "order": 1,
            },
        )
        assert resp.status_code == 302
        assert resp.url == reverse("manage:expense-category-list", kwargs={"conference_slug": conference.slug})
        expense_category.refresh_from_db()
        assert expense_category.name == "Venue & AV"


# ---------------------------------------------------------------------------
# Expense CRUD views (views.py 3891-3987, forms.py 778-781)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExpenseViews:
    def test_list_view_basic(self, client_logged_in_super, conference, expense_category):
        expense = Expense.objects.create(
            conference=conference,
            category=expense_category,
            description="Deposit",
            amount="500.00",
            date=date(2027, 4, 1),
        )
        url = reverse("manage:expense-list", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200
        assert resp.context["active_nav"] == "expenses"
        assert expense in resp.context["expenses"]
        assert resp.context["total_expenses"] == 500
        assert resp.context["expense_count"] == 1
        assert resp.context["current_category"] == ""

    def test_list_view_filtered_by_category(self, client_logged_in_super, conference, expense_category):
        other_category = ExpenseCategory.objects.create(
            conference=conference,
            name="Swag",
            slug="swag",
            order=2,
        )
        in_category = Expense.objects.create(
            conference=conference,
            category=expense_category,
            description="Deposit",
            amount="500.00",
            date=date(2027, 4, 1),
        )
        Expense.objects.create(
            conference=conference,
            category=other_category,
            description="T-shirts",
            amount="300.00",
            date=date(2027, 4, 2),
        )
        url = reverse("manage:expense-list", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url, {"category": expense_category.pk})
        assert resp.status_code == 200
        assert list(resp.context["expenses"]) == [in_category]
        assert resp.context["total_expenses"] == 500
        assert resp.context["expense_count"] == 1
        assert resp.context["current_category"] == str(expense_category.pk)

    def test_create_view_get_scopes_category_queryset(self, client_logged_in_super, conference, expense_category):
        """Covers ExpenseForm.__init__ scoping category choices to the conference (forms.py 778-781)."""
        other_conference = Conference.objects.create(
            name="Other Conf",
            slug="other-conf",
            start_date=date(2027, 6, 1),
            end_date=date(2027, 6, 3),
            timezone="UTC",
            is_active=True,
        )
        ExpenseCategory.objects.create(conference=other_conference, name="Other", slug="other", order=1)

        url = reverse("manage:expense-add", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200
        assert resp.context["active_nav"] == "expenses"
        assert resp.context["is_create"] is True
        category_qs = resp.context["form"].fields["category"].queryset
        assert list(category_qs) == [expense_category]

    def test_create_view_post(self, client_logged_in_super, conference, expense_category, superuser):
        url = reverse("manage:expense-add", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.post(
            url,
            {
                "category": expense_category.pk,
                "description": "Banner printing",
                "amount": "150.00",
                "vendor": "Print Co",
                "date": "2027-04-15",
                "receipt_reference": "",
                "notes": "",
            },
        )
        assert resp.status_code == 302
        assert resp.url == reverse("manage:expense-list", kwargs={"conference_slug": conference.slug})
        created = Expense.objects.get(conference=conference, description="Banner printing")
        assert created.created_by == superuser

    def test_edit_view_get(self, client_logged_in_super, conference, expense_category):
        expense = Expense.objects.create(
            conference=conference,
            category=expense_category,
            description="Deposit",
            amount="500.00",
            date=date(2027, 4, 1),
        )
        url = reverse(
            "manage:expense-edit",
            kwargs={"conference_slug": conference.slug, "pk": expense.pk},
        )
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200
        assert resp.context["active_nav"] == "expenses"
        assert resp.context["is_create"] is False

    def test_edit_view_post(self, client_logged_in_super, conference, expense_category):
        expense = Expense.objects.create(
            conference=conference,
            category=expense_category,
            description="Deposit",
            amount="500.00",
            date=date(2027, 4, 1),
        )
        url = reverse(
            "manage:expense-edit",
            kwargs={"conference_slug": conference.slug, "pk": expense.pk},
        )
        resp = client_logged_in_super.post(
            url,
            {
                "category": expense_category.pk,
                "description": "Deposit (revised)",
                "amount": "550.00",
                "vendor": "",
                "date": "2027-04-01",
                "receipt_reference": "",
                "notes": "",
            },
        )
        assert resp.status_code == 302
        assert resp.url == reverse("manage:expense-list", kwargs={"conference_slug": conference.slug})
        expense.refresh_from_db()
        assert expense.description == "Deposit (revised)"
        assert expense.amount == 550


# ---------------------------------------------------------------------------
# _decimal_to_float (views_analytics.py 45-56)
# ---------------------------------------------------------------------------


class TestDecimalToFloat:
    def test_converts_decimal(self):
        from decimal import Decimal

        assert _decimal_to_float(Decimal("12.50")) == 12.5

    def test_passes_through_non_decimal(self):
        """Non-Decimal values are returned unchanged (used as json.dumps default)."""
        assert _decimal_to_float("already-a-string") == "already-a-string"
        assert _decimal_to_float(42) == 42
