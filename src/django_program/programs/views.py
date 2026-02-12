"""Views for the programs app.

Provides activity listing, detail, signup, and travel grant application
views scoped to a conference via the ``conference_slug`` URL kwarg.
"""

from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, ListView

from django_program.pretalx.views import ConferenceMixin
from django_program.programs.forms import TravelGrantApplicationForm
from django_program.programs.models import Activity, ActivitySignup

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest, HttpResponse


class ActivityListView(ConferenceMixin, ListView):
    """List view of all active activities for a conference."""

    template_name = "django_program/programs/activity_list.html"
    context_object_name = "activities"

    def get_queryset(self) -> QuerySet[Activity]:
        """Return active activities for the current conference.

        Returns:
            A queryset of active Activity instances ordered by time and name,
            annotated with ``signup_count`` to avoid N+1 queries.
        """
        return (
            Activity.objects.filter(conference=self.conference, is_active=True)
            .annotate(signup_count=Count("signups"))
            .order_by("start_time", "name")
        )


class ActivityDetailView(ConferenceMixin, DetailView):
    """Detail view for a single activity."""

    template_name = "django_program/programs/activity_detail.html"
    context_object_name = "activity"

    def get_object(self, queryset: QuerySet[Activity] | None = None) -> Activity:  # noqa: ARG002
        """Look up the activity by conference and slug.

        Returns:
            The matched Activity instance.

        Raises:
            Http404: If no active activity matches the conference and slug.
        """
        return get_object_or_404(
            Activity,
            conference=self.conference,
            slug=self.kwargs["slug"],
            is_active=True,
        )

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add signups and availability to the template context.

        Returns:
            Context dict with ``signups`` and ``spots_remaining``.
        """
        context = super().get_context_data(**kwargs)
        context["signups"] = self.object.signups.select_related("user")
        context["spots_remaining"] = self.object.spots_remaining
        return context


class ActivitySignupView(LoginRequiredMixin, ConferenceMixin, View):
    """POST-only view for signing up to an activity."""

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Handle the signup form submission.

        Uses ``select_for_update`` inside a transaction to prevent race
        conditions when checking capacity.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments (unused).

        Returns:
            A redirect to the activity detail page.
        """
        with transaction.atomic():
            activity = get_object_or_404(
                Activity.objects.select_for_update(),
                conference=self.conference,
                slug=self.kwargs["slug"],
                is_active=True,
            )
            if activity.spots_remaining is not None and activity.spots_remaining <= 0:
                messages.error(request, "This activity is full.")
                return redirect(reverse("programs:activity-detail", args=[self.conference.slug, activity.slug]))
            ActivitySignup.objects.get_or_create(
                activity=activity,
                user=request.user,
                defaults={"note": request.POST.get("note", "")},
            )
        messages.success(request, f"You have signed up for {activity.name}.")
        return redirect(reverse("programs:activity-detail", args=[self.conference.slug, activity.slug]))


class TravelGrantApplyView(LoginRequiredMixin, ConferenceMixin, View):
    """View for applying for a travel grant.

    Uses ``TravelGrantApplicationForm`` for server-side validation of
    the requested amount, travel origin, and reason fields.
    """

    template_name = "django_program/programs/travel_grant_form.html"

    def get(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Render the travel grant application form.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments (unused).

        Returns:
            The rendered form page.
        """
        form = TravelGrantApplicationForm()
        return render(request, self.template_name, {"conference": self.conference, "form": form})

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Handle the travel grant application submission.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments (unused).

        Returns:
            A redirect to the activity list on success, or the form with
            errors on validation failure.
        """
        form = TravelGrantApplicationForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"conference": self.conference, "form": form})

        grant = form.save(commit=False)
        grant.conference = self.conference
        grant.user = request.user
        try:
            with transaction.atomic():
                grant.save()
        except IntegrityError:
            messages.error(request, "You have already applied for a travel grant for this conference.")
            return redirect(reverse("programs:activity-list", args=[self.conference.slug]))
        messages.success(request, "Your travel grant application has been submitted.")
        return redirect(reverse("programs:activity-list", args=[self.conference.slug]))
