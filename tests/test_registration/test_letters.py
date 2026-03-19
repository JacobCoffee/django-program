"""Tests for visa invitation letter requests — models, forms, services, and views."""

from datetime import date
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.db import IntegrityError
from django.test import Client
from django.urls import reverse

from django_program.conference.models import Conference
from django_program.registration.forms import LetterRequestForm
from django_program.registration.letter import LetterRequest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conference(db):
    return Conference.objects.create(
        name="TestCon 2027",
        slug="testcon",
        start_date=date(2027, 5, 1),
        end_date=date(2027, 5, 3),
        timezone="UTC",
        is_active=True,
        venue="Convention Center",
        address="123 Main St, Portland, OR",
    )


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="attendee",
        password="password",
        email="attendee@test.com",
        first_name="Jane",
        last_name="Doe",
    )


@pytest.fixture
def other_user(db):
    return User.objects.create_user(username="other", password="password", email="other@test.com")


@pytest.fixture
def staff_user(db):
    return User.objects.create_superuser(username="admin", password="password", email="admin@test.com")


@pytest.fixture
def letter_data():
    return {
        "passport_name": "Jane Doe",
        "passport_number": "AB1234567",
        "nationality": "United States",
        "date_of_birth": "1990-06-15",
        "travel_from": "2027-04-28",
        "travel_until": "2027-05-05",
        "destination_address": "456 Hotel Ave, Portland, OR 97201",
        "embassy_name": "US Embassy Berlin",
    }


@pytest.fixture
def letter_request(conference, user):
    return LetterRequest.objects.create(
        conference=conference,
        user=user,
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


@pytest.fixture
def client_logged_in(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def client_other_user(other_user):
    c = Client()
    c.force_login(other_user)
    return c


@pytest.fixture
def client_staff(staff_user):
    c = Client()
    c.force_login(staff_user)
    return c


@pytest.fixture
def anon_client():
    return Client()


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.django_db
class TestLetterRequestModel:
    """Tests for the LetterRequest model."""

    def test_create_with_all_required_fields(self, conference, user):
        lr = LetterRequest.objects.create(
            conference=conference,
            user=user,
            passport_name="John Smith",
            passport_number="XY9876543",
            nationality="Germany",
            travel_from=date(2027, 4, 28),
            travel_until=date(2027, 5, 5),
            destination_address="456 Hotel Ave",
        )
        assert lr.pk is not None
        assert lr.status == LetterRequest.Status.SUBMITTED
        assert lr.created_at is not None

    def test_str_representation(self, letter_request, conference):
        result = str(letter_request)
        assert "Jane Doe" in result
        assert str(conference) in result
        assert "Submitted" in result

    def test_status_choices_exist(self):
        values = LetterRequest.Status.values
        assert "submitted" in values
        assert "under_review" in values
        assert "approved" in values
        assert "generated" in values
        assert "sent" in values
        assert "rejected" in values

    def test_transition_submitted_to_under_review(self, letter_request):
        letter_request.transition_to(LetterRequest.Status.UNDER_REVIEW)
        assert letter_request.status == LetterRequest.Status.UNDER_REVIEW

    def test_transition_submitted_to_rejected(self, letter_request):
        letter_request.transition_to(LetterRequest.Status.REJECTED)
        assert letter_request.status == LetterRequest.Status.REJECTED

    def test_transition_under_review_to_approved(self, letter_request):
        letter_request.status = LetterRequest.Status.UNDER_REVIEW
        letter_request.transition_to(LetterRequest.Status.APPROVED)
        assert letter_request.status == LetterRequest.Status.APPROVED

    def test_transition_under_review_to_rejected(self, letter_request):
        letter_request.status = LetterRequest.Status.UNDER_REVIEW
        letter_request.transition_to(LetterRequest.Status.REJECTED)
        assert letter_request.status == LetterRequest.Status.REJECTED

    def test_transition_approved_to_generated(self, letter_request):
        letter_request.status = LetterRequest.Status.APPROVED
        letter_request.transition_to(LetterRequest.Status.GENERATED)
        assert letter_request.status == LetterRequest.Status.GENERATED

    def test_transition_generated_to_sent(self, letter_request):
        letter_request.status = LetterRequest.Status.GENERATED
        letter_request.transition_to(LetterRequest.Status.SENT)
        assert letter_request.status == LetterRequest.Status.SENT

    def test_transition_submitted_to_approved(self, letter_request):
        letter_request.transition_to(LetterRequest.Status.APPROVED)
        assert letter_request.status == LetterRequest.Status.APPROVED

    def test_transition_invalid_submitted_to_generated_raises(self, letter_request):
        with pytest.raises(ValueError, match="Cannot transition"):
            letter_request.transition_to(LetterRequest.Status.GENERATED)

    def test_transition_invalid_approved_to_sent_raises(self, letter_request):
        letter_request.status = LetterRequest.Status.APPROVED
        with pytest.raises(ValueError, match="Cannot transition"):
            letter_request.transition_to(LetterRequest.Status.SENT)

    def test_transition_from_sent_raises(self, letter_request):
        letter_request.status = LetterRequest.Status.SENT
        with pytest.raises(ValueError, match="Cannot transition"):
            letter_request.transition_to(LetterRequest.Status.SUBMITTED)

    def test_transition_from_rejected_raises(self, letter_request):
        letter_request.status = LetterRequest.Status.REJECTED
        with pytest.raises(ValueError, match="Cannot transition"):
            letter_request.transition_to(LetterRequest.Status.SUBMITTED)

    def test_unique_together_user_conference(self, conference, user, letter_request):
        with pytest.raises(IntegrityError):
            LetterRequest.objects.create(
                conference=conference,
                user=user,
                passport_name="Duplicate Request",
                passport_number="ZZ0000000",
                nationality="France",
                travel_from=date(2027, 4, 28),
                travel_until=date(2027, 5, 5),
                destination_address="Some address",
            )

    def test_default_ordering(self, conference, user, other_user):
        lr1 = LetterRequest.objects.create(
            conference=conference,
            user=user,
            passport_name="First",
            passport_number="A1",
            nationality="US",
            travel_from=date(2027, 4, 28),
            travel_until=date(2027, 5, 5),
            destination_address="Addr 1",
        )
        lr2 = LetterRequest.objects.create(
            conference=conference,
            user=other_user,
            passport_name="Second",
            passport_number="A2",
            nationality="US",
            travel_from=date(2027, 4, 28),
            travel_until=date(2027, 5, 5),
            destination_address="Addr 2",
        )
        results = list(LetterRequest.objects.filter(conference=conference))
        assert results[0] == lr2
        assert results[1] == lr1


# ---------------------------------------------------------------------------
# Form tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.django_db
class TestLetterRequestForm:
    """Tests for the LetterRequestForm."""

    def test_valid_data(self, letter_data):
        form = LetterRequestForm(data=letter_data)
        assert form.is_valid(), form.errors

    def test_travel_from_must_be_before_travel_until(self, letter_data):
        letter_data["travel_from"] = "2027-05-10"
        letter_data["travel_until"] = "2027-05-05"
        form = LetterRequestForm(data=letter_data)
        assert not form.is_valid()
        assert "__all__" in form.errors

    def test_travel_same_dates_invalid(self, letter_data):
        letter_data["travel_from"] = "2027-05-01"
        letter_data["travel_until"] = "2027-05-01"
        form = LetterRequestForm(data=letter_data)
        assert not form.is_valid()

    def test_missing_required_passport_name(self, letter_data):
        del letter_data["passport_name"]
        form = LetterRequestForm(data=letter_data)
        assert not form.is_valid()
        assert "passport_name" in form.errors

    def test_missing_required_passport_number(self, letter_data):
        del letter_data["passport_number"]
        form = LetterRequestForm(data=letter_data)
        assert not form.is_valid()
        assert "passport_number" in form.errors

    def test_missing_required_nationality(self, letter_data):
        del letter_data["nationality"]
        form = LetterRequestForm(data=letter_data)
        assert not form.is_valid()
        assert "nationality" in form.errors

    def test_missing_required_travel_dates(self, letter_data):
        del letter_data["travel_from"]
        del letter_data["travel_until"]
        form = LetterRequestForm(data=letter_data)
        assert not form.is_valid()
        assert "travel_from" in form.errors
        assert "travel_until" in form.errors

    def test_missing_required_destination_address(self, letter_data):
        del letter_data["destination_address"]
        form = LetterRequestForm(data=letter_data)
        assert not form.is_valid()
        assert "destination_address" in form.errors

    def test_optional_fields_can_be_omitted(self, letter_data):
        del letter_data["date_of_birth"]
        del letter_data["embassy_name"]
        form = LetterRequestForm(data=letter_data)
        assert form.is_valid(), form.errors


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.django_db
class TestGenerateInvitationLetter:
    """Tests for the generate_invitation_letter service."""

    def test_produces_pdf_bytes(self, letter_request):
        from django_program.registration.services.letters import generate_invitation_letter

        letter_request.status = LetterRequest.Status.APPROVED
        letter_request.save(update_fields=["status"])

        pdf_bytes = generate_invitation_letter(letter_request)

        assert isinstance(pdf_bytes, bytes)
        assert pdf_bytes[:5] == b"%PDF-"

    def test_updates_status_to_generated(self, letter_request):
        from django_program.registration.services.letters import generate_invitation_letter

        letter_request.status = LetterRequest.Status.APPROVED
        letter_request.save(update_fields=["status"])

        generate_invitation_letter(letter_request)

        letter_request.refresh_from_db()
        assert letter_request.status == LetterRequest.Status.GENERATED

    def test_saves_pdf_to_generated_pdf_field(self, letter_request):
        from django_program.registration.services.letters import generate_invitation_letter

        letter_request.status = LetterRequest.Status.APPROVED
        letter_request.save(update_fields=["status"])

        generate_invitation_letter(letter_request)

        letter_request.refresh_from_db()
        assert letter_request.generated_pdf
        assert letter_request.generated_pdf.name.endswith(".pdf")

    def test_pdf_without_optional_fields(self, conference, other_user):
        from django_program.registration.services.letters import generate_invitation_letter

        lr = LetterRequest.objects.create(
            conference=conference,
            user=other_user,
            passport_name="No Optional",
            passport_number="XX000",
            nationality="Canada",
            travel_from=date(2027, 4, 28),
            travel_until=date(2027, 5, 5),
            destination_address="Some hotel",
            status=LetterRequest.Status.APPROVED,
        )
        pdf_bytes = generate_invitation_letter(lr)
        assert pdf_bytes[:5] == b"%PDF-"


@pytest.mark.unit
@pytest.mark.django_db
class TestSendInvitationLetter:
    """Tests for the send_invitation_letter service."""

    def test_updates_status_to_sent(self, letter_request):
        from django_program.registration.services.letters import send_invitation_letter

        letter_request.status = LetterRequest.Status.GENERATED
        letter_request.save(update_fields=["status"])

        send_invitation_letter(letter_request)

        letter_request.refresh_from_db()
        assert letter_request.status == LetterRequest.Status.SENT

    def test_sets_sent_at_timestamp(self, letter_request):
        from django_program.registration.services.letters import send_invitation_letter

        letter_request.status = LetterRequest.Status.GENERATED
        letter_request.save(update_fields=["status"])

        assert letter_request.sent_at is None
        send_invitation_letter(letter_request)

        letter_request.refresh_from_db()
        assert letter_request.sent_at is not None

    def test_raises_on_invalid_transition(self, letter_request):
        from django_program.registration.services.letters import send_invitation_letter

        with pytest.raises(ValueError, match="Cannot transition"):
            send_invitation_letter(letter_request)


# ---------------------------------------------------------------------------
# Helper: patch the feature check so visa_letters doesn't raise ValueError
# ---------------------------------------------------------------------------


def _mock_feature_enabled(feature, conference=None):
    """Always return True for feature checks during view tests."""
    return True


# ---------------------------------------------------------------------------
# Registration view tests (attendee-facing)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.django_db
class TestLetterRequestCreateView:
    """Tests for the LetterRequestCreateView."""

    def _url(self, conference):
        return reverse("registration:letter-request", kwargs={"conference_slug": conference.slug})

    @patch("django_program.features.is_feature_enabled", side_effect=_mock_feature_enabled)
    def test_get_renders_form(self, mock_feature, client_logged_in, conference):
        resp = client_logged_in.get(self._url(conference))
        assert resp.status_code == 200
        assert "form" in resp.context

    @patch("django_program.features.is_feature_enabled", side_effect=_mock_feature_enabled)
    def test_get_prefills_passport_name(self, mock_feature, client_logged_in, conference):
        resp = client_logged_in.get(self._url(conference))
        form = resp.context["form"]
        assert form.initial.get("passport_name") == "Jane Doe"

    @patch("django_program.features.is_feature_enabled", side_effect=_mock_feature_enabled)
    def test_post_creates_letter_request(self, mock_feature, client_logged_in, conference, user, letter_data):
        resp = client_logged_in.post(self._url(conference), letter_data)
        assert resp.status_code == 302
        assert LetterRequest.objects.filter(user=user, conference=conference).exists()
        lr = LetterRequest.objects.get(user=user, conference=conference)
        assert lr.passport_name == "Jane Doe"
        assert lr.status == LetterRequest.Status.SUBMITTED

    @patch("django_program.features.is_feature_enabled", side_effect=_mock_feature_enabled)
    def test_post_invalid_data_re_renders_form(self, mock_feature, client_logged_in, conference):
        resp = client_logged_in.post(self._url(conference), {"passport_name": ""})
        assert resp.status_code == 200
        assert "form" in resp.context
        assert resp.context["form"].errors

    @patch("django_program.features.is_feature_enabled", side_effect=_mock_feature_enabled)
    def test_redirects_if_already_exists(self, mock_feature, client_logged_in, conference, letter_request):
        resp = client_logged_in.get(self._url(conference))
        assert resp.status_code == 302
        detail_url = reverse("registration:letter-request-detail", args=[conference.slug])
        assert resp.url == detail_url

    @patch("django_program.features.is_feature_enabled", side_effect=_mock_feature_enabled)
    def test_post_redirects_if_already_exists(
        self, mock_feature, client_logged_in, conference, letter_request, letter_data
    ):
        resp = client_logged_in.post(self._url(conference), letter_data)
        assert resp.status_code == 302

    @patch("django_program.features.is_feature_enabled", side_effect=_mock_feature_enabled)
    def test_anonymous_redirects_to_login(self, mock_feature, anon_client, conference):
        resp = anon_client.get(self._url(conference))
        assert resp.status_code == 302
        assert "login" in resp.url


@pytest.mark.integration
@pytest.mark.django_db
class TestLetterRequestDetailView:
    """Tests for the LetterRequestDetailView."""

    def _url(self, conference):
        return reverse("registration:letter-request-detail", kwargs={"conference_slug": conference.slug})

    @patch("django_program.features.is_feature_enabled", side_effect=_mock_feature_enabled)
    def test_shows_request_for_owner(self, mock_feature, client_logged_in, conference, letter_request):
        resp = client_logged_in.get(self._url(conference))
        assert resp.status_code == 200
        assert resp.context["letter_request"] == letter_request

    @patch("django_program.features.is_feature_enabled", side_effect=_mock_feature_enabled)
    def test_returns_404_for_non_owner(self, mock_feature, client_other_user, conference, letter_request):
        resp = client_other_user.get(self._url(conference))
        assert resp.status_code == 404

    @patch("django_program.features.is_feature_enabled", side_effect=_mock_feature_enabled)
    def test_returns_404_when_no_request_exists(self, mock_feature, client_logged_in, conference):
        resp = client_logged_in.get(self._url(conference))
        assert resp.status_code == 404

    @patch("django_program.features.is_feature_enabled", side_effect=_mock_feature_enabled)
    def test_pdf_available_when_generated(self, mock_feature, client_logged_in, conference, letter_request):
        letter_request.status = LetterRequest.Status.GENERATED
        letter_request.generated_pdf.save("test.pdf", ContentFile(b"%PDF-fake"), save=True)
        resp = client_logged_in.get(self._url(conference))
        assert resp.status_code == 200
        assert resp.context["pdf_available"]

    @patch("django_program.features.is_feature_enabled", side_effect=_mock_feature_enabled)
    def test_pdf_not_available_when_submitted(self, mock_feature, client_logged_in, conference, letter_request):
        resp = client_logged_in.get(self._url(conference))
        assert resp.status_code == 200
        assert not resp.context["pdf_available"]


# ---------------------------------------------------------------------------
# Manage view tests (staff-facing)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.django_db
class TestLetterRequestListView:
    """Tests for the manage LetterRequestListView."""

    def _url(self, conference):
        return reverse("manage:letter-list", kwargs={"conference_slug": conference.slug})

    def test_staff_can_view_list(self, client_staff, conference, letter_request):
        resp = client_staff.get(self._url(conference))
        assert resp.status_code == 200
        assert letter_request in resp.context["letter_requests"]

    def test_non_staff_gets_403(self, client_logged_in, conference):
        resp = client_logged_in.get(self._url(conference))
        assert resp.status_code == 403

    def test_anonymous_redirects(self, anon_client, conference):
        resp = anon_client.get(self._url(conference))
        assert resp.status_code == 302
        assert "login" in resp.url

    def test_filter_by_status(self, client_staff, conference, letter_request):
        resp = client_staff.get(self._url(conference), {"status": "submitted"})
        assert resp.status_code == 200
        assert letter_request in resp.context["letter_requests"]

    def test_filter_excludes_non_matching(self, client_staff, conference, letter_request):
        resp = client_staff.get(self._url(conference), {"status": "approved"})
        assert resp.status_code == 200
        assert letter_request not in resp.context["letter_requests"]

    def test_status_counts_in_context(self, client_staff, conference, letter_request):
        resp = client_staff.get(self._url(conference))
        assert "status_counts" in resp.context
        assert resp.context["status_counts"]["submitted"] == 1
        assert resp.context["total_count"] == 1


@pytest.mark.integration
@pytest.mark.django_db
class TestLetterRequestReviewView:
    """Tests for the manage LetterRequestReviewView."""

    def _url(self, conference, lr):
        return reverse("manage:letter-review", kwargs={"conference_slug": conference.slug, "pk": lr.pk})

    def test_get_renders_review_page(self, client_staff, conference, letter_request):
        resp = client_staff.get(self._url(conference, letter_request))
        assert resp.status_code == 200
        assert resp.context["letter_request"] == letter_request

    def test_approve_action(self, client_staff, conference, letter_request):
        resp = client_staff.post(self._url(conference, letter_request), {"action": "approve"})
        assert resp.status_code == 302
        letter_request.refresh_from_db()
        assert letter_request.status == LetterRequest.Status.APPROVED
        assert letter_request.reviewed_by is not None
        assert letter_request.reviewed_at is not None

    def test_reject_action_with_reason(self, client_staff, conference, letter_request):
        resp = client_staff.post(
            self._url(conference, letter_request),
            {"action": "reject", "rejection_reason": "Incomplete passport details"},
        )
        assert resp.status_code == 302
        letter_request.refresh_from_db()
        assert letter_request.status == LetterRequest.Status.REJECTED
        assert letter_request.rejection_reason == "Incomplete passport details"
        assert letter_request.reviewed_by is not None

    def test_reject_without_reason_shows_error(self, client_staff, conference, letter_request):
        resp = client_staff.post(
            self._url(conference, letter_request),
            {"action": "reject", "rejection_reason": ""},
        )
        assert resp.status_code == 302
        letter_request.refresh_from_db()
        assert letter_request.status == LetterRequest.Status.SUBMITTED

    def test_under_review_action(self, client_staff, conference, letter_request):
        resp = client_staff.post(self._url(conference, letter_request), {"action": "under_review"})
        assert resp.status_code == 302
        letter_request.refresh_from_db()
        assert letter_request.status == LetterRequest.Status.UNDER_REVIEW

    def test_invalid_action_shows_error(self, client_staff, conference, letter_request):
        letter_request.status = LetterRequest.Status.GENERATED
        letter_request.save(update_fields=["status"])
        resp = client_staff.post(self._url(conference, letter_request), {"action": "approve"})
        assert resp.status_code == 302
        letter_request.refresh_from_db()
        assert letter_request.status == LetterRequest.Status.GENERATED


@pytest.mark.integration
@pytest.mark.django_db
class TestLetterRequestGenerateView:
    """Tests for the manage LetterRequestGenerateView."""

    def _url(self, conference, lr):
        return reverse("manage:letter-generate", kwargs={"conference_slug": conference.slug, "pk": lr.pk})

    def test_generates_pdf_for_approved_request(self, client_staff, conference, letter_request):
        letter_request.status = LetterRequest.Status.APPROVED
        letter_request.save(update_fields=["status"])

        resp = client_staff.post(self._url(conference, letter_request))
        assert resp.status_code == 302

        letter_request.refresh_from_db()
        assert letter_request.status == LetterRequest.Status.GENERATED
        assert letter_request.generated_pdf

    def test_rejects_non_approved_request(self, client_staff, conference, letter_request):
        resp = client_staff.post(self._url(conference, letter_request))
        assert resp.status_code == 302
        letter_request.refresh_from_db()
        assert letter_request.status == LetterRequest.Status.SUBMITTED

    def test_non_staff_gets_403(self, client_logged_in, conference, letter_request):
        letter_request.status = LetterRequest.Status.APPROVED
        letter_request.save(update_fields=["status"])
        resp = client_logged_in.post(self._url(conference, letter_request))
        assert resp.status_code == 403


@pytest.mark.integration
@pytest.mark.django_db
class TestLetterRequestDownloadView:
    """Tests for the manage LetterRequestDownloadView."""

    def _url(self, conference, lr):
        return reverse("manage:letter-download", kwargs={"conference_slug": conference.slug, "pk": lr.pk})

    def test_serves_pdf_when_available(self, client_staff, conference, letter_request):
        pdf_content = b"%PDF-1.4 fake pdf content"
        letter_request.generated_pdf.save("test.pdf", ContentFile(pdf_content), save=True)

        resp = client_staff.get(self._url(conference, letter_request))
        assert resp.status_code == 200
        assert resp["Content-Type"] == "application/pdf"
        assert "attachment" in resp["Content-Disposition"]
        assert b"%PDF-" in resp.content

    def test_redirects_when_no_pdf(self, client_staff, conference, letter_request):
        resp = client_staff.get(self._url(conference, letter_request))
        assert resp.status_code == 302

    def test_non_staff_gets_403(self, client_logged_in, conference, letter_request):
        letter_request.generated_pdf.save("test.pdf", ContentFile(b"%PDF-fake"), save=True)
        resp = client_logged_in.get(self._url(conference, letter_request))
        assert resp.status_code == 403
