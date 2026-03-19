"""Check-in dashboard and scanner views for the manage app.

Provides the staff-facing scanner interface for on-site check-in and a
real-time dashboard showing check-in statistics, station activity, and
product redemption counts.
"""

from django.db.models import Count, Max
from django.utils import timezone
from django.views.generic import TemplateView

from django_program.manage.views import ManagePermissionMixin
from django_program.registration.attendee import Attendee
from django_program.registration.checkin import CheckIn, DoorCheck, ProductRedemption


class CheckInScannerView(ManagePermissionMixin, TemplateView):
    """Staff-facing scanner page for on-site check-in.

    Renders the scanner template with conference context. All scanning
    logic is handled client-side via the check-in API endpoints.
    """

    template_name = "django_program/manage/checkin_scanner.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add active_nav to the template context.

        Args:
            **kwargs: Additional context data.

        Returns:
            Template context with conference and active navigation state.
        """
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "checkin"
        return context


class CheckInDashboardView(ManagePermissionMixin, TemplateView):
    """Real-time check-in statistics dashboard.

    Displays aggregate check-in data including total attendees, check-in
    rate, station activity breakdown, recent check-in log, and product
    redemption statistics.
    """

    template_name = "django_program/manage/checkin_dashboard.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Build context with check-in statistics for the dashboard.

        Args:
            **kwargs: Additional context data.

        Returns:
            Template context with attendee counts, check-in rate, station
            activity, recent check-ins, and redemption stats.
        """
        context = super().get_context_data(**kwargs)
        conference = self.conference
        context["active_nav"] = "checkin"

        total_attendees = Attendee.objects.filter(conference=conference).count()
        checked_in_count = Attendee.objects.filter(conference=conference, checkins__isnull=False).distinct().count()
        check_in_rate = round((checked_in_count / total_attendees * 100), 1) if total_attendees > 0 else 0

        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        checkins_today = CheckIn.objects.filter(conference=conference, checked_in_at__gte=today_start).count()

        checkins_by_station = (
            CheckIn.objects.filter(conference=conference)
            .exclude(station="")
            .values("station")
            .annotate(count=Count("id"), last_checkin=Max("checked_in_at"))
            .order_by("-count")
        )

        recent_checkins = (
            CheckIn.objects.filter(conference=conference)
            .select_related("attendee", "attendee__user", "checked_in_by")
            .order_by("-checked_in_at")[:50]
        )

        redemption_stats = (
            ProductRedemption.objects.filter(conference=conference)
            .values("order_line_item__description")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        door_check_counts = (
            DoorCheck.objects.filter(conference=conference)
            .values("ticket_type__name", "addon__name")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        context["total_attendees"] = total_attendees
        context["checked_in_count"] = checked_in_count
        context["check_in_rate"] = check_in_rate
        context["checkins_today"] = checkins_today
        context["checkins_by_station"] = checkins_by_station
        context["recent_checkins"] = recent_checkins
        context["redemption_stats"] = redemption_stats
        context["door_check_counts"] = door_check_counts
        return context
