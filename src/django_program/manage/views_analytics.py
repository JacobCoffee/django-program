"""Analytics and KPI dashboard views for conference management.

Provides the main analytics dashboard (Tier 1 KPIs from existing data),
the cross-event intelligence dashboard (Tier 3 cross-conference metrics),
and sponsor-level analytics with goal tracking.
Both views are gated by the same report-level permissions.
"""

import json
from decimal import Decimal
from typing import Any

from django.views.generic import TemplateView

from django_program.manage.reports import (
    get_activity_utilization,
    get_attendee_summary,
    get_cart_funnel,
    get_checkin_throughput,
    get_content_analytics,
    get_refund_metrics,
    get_revenue_breakdown,
    get_revenue_per_attendee,
    get_room_utilization,
    get_sponsor_benefit_fulfillment,
    get_ticket_sales_ratio,
    get_travel_grant_analytics,
)
from django_program.manage.views_reports import ReportPermissionMixin

_ZERO = Decimal("0.00")

# Default KPI targets (industry averages / sensible defaults)
_DEFAULT_TARGETS = {
    "target_conversion_rate": Decimal("3.0"),
    "target_refund_rate": Decimal("5.0"),
    "target_checkin_rate": Decimal("80.0"),
    "target_fulfillment_rate": Decimal("90.0"),
    "target_revenue_per_attendee": None,
    "target_room_utilization": Decimal("28.0"),
}


def _decimal_to_float(obj: object) -> float | str | object:
    """Convert Decimal values to float for JSON serialization.

    Args:
        obj: The value to convert.

    Returns:
        Float if Decimal, otherwise the original value.
    """
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


def _serialize_for_json(data: dict[str, Any] | list[Any]) -> str:
    """Serialize a dict or list to JSON, converting Decimals to floats.

    Args:
        data: The data structure to serialize.

    Returns:
        A JSON string with Decimals converted to floats.
    """
    return json.dumps(data, default=_decimal_to_float)


def _get_effective_targets(conference: object) -> dict[str, Any]:
    """Return effective KPI targets, merging conference overrides with defaults.

    Args:
        conference: The conference instance (may or may not have kpi_targets).

    Returns:
        A dict of target field names to their effective values.
    """
    from django_program.conference.models import KPITargets  # noqa: PLC0415

    targets = dict(_DEFAULT_TARGETS)
    try:
        kpi = conference.kpi_targets  # type: ignore[union-attr]
        for field in _DEFAULT_TARGETS:
            val = getattr(kpi, field, None)
            if val is not None:
                targets[field] = val
    except KPITargets.DoesNotExist:
        pass
    return targets


class AnalyticsDashboardView(ReportPermissionMixin, TemplateView):
    """Main analytics and KPI dashboard aggregating Tier 1 metrics.

    Provides revenue per attendee, cart funnel, check-in throughput,
    room utilization, sponsor fulfillment, travel grant analytics,
    activity capacity, content analytics, and ticket sales ratio.
    """

    template_name = "django_program/manage/analytics_dashboard.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Build context with all Tier 1 analytics KPIs and chart data.

        Args:
            **kwargs: Additional context data.

        Returns:
            Template context with KPI summaries and JSON chart data.
        """
        context: dict[str, object] = super().get_context_data(**kwargs)
        context["active_nav"] = "analytics"
        conference = self.conference

        # KPI targets (Feature #49)
        targets = _get_effective_targets(conference)
        context["kpi_targets"] = targets

        # KPI summary data
        revenue_data = get_revenue_per_attendee(conference)
        cart_data = get_cart_funnel(conference)
        attendee_summary = get_attendee_summary(conference)
        fulfillment_data = get_sponsor_benefit_fulfillment(conference)
        refund_data = get_refund_metrics(conference)

        checkin_rate = _ZERO
        if attendee_summary["total"] > 0:
            checkin_rate = Decimal(attendee_summary["checked_in"]) / Decimal(attendee_summary["total"]) * 100

        context["kpi_summary"] = {
            "revenue_per_attendee": revenue_data["revenue_per_attendee"],
            "conversion_rate": cart_data["conversion_rate"],
            "checkin_rate": round(checkin_rate, 1),
            "fulfillment_rate": fulfillment_data["fulfillment_rate"],
            "refund_rate": refund_data["refund_rate"],
        }

        # Revenue breakdown
        revenue_breakdown = get_revenue_breakdown(conference)
        context["revenue_breakdown"] = revenue_breakdown
        context["chart_revenue_breakdown_json"] = _serialize_for_json(revenue_breakdown)

        # Cart funnel
        context["cart_funnel"] = cart_data
        context["chart_cart_funnel_json"] = _serialize_for_json(cart_data)

        # Room utilization — pass target to chart
        room_data = get_room_utilization(conference)
        context["room_utilization"] = room_data
        room_chart_data = {
            "rooms": room_data,
            "target_pct": float(targets["target_room_utilization"]) if targets["target_room_utilization"] else 28,
        }
        context["chart_room_utilization_json"] = _serialize_for_json(room_chart_data)

        # Activity capacity
        activity_data = get_activity_utilization(conference)
        context["activity_utilization"] = activity_data
        context["chart_activity_capacity_json"] = _serialize_for_json(activity_data)

        # Travel grant analytics
        grant_data = get_travel_grant_analytics(conference)
        context["grant_analytics"] = grant_data
        grant_chart = {
            "by_status": grant_data["by_status"],
            "approval_rate": grant_data["approval_rate"],
            "total_approved": grant_data["total_approved"],
            "total_disbursed": grant_data["total_disbursed"],
        }
        if conference.grant_budget:
            grant_chart["budget"] = conference.grant_budget
        context["chart_grant_status_json"] = _serialize_for_json(grant_chart)

        # Content analytics
        content_data = get_content_analytics(conference)
        context["content_analytics"] = content_data
        context["chart_content_json"] = _serialize_for_json(content_data)

        # Ticket sales ratio
        ticket_data = get_ticket_sales_ratio(conference)
        context["ticket_sales_ratio"] = ticket_data

        # Sponsor benefit fulfillment
        context["sponsor_fulfillment"] = fulfillment_data

        # Check-in throughput
        throughput_data = get_checkin_throughput(conference)
        context["chart_checkin_throughput_json"] = _serialize_for_json(
            [
                {
                    "bucket_start": row["bucket_start"].isoformat(),
                    "bucket_end": row["bucket_end"].isoformat(),
                    "count": row["count"],
                }
                for row in throughput_data
            ]
        )

        return context


class SponsorAnalyticsView(ReportPermissionMixin, TemplateView):
    """Sponsor analytics dashboard with revenue and goal tracking.

    Provides per-level sponsor counts, revenue, benefit fulfillment
    rates, and sponsor pipeline visualizations.
    """

    template_name = "django_program/manage/sponsor_analytics.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Build context with sponsor analytics data.

        Args:
            **kwargs: Additional context data.

        Returns:
            Template context with sponsor metrics and chart data.
        """
        context: dict[str, object] = super().get_context_data(**kwargs)
        context["active_nav"] = "analytics"
        conference = self.conference

        from django_program.manage.reports_analytics import (  # noqa: PLC0415
            get_sponsor_analytics,
            get_sponsor_renewal_rate,
        )

        sponsor_data = get_sponsor_analytics(conference)
        context["sponsor_analytics"] = sponsor_data
        context["chart_sponsor_revenue_json"] = _serialize_for_json(sponsor_data["by_level"])

        fulfillment_data = get_sponsor_benefit_fulfillment(conference)
        context["sponsor_fulfillment"] = fulfillment_data

        renewal_data = get_sponsor_renewal_rate(conference)
        context["sponsor_renewal"] = renewal_data

        return context


class CrossEventDashboardView(ReportPermissionMixin, TemplateView):
    """Cross-event intelligence dashboard with Tier 3 metrics.

    Provides year-over-year retention, attendee lifetime value,
    sponsor renewal rate, speaker return rate, and YoY growth comparison.
    """

    template_name = "django_program/manage/cross_event_dashboard.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Build context with cross-conference analytics.

        Args:
            **kwargs: Additional context data.

        Returns:
            Template context with retention, LTV, renewal, and growth data.
        """
        context: dict[str, object] = super().get_context_data(**kwargs)
        context["active_nav"] = "analytics"
        conference = self.conference

        # Lazy import to avoid circular imports at module level; these
        # functions live in the analytics report module which depends on
        # models that may not yet have migrations during initial dev.
        from django_program.manage.reports_analytics import (  # noqa: PLC0415
            get_attendee_lifetime_value,
            get_speaker_return_rate,
            get_sponsor_renewal_rate,
            get_yoy_growth,
            get_yoy_retention,
        )

        # YoY retention
        retention = get_yoy_retention(conference)
        context["retention"] = retention
        context["chart_retention_json"] = _serialize_for_json(
            {
                "returning": retention["returning_count"],
                "new": retention["new_count"],
                "total": retention["current_attendee_count"],
                "retention_rate": retention["retention_rate"],
            }
        )

        # Attendee LTV
        ltv = get_attendee_lifetime_value(conference)
        context["ltv"] = ltv
        context["chart_ltv_json"] = _serialize_for_json(
            {
                "avg_ltv": ltv["avg_ltv"],
                "max_ltv": ltv["max_ltv"],
                "total_users": ltv["total_users_with_orders"],
            }
        )

        # Sponsor renewal
        sponsor_renewal = get_sponsor_renewal_rate(conference)
        context["sponsor_renewal"] = sponsor_renewal

        # Speaker return rate
        speaker_return = get_speaker_return_rate(conference)
        context["speaker_return"] = speaker_return

        # YoY growth
        growth = get_yoy_growth(conference)
        context["yoy_growth"] = growth
        # Build chart series: history (oldest first) + current as last point.
        # Each entry already has attendance, revenue, sponsors, talks, and
        # per-entry attendance_growth_pct / revenue_growth_pct where applicable.
        chart_history = [*reversed(growth["history"]), growth["current"]]
        for item in chart_history:
            item["label"] = str(item.get("name", ""))
        context["chart_growth_json"] = _serialize_for_json(
            {
                "current": growth["current"],
                "history": chart_history,
            }
        )

        return context
