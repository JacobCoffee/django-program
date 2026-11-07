"""Coverage backfill tests for:

- ``conference/management/commands/setup_groups.py`` (the "missing
  permissions" warning branch)
- Simple ``__str__`` representations in ``conference/models.py``,
  ``pretalx/models.py``, and ``programs/models.py`` that had no direct
  coverage.
"""

from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from django_program.conference.models import Conference, Expense, ExpenseCategory
from django_program.pretalx.models import SessionRating, Talk
from django_program.programs.models import Survey, SurveyResponse

User = get_user_model()


# =============================================================================
# setup_groups command — missing permissions warning
# =============================================================================


@pytest.mark.django_db
def test_setup_groups_warns_when_permissions_are_missing():
    """When Permission.objects.filter returns no matches, every requested
    permission is reported as missing and the warning line is printed."""
    out = StringIO()

    with patch("django_program.conference.management.commands.setup_groups.Permission.objects.filter") as mock_filter:
        mock_filter.return_value = []
        call_command("setup_groups", stdout=out, verbosity=1)

    output = out.getvalue()
    assert "missing permissions" in output
    assert "Conference Organizer" in output


@pytest.mark.django_db
def test_setup_groups_silent_when_verbosity_zero():
    """Verbosity 0 suppresses the missing-permissions warning line entirely."""
    out = StringIO()

    with patch("django_program.conference.management.commands.setup_groups.Permission.objects.filter") as mock_filter:
        mock_filter.return_value = []
        call_command("setup_groups", stdout=out, verbosity=0)

    assert out.getvalue() == ""


@pytest.mark.django_db
def test_setup_groups_creates_groups_without_warning_when_all_matched():
    out = StringIO()
    call_command("setup_groups", stdout=out, verbosity=1)
    output = out.getvalue()

    assert "missing permissions" not in output
    assert "Done." in output


# =============================================================================
# conference/models.py — __str__ methods
# =============================================================================


@pytest.fixture
def conference(db):
    return Conference.objects.create(
        name="ModelCoverageCon",
        slug="model-coverage-con",
        start_date=date(2027, 8, 1),
        end_date=date(2027, 8, 3),
        timezone="UTC",
    )


@pytest.mark.unit
@pytest.mark.django_db
class TestExpenseCategoryStr:
    def test_str_includes_name_and_conference_slug(self, conference):
        category = ExpenseCategory.objects.create(
            conference=conference,
            name="Venue",
            slug="venue",
        )
        assert str(category) == f"Venue ({conference.slug})"


@pytest.mark.unit
@pytest.mark.django_db
class TestExpenseStr:
    def test_str_includes_description_and_amount(self, conference):
        category = ExpenseCategory.objects.create(
            conference=conference,
            name="Catering",
            slug="catering",
        )
        expense = Expense.objects.create(
            conference=conference,
            category=category,
            description="Lunch buffet",
            amount=Decimal("1250.50"),
            date=date(2027, 8, 2),
        )
        assert str(expense) == "Lunch buffet ($1250.50)"


# =============================================================================
# pretalx/models.py — SessionRating.__str__
# =============================================================================


@pytest.mark.unit
@pytest.mark.django_db
class TestSessionRatingStr:
    def test_str_includes_score_talk_and_user(self, conference):
        user = User.objects.create_user(
            username="raterperson",
            email="rater@example.com",
            password="testpass123",
        )
        talk = Talk.objects.create(
            conference=conference,
            pretalx_code="ABC123",
            title="A Great Talk",
        )
        rating = SessionRating.objects.create(
            conference=conference,
            talk=talk,
            user=user,
            score=4,
        )
        expected = f"Rating 4/5 for {talk} by {user}"
        assert str(rating) == expected


# =============================================================================
# programs/models.py — Survey.__str__ / SurveyResponse.__str__
# =============================================================================


@pytest.mark.unit
@pytest.mark.django_db
class TestSurveyStr:
    def test_str_includes_name_and_conference_slug(self, conference):
        survey = Survey.objects.create(
            conference=conference,
            name="Post-Event Feedback",
            slug="post-event-feedback",
        )
        assert str(survey) == f"Post-Event Feedback ({conference.slug})"


@pytest.mark.unit
@pytest.mark.django_db
class TestSurveyResponseStr:
    def test_str_includes_score_survey_and_user(self, conference):
        user = User.objects.create_user(
            username="surveyresponder",
            email="responder@example.com",
            password="testpass123",
        )
        survey = Survey.objects.create(
            conference=conference,
            name="NPS Survey",
            slug="nps-survey",
        )
        response = SurveyResponse.objects.create(
            survey=survey,
            user=user,
            score=9,
        )
        expected = f"Response 9 to {survey} by {user}"
        assert str(response) == expected
