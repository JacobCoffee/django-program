"""Tests that manage views respect ``DJANGO_PROGRAM['features']`` flags."""

from datetime import date

import pytest
from django.contrib.auth.models import User
from django.http import Http404, HttpResponse
from django.test import Client, override_settings
from django.urls import reverse
from django.views import View

from django_program.conference.models import Conference
from django_program.manage.views import ConferencePermissionMixin


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
    def test_override_list_200_when_sync_disabled(self, client_logged_in_super, conference):
        """Overrides apply regardless of sync (pretalx/models.py), so the view stays open."""
        url = reverse("manage:override-list", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200


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


# ---------------------------------------------------------------------------
# reports (views_reports.py) — registration-backed reports vs visa_letters
# ---------------------------------------------------------------------------


class TestReportsFeatureGating:
    @override_settings(DJANGO_PROGRAM={"features": {"registration_enabled": False}})
    def test_attendee_manifest_report_404_when_registration_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:report-attendee-manifest", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    @override_settings(DJANGO_PROGRAM={"features": {"registration_enabled": False}})
    def test_attendee_manifest_export_404_when_registration_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:report-attendee-export", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    def test_attendee_manifest_report_200_when_enabled(self, client_logged_in_super, conference):
        url = reverse("manage:report-attendee-manifest", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200

    @override_settings(DJANGO_PROGRAM={"features": {"registration_enabled": False}})
    def test_inventory_report_404_when_registration_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:report-inventory", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    @override_settings(DJANGO_PROGRAM={"features": {"registration_enabled": False}})
    def test_voucher_usage_report_404_when_registration_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:report-voucher-usage", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    @override_settings(DJANGO_PROGRAM={"features": {"registration_enabled": False}})
    def test_discount_effectiveness_report_404_when_registration_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:report-discount-effectiveness", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    @override_settings(DJANGO_PROGRAM={"features": {"registration_enabled": False}})
    def test_sales_by_date_report_404_when_registration_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:report-sales-by-date", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    @override_settings(DJANGO_PROGRAM={"features": {"registration_enabled": False}})
    def test_credit_notes_report_404_when_registration_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:report-credit-notes", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    @override_settings(DJANGO_PROGRAM={"features": {"registration_enabled": False}})
    def test_speaker_registration_report_404_when_registration_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:report-speaker-registration", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    @override_settings(DJANGO_PROGRAM={"features": {"registration_enabled": False}})
    def test_reconciliation_report_404_when_registration_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:report-reconciliation", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    @override_settings(DJANGO_PROGRAM={"features": {"registration_enabled": False}})
    def test_registration_flow_report_404_when_registration_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:report-registration-flow", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    @override_settings(DJANGO_PROGRAM={"features": {"visa_letters_enabled": False}})
    def test_visa_letter_report_404_when_visa_letters_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:report-visa-letters", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    @override_settings(DJANGO_PROGRAM={"features": {"visa_letters_enabled": False}})
    def test_visa_letter_export_404_when_visa_letters_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:report-visa-letters-export", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    def test_visa_letter_report_200_when_enabled(self, client_logged_in_super, conference):
        url = reverse("manage:report-visa-letters", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200

    @override_settings(DJANGO_PROGRAM={"features": {"registration_enabled": False, "visa_letters_enabled": False}})
    def test_reports_dashboard_itself_stays_200_with_everything_disabled(self, client_logged_in_super, conference):
        """The reports hub is feature-less; it just hides links/panels for disabled modules."""
        url = reverse("manage:reports-dashboard", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200

    @override_settings(DJANGO_PROGRAM={"features": {"registration_enabled": False}})
    def test_reports_dashboard_hides_registration_report_links_when_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:reports-dashboard", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        content = resp.content.decode()
        disabled_url = reverse("manage:report-attendee-manifest", kwargs={"conference_slug": conference.slug})
        assert disabled_url not in content

    @override_settings(DJANGO_PROGRAM={"features": {"visa_letters_enabled": False}})
    def test_reports_dashboard_hides_visa_letters_link_when_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:reports-dashboard", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        content = resp.content.decode()
        disabled_url = reverse("manage:report-visa-letters", kwargs={"conference_slug": conference.slug})
        assert disabled_url not in content


# ---------------------------------------------------------------------------
# analytics (views_analytics.py) — SponsorAnalyticsView vs feature-less hubs
# ---------------------------------------------------------------------------


class TestAnalyticsFeatureGating:
    @override_settings(DJANGO_PROGRAM={"features": {"sponsors_enabled": False}})
    def test_sponsor_analytics_404_when_sponsors_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:sponsor-analytics", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 404

    def test_sponsor_analytics_200_when_enabled(self, client_logged_in_super, conference):
        url = reverse("manage:sponsor-analytics", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200

    @override_settings(
        DJANGO_PROGRAM={
            "features": {
                "sponsors_enabled": False,
                "travel_grants_enabled": False,
                "programs_enabled": False,
            }
        }
    )
    def test_analytics_dashboard_itself_stays_200_with_modules_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:analytics-dashboard", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200

    @override_settings(DJANGO_PROGRAM={"features": {"sponsors_enabled": False}})
    def test_analytics_dashboard_hides_sponsor_analytics_link_when_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:analytics-dashboard", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        content = resp.content.decode()
        disabled_url = reverse("manage:sponsor-analytics", kwargs={"conference_slug": conference.slug})
        assert disabled_url not in content

    def test_cross_event_dashboard_stays_feature_less(self, client_logged_in_super, conference):
        """Cross-event intelligence aggregates multiple modules and stays ungated itself."""
        url = reverse("manage:cross-event-dashboard", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Main conference dashboard (views.py DashboardView + dashboard.html) — links,
# metrics, and sync forms must not point at disabled modules.
# ---------------------------------------------------------------------------


class TestMainDashboardFeatureGating:
    def test_dashboard_200_with_everything_disabled(self, client_logged_in_super, conference):
        """The main dashboard itself is feature-less; it just hides gated content."""
        with override_settings(
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
        ):
            url = reverse("manage:dashboard", kwargs={"conference_slug": conference.slug})
            resp = client_logged_in_super.get(url)
            assert resp.status_code == 200

    @override_settings(DJANGO_PROGRAM={"features": {"registration_enabled": False}})
    def test_dashboard_hides_registration_metric_and_links_when_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:dashboard", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        content = resp.content.decode()
        assert reverse("manage:order-list", kwargs={"conference_slug": conference.slug}) not in content
        assert reverse("manage:ticket-type-list", kwargs={"conference_slug": conference.slug}) not in content
        assert reverse("manage:addon-list", kwargs={"conference_slug": conference.slug}) not in content
        assert reverse("manage:voucher-list", kwargs={"conference_slug": conference.slug}) not in content

    def test_dashboard_shows_registration_links_when_enabled(self, client_logged_in_super, conference):
        url = reverse("manage:dashboard", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        content = resp.content.decode()
        assert reverse("manage:order-list", kwargs={"conference_slug": conference.slug}) in content

    @override_settings(DJANGO_PROGRAM={"features": {"programs_enabled": False}})
    def test_dashboard_hides_activities_link_when_programs_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:dashboard", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        content = resp.content.decode()
        assert reverse("manage:activity-list", kwargs={"conference_slug": conference.slug}) not in content

    @override_settings(DJANGO_PROGRAM={"features": {"sponsors_enabled": False}})
    def test_dashboard_hides_sponsors_link_when_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:dashboard", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        content = resp.content.decode()
        assert reverse("manage:sponsor-manage-list", kwargs={"conference_slug": conference.slug}) not in content

    @override_settings(DJANGO_PROGRAM={"features": {"travel_grants_enabled": False}})
    def test_dashboard_hides_travel_grants_link_when_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:dashboard", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        content = resp.content.decode()
        assert reverse("manage:travel-grant-list", kwargs={"conference_slug": conference.slug}) not in content

    @override_settings(DJANGO_PROGRAM={"features": {"visa_letters_enabled": False}})
    def test_dashboard_hides_visa_letters_link_when_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:dashboard", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        content = resp.content.decode()
        assert reverse("manage:letter-list", kwargs={"conference_slug": conference.slug}) not in content

    @override_settings(DJANGO_PROGRAM={"features": {"pretalx_sync_enabled": False}})
    def test_dashboard_hides_pretalx_sync_form_when_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:dashboard", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        content = resp.content.decode()
        assert reverse("manage:sync-pretalx", kwargs={"conference_slug": conference.slug}) not in content
        assert reverse("manage:sync-pretalx-stream", kwargs={"conference_slug": conference.slug}) not in content
        assert "Sync Pretalx" not in content

    def test_dashboard_shows_pretalx_sync_form_when_enabled(self, client_logged_in_super, conference):
        url = reverse("manage:dashboard", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        content = resp.content.decode()
        assert reverse("manage:sync-pretalx", kwargs={"conference_slug": conference.slug}) in content

    @override_settings(DJANGO_PROGRAM={"features": {"pretalx_sync_enabled": False, "sponsors_enabled": False}})
    def test_dashboard_hides_whole_sync_card_when_both_sync_features_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:dashboard", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        content = resp.content.decode()
        assert 'id="sync-section"' not in content


# ---------------------------------------------------------------------------
# analytics_dashboard.html — registration-only charts/table must not render
# (and must not generate dead drill-down links) when registration is off.
# ---------------------------------------------------------------------------


class TestAnalyticsDashboardRegistrationGating:
    @override_settings(DJANGO_PROGRAM={"features": {"registration_enabled": False}})
    def test_cart_funnel_chart_not_rendered_when_registration_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:analytics-dashboard", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        content = resp.content.decode()
        assert 'id="chart-cart-funnel"' not in content

    def test_cart_funnel_chart_rendered_when_registration_enabled(self, client_logged_in_super, conference):
        url = reverse("manage:analytics-dashboard", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        content = resp.content.decode()
        assert 'id="chart-cart-funnel"' in content

    @override_settings(DJANGO_PROGRAM={"features": {"registration_enabled": False}})
    def test_ticket_sales_ratio_table_not_rendered_when_registration_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:analytics-dashboard", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        content = resp.content.decode()
        assert "Ticket Sales Ratio" not in content

    @override_settings(DJANGO_PROGRAM={"features": {"registration_enabled": False}})
    def test_drilldown_order_list_url_empty_when_registration_disabled(self, client_logged_in_super, conference):
        url = reverse("manage:analytics-dashboard", kwargs={"conference_slug": conference.slug})
        resp = client_logged_in_super.get(url)
        content = resp.content.decode()
        assert reverse("manage:order-list", kwargs={"conference_slug": conference.slug}) not in content
        assert "orderList: ''" in content

    def test_analytics_dashboard_200_when_registration_disabled(self, client_logged_in_super, conference):
        with override_settings(DJANGO_PROGRAM={"features": {"registration_enabled": False}}):
            url = reverse("manage:analytics-dashboard", kwargs={"conference_slug": conference.slug})
            resp = client_logged_in_super.get(url)
            assert resp.status_code == 200


class _NeedsTwoModules(ConferencePermissionMixin, View):
    required_feature = ("registration", "sponsors")

    def get(self, request, **kwargs):
        return HttpResponse("ok")


class TestTupleRequiredFeature:
    def test_every_listed_module_must_be_enabled(self, rf, superuser, conference, settings):
        request = rf.get("/")
        request.user = superuser
        view = _NeedsTwoModules.as_view()
        assert view(request, conference_slug=conference.slug).status_code == 200

        settings.DJANGO_PROGRAM = {"features": {"sponsors_enabled": False}}
        with pytest.raises(Http404):
            view(request, conference_slug=conference.slug)
