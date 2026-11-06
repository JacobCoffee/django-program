"""Coverage tests for django_program.manage.reports_analytics.

Exercises report functions whose non-empty / data-bearing branches are not
hit by the existing test_analytics_reports.py suite: expense summary,
event ROI, registration attribution, session rating analytics, NPS score,
attendee lifetime value, sponsor renewal rate, speaker return rate, and the
int-valued zero-division branch in year-over-year growth.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import User

from django_program.conference.models import Conference, Expense, ExpenseCategory
from django_program.manage.reports_analytics import (
    get_attendee_lifetime_value,
    get_event_roi,
    get_expense_summary,
    get_nps_score,
    get_registration_attribution,
    get_session_rating_analytics,
    get_speaker_return_rate,
    get_sponsor_renewal_rate,
    get_yoy_growth,
)
from django_program.pretalx.models import SessionRating, Speaker, Talk
from django_program.programs.models import Survey, SurveyResponse
from django_program.registration.models import Attendee, Order
from django_program.sponsors.models import Sponsor, SponsorLevel

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
def user1(db):
    return User.objects.create_user(username="u1", password="p", email="u1@test.com")


@pytest.fixture
def user2(db):
    return User.objects.create_user(username="u2", password="p", email="u2@test.com")


# ---------------------------------------------------------------------------
# get_expense_summary
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExpenseSummary:
    def test_categories_with_and_without_budget(self, conference):
        budgeted = ExpenseCategory.objects.create(
            conference=conference,
            name="Venue",
            slug="venue",
            budget_amount=Decimal("1000.00"),
        )
        unbudgeted = ExpenseCategory.objects.create(
            conference=conference,
            name="Swag",
            slug="swag",
        )
        Expense.objects.create(
            conference=conference,
            category=budgeted,
            description="Hall rental",
            amount=Decimal("800.00"),
            date=date(2027, 4, 1),
        )
        Expense.objects.create(
            conference=conference,
            category=unbudgeted,
            description="T-shirts",
            amount=Decimal("200.00"),
            date=date(2027, 4, 2),
        )

        result = get_expense_summary(conference)

        assert result["total_expenses"] == Decimal("1000.00")
        assert result["total_budget"] == Decimal("1000.00")
        assert result["budget_variance"] == Decimal("0.00")
        assert result["expense_count"] == 2
        by_name = {row["name"]: row for row in result["by_category"]}
        assert by_name["Venue"]["budget"] == Decimal("1000.00")
        assert by_name["Venue"]["variance"] == Decimal("200.00")
        assert by_name["Swag"]["budget"] is None
        assert by_name["Swag"]["variance"] is None


# ---------------------------------------------------------------------------
# get_event_roi
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventROI:
    def test_computes_profit_and_per_attendee_metrics(self, conference, user1, user2):
        Order.objects.create(
            conference=conference,
            user=user1,
            status=Order.Status.PAID,
            total=Decimal("1000.00"),
            subtotal=Decimal("1000.00"),
            reference="ORD-ROI-1",
        )
        category = ExpenseCategory.objects.create(conference=conference, name="AV", slug="av")
        Expense.objects.create(
            conference=conference,
            category=category,
            description="Projector",
            amount=Decimal("500.00"),
            date=date(2027, 4, 1),
        )
        Attendee.objects.create(conference=conference, user=user1)
        Attendee.objects.create(conference=conference, user=user2)

        result = get_event_roi(conference)

        assert result["total_revenue"] == Decimal("1000.00")
        assert result["total_expenses"] == Decimal("500.00")
        assert result["gross_profit"] == Decimal("500.00")
        assert result["gross_margin_pct"] == Decimal("50.00")
        assert result["net_profit"] == Decimal("500.00")
        assert result["roi_pct"] == Decimal("100.00")
        assert result["cost_per_attendee"] == Decimal("250.00")
        assert result["revenue_per_attendee"] == Decimal("500.00")


# ---------------------------------------------------------------------------
# get_registration_attribution
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRegistrationAttribution:
    def test_groups_paid_orders_by_utm_fields(self, conference, user1, user2):
        Order.objects.create(
            conference=conference,
            user=user1,
            status=Order.Status.PAID,
            total=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            reference="ORD-ATTR-1",
            utm_source="newsletter",
            utm_medium="email",
            utm_campaign="launch",
        )
        Order.objects.create(
            conference=conference,
            user=user2,
            status=Order.Status.PAID,
            total=Decimal("50.00"),
            subtotal=Decimal("50.00"),
            reference="ORD-ATTR-2",
        )

        result = get_registration_attribution(conference)

        assert result["total_attributed"] == 1
        assert result["total_unattributed"] == 1
        assert result["by_source"] == [{"name": "newsletter", "count": 1, "revenue": Decimal("100.00")}]
        assert result["by_medium"] == [{"name": "email", "count": 1, "revenue": Decimal("100.00")}]
        assert result["by_campaign"] == [{"name": "launch", "count": 1, "revenue": Decimal("100.00")}]


# ---------------------------------------------------------------------------
# get_session_rating_analytics
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSessionRatingAnalytics:
    def test_computes_distribution_rankings_and_track_breakdown(self, conference, user1, user2):
        rater3 = User.objects.create_user(username="u3", password="p", email="u3@test.com")
        talk = Talk.objects.create(
            conference=conference,
            pretalx_code="T1",
            title="Great Talk",
            track="Web",
        )

        SessionRating.objects.create(conference=conference, talk=talk, user=user1, score=5)
        SessionRating.objects.create(conference=conference, talk=talk, user=user2, score=4)
        SessionRating.objects.create(conference=conference, talk=talk, user=rater3, score=3)

        result = get_session_rating_analytics(conference)

        assert result["total_ratings"] == 3
        assert result["average_score"] == Decimal(4)
        assert result["score_distribution"][5] == 1
        assert result["score_distribution"][4] == 1
        assert result["score_distribution"][3] == 1
        assert len(result["top_sessions"]) == 1
        assert result["top_sessions"][0]["talk_title"] == "Great Talk"
        assert len(result["bottom_sessions"]) == 1
        assert len(result["by_track"]) == 1
        assert result["by_track"][0]["track"] == "Web"


# ---------------------------------------------------------------------------
# get_nps_score
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestNPSScore:
    def test_explicit_slug_with_responses_computes_full_metrics(self, conference, user1, user2):
        rater3 = User.objects.create_user(username="u3nps", password="p", email="u3nps@test.com")
        rater4 = User.objects.create_user(username="u4nps", password="p", email="u4nps@test.com")
        survey = Survey.objects.create(
            conference=conference,
            name="Post Event",
            slug="post-event",
            survey_type=Survey.SurveyType.SATISFACTION,
        )
        SurveyResponse.objects.create(survey=survey, user=user1, score=9)
        SurveyResponse.objects.create(survey=survey, user=user2, score=9)
        SurveyResponse.objects.create(survey=survey, user=rater3, score=7)
        SurveyResponse.objects.create(survey=survey, user=rater4, score=3)
        Attendee.objects.create(conference=conference, user=user1)
        Attendee.objects.create(conference=conference, user=user2)

        result = get_nps_score(conference, survey_slug="post-event")

        assert result["total_responses"] == 4
        assert result["promoters"] == 2
        assert result["passives"] == 1
        assert result["detractors"] == 1
        assert result["nps_score"] == 25
        assert result["response_rate"] == Decimal("200.00")

    def test_no_matching_survey_returns_empty(self, conference):
        result = get_nps_score(conference)

        assert result["nps_score"] == 0
        assert result["total_responses"] == 0

    def test_default_lookup_survey_with_no_responses_returns_empty(self, conference):
        Survey.objects.create(
            conference=conference,
            name="NPS Survey",
            slug="nps-survey",
            survey_type=Survey.SurveyType.NPS,
        )

        result = get_nps_score(conference)

        assert result["total_responses"] == 0
        assert result["nps_score"] == 0


# ---------------------------------------------------------------------------
# get_attendee_lifetime_value
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAttendeeLifetimeValue:
    def test_computes_ltv_across_conferences(self, conference, previous_conference, user1, user2):
        Order.objects.create(
            conference=conference,
            user=user1,
            status=Order.Status.PAID,
            total=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            reference="ORD-LTV-1",
        )
        Order.objects.create(
            conference=previous_conference,
            user=user1,
            status=Order.Status.PAID,
            total=Decimal("50.00"),
            subtotal=Decimal("50.00"),
            reference="ORD-LTV-2",
        )
        Order.objects.create(
            conference=conference,
            user=user2,
            status=Order.Status.PAID,
            total=Decimal("200.00"),
            subtotal=Decimal("200.00"),
            reference="ORD-LTV-3",
        )

        result = get_attendee_lifetime_value(conference)

        assert result["total_users_with_orders"] == 2
        assert result["max_ltv"] == Decimal("200.00")
        assert result["min_ltv"] == Decimal("150.00")
        assert result["avg_ltv"] == Decimal("175.00")
        usernames = {row["username"] for row in result["top_users"]}
        assert usernames == {"u1", "u2"}


# ---------------------------------------------------------------------------
# get_sponsor_renewal_rate
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSponsorRenewalRate:
    def test_by_level_breakdown_with_returning_and_new_sponsors(self, conference, previous_conference):
        prev_level = SponsorLevel.objects.create(conference=previous_conference, name="Gold", cost=Decimal("5000.00"))
        Sponsor.objects.create(conference=previous_conference, level=prev_level, name="Acme Corp")

        level = SponsorLevel.objects.create(conference=conference, name="Gold", cost=Decimal("5000.00"))
        Sponsor.objects.create(conference=conference, level=level, name="Acme Corp")
        Sponsor.objects.create(conference=conference, level=level, name="New Sponsor Inc")

        result = get_sponsor_renewal_rate(conference)

        assert result["current_sponsor_count"] == 2
        assert result["returning_count"] == 1
        assert result["new_count"] == 1
        level_row = result["by_level"][0]
        assert level_row["level_name"] == "Gold"
        assert level_row["total"] == 2
        assert level_row["returning"] == 1
        assert level_row["new"] == 1


# ---------------------------------------------------------------------------
# get_speaker_return_rate
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSpeakerReturnRate:
    def test_matches_returning_speakers_by_user_and_by_name_email(self, conference, previous_conference, user1):
        Speaker.objects.create(
            conference=previous_conference,
            pretalx_code="PS1",
            name="Returning By User",
            user=user1,
        )
        Speaker.objects.create(
            conference=previous_conference,
            pretalx_code="PS2",
            name="Returning By Name",
            email="byname@test.com",
        )

        Speaker.objects.create(
            conference=conference,
            pretalx_code="CS1",
            name="Returning By User",
            user=user1,
        )
        Speaker.objects.create(
            conference=conference,
            pretalx_code="CS2",
            name="Returning By Name",
            email="byname@test.com",
        )
        Speaker.objects.create(
            conference=conference,
            pretalx_code="CS3",
            name="Brand New Speaker",
            email="new@test.com",
        )

        result = get_speaker_return_rate(conference)

        assert result["current_speaker_count"] == 3
        assert result["returning_count"] == 2
        assert result["new_count"] == 1
        assert round(result["return_rate"], 2) == Decimal("66.67")


# ---------------------------------------------------------------------------
# get_yoy_growth
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestYoyGrowthIntZeroBranch:
    def test_zero_previous_attendance_takes_int_zero_branch(self, conference, previous_conference):
        """previous_conference has zero attendees: the non-Decimal 'attendance'
        metric hits the falsy-prev_val branch (pct = _ZERO) instead of the
        Decimal or nonzero-int division branches."""
        result = get_yoy_growth(conference)

        assert result["history"][0]["attendance"] == 0
        assert result["current"]["attendance_growth_pct"] == Decimal("0.00")
