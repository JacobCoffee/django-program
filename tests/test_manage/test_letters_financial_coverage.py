"""Coverage tests for the staff letter-review workflow and financial dashboard budget/PO branches."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from django_program.conference.models import Conference
from django_program.programs.models import TravelGrant
from django_program.registration.attendee import Attendee
from django_program.registration.letter import LetterRequest
from django_program.registration.models import TicketType
from django_program.registration.purchase_order import PurchaseOrderPayment
from django_program.registration.services.purchase_orders import create_purchase_order

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(username="lfadmin", password="password", email="lfadmin@test.com")


@pytest.fixture
def requester(db):
    return User.objects.create_user(
        username="requester", password="password", email="requester@test.com", first_name="Jane", last_name="Doe"
    )


@pytest.fixture
def client_logged_in_super(superuser):
    c = Client()
    c.login(username="lfadmin", password="password")
    return c


@pytest.fixture
def conference(db):
    return Conference.objects.create(
        name="LF Test Conf",
        slug="lf-test-conf",
        start_date=date(2027, 5, 1),
        end_date=date(2027, 5, 3),
        timezone="UTC",
        is_active=True,
        venue="Convention Center",
        address="123 Main St, Portland, OR",
    )


@pytest.fixture
def letter_request(conference, requester):
    return LetterRequest.objects.create(
        conference=conference,
        user=requester,
        passport_name="Jane Doe",
        passport_number="AB1234567",
        nationality="United States",
        date_of_birth=date(1990, 6, 15),
        travel_from=date(2027, 4, 28),
        travel_until=date(2027, 5, 5),
        destination_address="456 Hotel Ave, Portland, OR 97201",
        embassy_name="US Embassy Berlin",
        status=LetterRequest.Status.SUBMITTED,
    )


def _review_url(conference, lr):
    return reverse("manage:letter-review", kwargs={"conference_slug": conference.slug, "pk": lr.pk})


def _generate_url(conference, lr):
    return reverse("manage:letter-generate", kwargs={"conference_slug": conference.slug, "pk": lr.pk})


def _bulk_generate_url(conference):
    return reverse("manage:letter-bulk-generate", kwargs={"conference_slug": conference.slug})


def _send_url(conference, lr):
    return reverse("manage:letter-send", kwargs={"conference_slug": conference.slug, "pk": lr.pk})


def _list_url(conference):
    return reverse("manage:letter-list", kwargs={"conference_slug": conference.slug})


# ---------------------------------------------------------------------------
# LetterRequestReviewView: unrecognized action (views_letters.py 154-155)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLetterRequestReviewUnrecognizedAction:
    def test_unknown_action_shows_error_and_leaves_status_unchanged(
        self, client_logged_in_super, conference, letter_request
    ):
        resp = client_logged_in_super.post(_review_url(conference, letter_request), {"action": "teleport"})
        assert resp.status_code == 302
        assert resp.url == _review_url(conference, letter_request)
        letter_request.refresh_from_db()
        assert letter_request.status == LetterRequest.Status.SUBMITTED

        follow = client_logged_in_super.get(resp.url)
        messages = [str(m) for m in follow.context["messages"]]
        assert any("Invalid action or status transition." in m for m in messages)


# ---------------------------------------------------------------------------
# LetterRequestGenerateView: exception path (views_letters.py 225-227)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLetterRequestGenerateViewException:
    def test_generate_exception_shows_error_message(self, client_logged_in_super, conference, letter_request):
        letter_request.status = LetterRequest.Status.APPROVED
        letter_request.save(update_fields=["status"])

        with patch(
            "django_program.manage.views_letters.generate_invitation_letter",
            side_effect=RuntimeError("pdf engine exploded"),
        ):
            resp = client_logged_in_super.post(_generate_url(conference, letter_request))

        assert resp.status_code == 302
        letter_request.refresh_from_db()
        assert letter_request.status == LetterRequest.Status.APPROVED
        assert not letter_request.generated_pdf

        follow = client_logged_in_super.get(resp.url)
        messages = [str(m) for m in follow.context["messages"]]
        assert any("Failed to generate the invitation letter PDF." in m for m in messages)


# ---------------------------------------------------------------------------
# LetterRequestBulkGenerateView (views_letters.py 253-271)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLetterRequestBulkGenerateView:
    def _make_approved(self, conference, email, **overrides):
        user = User.objects.create_user(username=email, password="password", email=f"{email}@test.com")
        defaults = {
            "conference": conference,
            "user": user,
            "passport_name": "Traveler",
            "passport_number": "X1",
            "nationality": "Testland",
            "travel_from": date(2027, 4, 28),
            "travel_until": date(2027, 5, 5),
            "destination_address": "456 Hotel Ave",
            "status": LetterRequest.Status.APPROVED,
        }
        defaults.update(overrides)
        return LetterRequest.objects.create(**defaults)

    def test_bulk_generate_success_for_all_approved(self, client_logged_in_super, conference):
        lr = self._make_approved(conference, "approved1")
        resp = client_logged_in_super.post(_bulk_generate_url(conference))
        assert resp.status_code == 302
        assert resp.url == _list_url(conference)
        lr.refresh_from_db()
        assert lr.status == LetterRequest.Status.GENERATED
        assert lr.generated_pdf

        follow = client_logged_in_super.get(resp.url)
        messages = [str(m) for m in follow.context["messages"]]
        assert any("Generated 1 invitation letter(s)." in m for m in messages)

    def test_bulk_generate_reports_failures(self, client_logged_in_super, conference):
        self._make_approved(conference, "approved2")

        with patch(
            "django_program.manage.views_letters.generate_invitation_letter",
            side_effect=RuntimeError("boom"),
        ):
            resp = client_logged_in_super.post(_bulk_generate_url(conference))

        assert resp.status_code == 302
        follow = client_logged_in_super.get(resp.url)
        messages = [str(m) for m in follow.context["messages"]]
        assert any("Failed to generate 1 letter(s)." in m for m in messages)

    def test_bulk_generate_with_no_approved_requests(self, client_logged_in_super, conference):
        resp = client_logged_in_super.post(_bulk_generate_url(conference))
        assert resp.status_code == 302
        follow = client_logged_in_super.get(resp.url)
        messages = [str(m) for m in follow.context["messages"]]
        assert any("No approved letter requests to generate." in m for m in messages)


# ---------------------------------------------------------------------------
# LetterRequestSendView (views_letters.py 294-311)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLetterRequestSendView:
    def test_send_success(self, client_logged_in_super, conference, letter_request):
        letter_request.status = LetterRequest.Status.GENERATED
        letter_request.save(update_fields=["status"])

        with patch("django_program.manage.views_letters.send_invitation_letter") as mock_send:
            resp = client_logged_in_super.post(_send_url(conference, letter_request))

        mock_send.assert_called_once_with(letter_request)
        assert resp.status_code == 302
        follow = client_logged_in_super.get(resp.url)
        messages = [str(m) for m in follow.context["messages"]]
        assert any("Invitation letter sent successfully." in m for m in messages)

    def test_send_rejects_non_generated_status(self, client_logged_in_super, conference, letter_request):
        resp = client_logged_in_super.post(_send_url(conference, letter_request))
        assert resp.status_code == 302
        follow = client_logged_in_super.get(resp.url)
        messages = [str(m) for m in follow.context["messages"]]
        assert any("Only generated letters can be sent." in m for m in messages)

    def test_send_exception_shows_error(self, client_logged_in_super, conference, letter_request):
        letter_request.status = LetterRequest.Status.GENERATED
        letter_request.save(update_fields=["status"])

        with patch(
            "django_program.manage.views_letters.send_invitation_letter",
            side_effect=RuntimeError("smtp down"),
        ):
            resp = client_logged_in_super.post(_send_url(conference, letter_request))

        assert resp.status_code == 302
        follow = client_logged_in_super.get(resp.url)
        messages = [str(m) for m in follow.context["messages"]]
        assert any("Failed to send the invitation letter." in m for m in messages)


# ---------------------------------------------------------------------------
# FinancialDashboardView budget branches (views_financial.py 184-217, 403-404)
# ---------------------------------------------------------------------------


@pytest.fixture
def budgeted_conference(db):
    return Conference.objects.create(
        name="Budgeted Fin Conf",
        slug="budgeted-fin-conf",
        start_date=date(2027, 5, 1),
        end_date=date(2027, 5, 3),
        timezone="UTC",
        is_active=True,
        revenue_budget="10000.00",
        target_attendance=100,
        grant_budget="5000.00",
    )


def _dashboard_url(conference):
    return reverse("manage:financial-dashboard", kwargs={"conference_slug": conference.slug})


@pytest.mark.django_db
class TestFinancialDashboardBudgetBranches:
    def test_budget_fields_populate_context(self, client_logged_in_super, budgeted_conference, superuser):
        from django_program.registration.models import Order

        second_user = User.objects.create_user(username="second", password="password", email="second@test.com")

        Order.objects.create(
            conference=budgeted_conference,
            user=superuser,
            status=Order.Status.PAID,
            reference="ORD-FIN-BUDGET-1",
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

        resp = client_logged_in_super.get(_dashboard_url(budgeted_conference))
        assert resp.status_code == 200

        budget = resp.context["budget"]
        assert budget["revenue_target"] == Decimal("10000.00")
        assert budget["revenue_actual"] == Decimal("2500.00")
        assert budget["revenue_pct"] == 25.0
        assert budget["attendance_target"] == 100
        assert budget["attendance_actual"] == 1
        assert budget["attendance_pct"] == 1.0
        assert budget["grant_target"] == Decimal("5000.00")
        assert budget["grant_committed"] == Decimal("400.00")
        assert budget["grant_disbursed"] == Decimal("300.00")
        assert budget["grant_pct"] == 8.0
        assert "chart_budget_json" in resp.context

    def test_no_budget_fields_set_omits_budget_context(self, client_logged_in_super, conference):
        resp = client_logged_in_super.get(_dashboard_url(conference))
        assert resp.status_code == 200
        assert "budget" not in resp.context
        assert "chart_budget_json" not in resp.context


# ---------------------------------------------------------------------------
# FinancialDashboardView purchase order branches (views_financial.py 441, 492)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFinancialDashboardPurchaseOrderBreakdown:
    def test_purchase_order_status_and_payment_method_breakdowns(self, client_logged_in_super, conference, superuser):
        ticket_type = TicketType.objects.create(
            conference=conference,
            name="Corporate",
            slug="corporate",
            price=Decimal("250.00"),
        )
        po = create_purchase_order(
            conference=conference,
            organization_name="Acme Corp",
            contact_email="billing@acme.com",
            contact_name="Jane Doe",
            billing_address="123 Corporate Ave",
            line_items=[
                {
                    "description": "Corporate Ticket",
                    "quantity": 2,
                    "unit_price": Decimal("250.00"),
                    "ticket_type": ticket_type,
                },
            ],
            notes="Test PO",
            created_by=superuser,
        )
        PurchaseOrderPayment.objects.create(
            purchase_order=po,
            amount=Decimal("500.00"),
            method=PurchaseOrderPayment.Method.WIRE,
            payment_date=date(2027, 4, 1),
            entered_by=superuser,
        )

        resp = client_logged_in_super.get(_dashboard_url(conference))
        assert resp.status_code == 200

        po_by_status = resp.context["po_by_status"]
        assert po_by_status[po.status]["count"] == 1
        assert po_by_status[po.status]["total"] == po.total

        po_payments_by_method = resp.context["po_payments_by_method"]
        assert po_payments_by_method[PurchaseOrderPayment.Method.WIRE]["count"] == 1
        assert po_payments_by_method[PurchaseOrderPayment.Method.WIRE]["total"] == Decimal("500.00")
        assert resp.context["po_collected"] == Decimal("500.00")
