"""Tests that manage views respect ``DJANGO_PROGRAM['features']`` flags."""

from datetime import date

import pytest
from django.contrib.auth.models import User
from django.test import Client, override_settings
from django.urls import reverse

from django_program.conference.models import Conference


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(username="admin", password="password", email="admin@test.com")


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
def another_conference(db):
    return Conference.objects.create(
        name="Another Conf",
        slug="another-conf",
        start_date=date(2028, 5, 1),
        end_date=date(2028, 5, 3),
        timezone="UTC",
        is_active=True,
    )


# ---------------------------------------------------------------------------
# manage_ui
# ---------------------------------------------------------------------------


class TestManageUIFeature:
    @override_settings(DJANGO_PROGRAM={"features": {"manage_ui_enabled": False}})
    def test_dashboard_404_when_manage_ui_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:dashboard", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    def test_dashboard_200_when_manage_ui_enabled(self, client_logged_in_super, conference):
        url = reverse("manage:dashboard", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200

    @override_settings(DJANGO_PROGRAM={"features": {"manage_ui_enabled": False}})
    def test_conference_list_404_when_manage_ui_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:conference-list")
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    def test_conference_list_200_when_manage_ui_enabled(self, client_logged_in_super, conference):
        url = reverse("manage:conference-list")
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200

    @override_settings(DJANGO_PROGRAM={"features": {"manage_ui_enabled": False}})
    def test_import_pretalx_404_when_manage_ui_disabled(self, client_logged_in_super):
        url = reverse("manage:import-pretalx")
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


class TestRegistrationFeature:
    @override_settings(DJANGO_PROGRAM={"features": {"registration_enabled": False}})
    def test_attendee_list_404_when_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:attendee-list", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    def test_attendee_list_200_when_enabled(self, client_logged_in_super, conference):
        url = reverse("manage:attendee-list", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200

    @override_settings(DJANGO_PROGRAM={"features": {"registration_enabled": False}})
    def test_order_list_404_when_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:order-list", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    @override_settings(DJANGO_PROGRAM={"features": {"registration_enabled": False}})
    def test_bulk_purchase_list_404_when_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:bulk-purchase-list", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    @override_settings(DJANGO_PROGRAM={"features": {"registration_enabled": False}})
    def test_purchase_order_list_404_when_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:purchase-order-list", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    @override_settings(DJANGO_PROGRAM={"features": {"registration_enabled": False}})
    def test_checkin_dashboard_404_when_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:checkin-dashboard", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    @override_settings(DJANGO_PROGRAM={"features": {"registration_enabled": False}})
    def test_financial_dashboard_404_when_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:financial-dashboard", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# sponsors
# ---------------------------------------------------------------------------


class TestSponsorsFeature:
    @override_settings(DJANGO_PROGRAM={"features": {"sponsors_enabled": False}})
    def test_sponsor_manage_list_404_when_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:sponsor-manage-list", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    def test_sponsor_manage_list_200_when_enabled(self, client_logged_in_super, conference):
        url = reverse("manage:sponsor-manage-list", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200

    @override_settings(DJANGO_PROGRAM={"features": {"sponsors_enabled": False}})
    def test_sponsor_override_list_404_when_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:sponsor-override-list", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# travel_grants
# ---------------------------------------------------------------------------


class TestTravelGrantsFeature:
    @override_settings(DJANGO_PROGRAM={"features": {"travel_grants_enabled": False}})
    def test_travel_grant_list_404_when_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:travel-grant-list", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    def test_travel_grant_list_200_when_enabled(self, client_logged_in_super, conference):
        url = reverse("manage:travel-grant-list", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200

    @override_settings(DJANGO_PROGRAM={"features": {"travel_grants_enabled": False}})
    def test_receipt_review_queue_404_when_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:receipt-review-queue", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# programs
# ---------------------------------------------------------------------------


class TestProgramsFeature:
    @override_settings(DJANGO_PROGRAM={"features": {"programs_enabled": False}})
    def test_activity_list_404_when_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:activity-list", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    def test_activity_list_200_when_enabled(self, client_logged_in_super, conference):
        url = reverse("manage:activity-list", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# pretalx_sync
# ---------------------------------------------------------------------------


class TestPretalxSyncFeature:
    @override_settings(DJANGO_PROGRAM={"features": {"pretalx_sync_enabled": False}})
    def test_import_pretalx_404_when_disabled(self, client_logged_in_super):
        url = reverse("manage:import-pretalx")
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    def test_import_pretalx_200_when_enabled(self, client_logged_in_super):
        url = reverse("manage:import-pretalx")
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200

    @override_settings(DJANGO_PROGRAM={"features": {"pretalx_sync_enabled": False}})
    def test_pretalx_event_search_404_when_disabled(self, client_logged_in_super):
        url = reverse("manage:pretalx-event-search")
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    @override_settings(DJANGO_PROGRAM={"features": {"pretalx_sync_enabled": False}})
    def test_sync_pretalx_404_when_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:sync-pretalx", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.post(url)
        assert resp.status_code == 404

    @override_settings(DJANGO_PROGRAM={"features": {"pretalx_sync_enabled": False}})
    def test_override_list_404_when_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:override-list", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# visa_letters
# ---------------------------------------------------------------------------


class TestVisaLettersFeature:
    @override_settings(DJANGO_PROGRAM={"features": {"visa_letters_enabled": False}})
    def test_letter_list_404_when_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:letter-list", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    def test_letter_list_200_when_enabled(self, client_logged_in_super, conference):
        url = reverse("manage:letter-list", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# No-feature views stay ungated by module features (only manage_ui applies)
# ---------------------------------------------------------------------------


class TestNoFeatureViews:
    @override_settings(
        DJANGO_PROGRAM={
            "features": {
                "registration_enabled": False,
                "sponsors_enabled": False,
                "travel_grants_enabled": False,
                "programs_enabled": False,
                "pretalx_sync_enabled": False,
                "visa_letters_enabled": False,
            }
        }
    )
    def test_section_list_unaffected_by_module_features(self, client_logged_in_super, conference):
        url = reverse("manage:section-list", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Single-conference redirect
# ---------------------------------------------------------------------------


class TestSingleConferenceRedirect:
    @override_settings(DJANGO_PROGRAM={"manage": {"conference": "test-conf"}})
    def test_conference_list_redirects_to_single_conference_dashboard(
        self, client_logged_in_super, conference, another_conference
    ):
        url = reverse("manage:conference-list")
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 302
        assert resp.url == reverse("manage:dashboard", kwargs={"conference_slug": conference.slug})

    @override_settings(DJANGO_PROGRAM={"manage": {"conference": "nonexistent-conf"}})
    def test_conference_list_falls_back_when_configured_conference_missing(self, client_logged_in_super, conference):
        url = reverse("manage:conference-list")
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200

    def test_conference_list_no_redirect_without_single_conference_setting(self, client_logged_in_super, conference):
        url = reverse("manage:conference-list")
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200
