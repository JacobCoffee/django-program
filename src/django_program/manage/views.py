"""Views for the conference management dashboard.

Provides permission-gated CRUD views for conference organizers and
superadmins.  All conference-scoped views inherit from
``ManagePermissionMixin`` which resolves the conference from the URL
and enforces access control.
"""

import itertools
import json
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import models
from django.db.models import Count, Q, QuerySet, Sum
from django.http import HttpRequest, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.timezone import localdate
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from django_program.conference.models import Conference, Section
from django_program.manage.forms import (
    ActivityForm,
    AddOnForm,
    ConferenceForm,
    DisbursementForm,
    ImportFromPretalxForm,
    ManualPaymentForm,
    ReceiptFlagForm,
    ReviewerMessageForm,
    RoomForm,
    ScheduleSlotForm,
    SectionForm,
    SponsorForm,
    SponsorLevelForm,
    TalkForm,
    TicketTypeForm,
    TravelGrantForm,
    VoucherForm,
)
from django_program.pretalx.models import Room, ScheduleSlot, Speaker, Talk
from django_program.pretalx.sync import PretalxSyncService
from django_program.programs.models import Activity, ActivitySignup, Receipt, TravelGrant, TravelGrantMessage
from django_program.registration.models import AddOn, Order, Payment, TicketType, Voucher
from django_program.settings import get_config
from django_program.sponsors.models import Sponsor, SponsorLevel
from django_program.sponsors.profiles.resolver import resolve_sponsor_profile
from django_program.sponsors.sync import SponsorSyncService
from pretalx_client.adapters.normalization import localized as _localized
from pretalx_client.client import PretalxClient

logger = logging.getLogger(__name__)


def _unique_section_slug(name: str, conference: object, exclude_pk: int | None = None) -> str:
    """Generate a unique slug for a Section within a conference.

    Args:
        name: The section name to slugify.
        conference: The conference instance to scope uniqueness to.
        exclude_pk: Optional PK to exclude (for updates).

    Returns:
        A unique slug string.
    """
    base = slugify(name) or "section"
    candidate = base
    counter = 1
    while True:
        qs = Section.objects.filter(conference=conference, slug=candidate)
        if exclude_pk is not None:
            qs = qs.exclude(pk=exclude_pk)
        if not qs.exists():
            return candidate
        counter += 1
        candidate = f"{base}-{counter}"


def _unique_activity_slug(name: str, conference: object, exclude_pk: int | None = None) -> str:
    """Generate a unique slug for an Activity within a conference.

    Appends a numeric suffix (``-2``, ``-3``, ...) if a collision
    is detected on the ``(conference, slug)`` unique constraint.

    Args:
        name: The activity name to slugify.
        conference: The conference instance to scope uniqueness to.
        exclude_pk: Optional PK to exclude (for updates).

    Returns:
        A unique slug string.
    """
    base = slugify(name) or "activity"
    candidate = base
    counter = 1
    while True:
        qs = Activity.objects.filter(conference=conference, slug=candidate)
        if exclude_pk is not None:
            qs = qs.exclude(pk=exclude_pk)
        if not qs.exists():
            return candidate
        counter += 1
        candidate = f"{base}-{counter}"


class ManagePermissionMixin(LoginRequiredMixin):
    """Permission mixin for conference-scoped management views.

    Resolves the conference from the ``conference_slug`` URL kwarg and
    checks that the authenticated user is a superuser or holds the
    ``program_conference.change_conference`` permission.  Stores the
    resolved conference on ``self.conference`` and injects it into the
    template context.

    Raises:
        PermissionDenied: If the user lacks the required permission.
    """

    conference: Conference
    kwargs: dict[str, str]

    def get_submission_type_nav(self) -> list[dict[str, str | int]]:
        """Build sidebar navigation data for talk submission types."""
        types = (
            Talk.objects.filter(conference=self.conference)
            .exclude(submission_type="")
            .values("submission_type")
            .annotate(count=Count("id"))
            .order_by("submission_type")
        )
        return [
            {"slug": slugify(t["submission_type"]), "name": t["submission_type"], "count": t["count"]} for t in types
        ]

    def dispatch(self, request: HttpRequest, *args: str, **kwargs: str) -> HttpResponse:
        """Resolve the conference and enforce permissions before dispatch.

        The conference is resolved and permissions checked after the
        ``LoginRequiredMixin`` verifies authentication but before the
        view logic executes.  If the user is not authenticated,
        ``LoginRequiredMixin`` handles the redirect and we skip
        conference resolution entirely.

        Args:
            request: The incoming HTTP request.
            *args: Positional arguments from the URL resolver.
            **kwargs: Keyword arguments from the URL pattern.

        Returns:
            The HTTP response from the downstream view.

        Raises:
            PermissionDenied: If the user is not authorized.
        """
        if not request.user.is_authenticated:
            return self.handle_no_permission()  # type: ignore[return-value]

        self.conference = get_object_or_404(Conference, slug=kwargs.get("conference_slug", ""))

        if not (request.user.is_superuser or request.user.has_perm("program_conference.change_conference")):
            raise PermissionDenied

        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add the conference and sidebar metadata to the template context.

        Includes ``submission_type_nav`` for the sidebar's dynamic Talks
        sub-menu.

        Args:
            **kwargs: Additional context data.

        Returns:
            The template context dict with the conference included.
        """
        context: dict[str, object] = super().get_context_data(**kwargs)  # type: ignore[misc]
        context["conference"] = self.conference
        context["submission_type_nav"] = self.get_submission_type_nav()
        context["last_synced"] = self._get_last_synced()
        return context

    def _get_last_synced(self) -> object:
        """Find the most recent synced_at timestamp across all synced models."""
        latest_values = []
        for model in (Room, Speaker, Talk, ScheduleSlot):
            latest = (
                model.objects.filter(conference=self.conference, synced_at__isnull=False)
                .order_by("-synced_at")
                .values_list("synced_at", flat=True)
                .first()
            )
            if latest:
                latest_values.append(latest)
        return max(latest_values) if latest_values else None


class ConferenceListView(LoginRequiredMixin, ListView):
    """List all conferences visible to the current user.

    Superusers see every conference.  Staff users see all active
    conferences.  Other authenticated users are denied access.
    """

    template_name = "django_program/manage/conference_list.html"
    context_object_name = "conferences"
    paginate_by = 25

    def dispatch(self, request: HttpRequest, *args: str, **kwargs: str) -> HttpResponse:
        """Check that the user is a superuser or staff member.

        Authentication is checked first; if the user is not logged in,
        ``LoginRequiredMixin`` handles the redirect.

        Args:
            request: The incoming HTTP request.
            *args: Positional arguments from the URL resolver.
            **kwargs: Keyword arguments from the URL pattern.

        Returns:
            The HTTP response.

        Raises:
            PermissionDenied: If the user is not superuser or staff.
        """
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        if not (request.user.is_superuser or request.user.is_staff):
            raise PermissionDenied

        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[Conference]:
        """Return conferences visible to the current user.

        Superusers see all conferences; staff see active conferences only.

        Returns:
            A queryset of Conference instances.
        """
        if self.request.user.is_superuser:
            return Conference.objects.all()
        return Conference.objects.filter(is_active=True)


class ImportFromPretalxView(LoginRequiredMixin, TemplateView):
    """Import a new conference by fetching event metadata from Pretalx.

    Presents a form to enter a Pretalx event slug.  On POST, fetches event
    metadata from the Pretalx API, creates a Conference object, and runs
    a full sync of rooms, speakers, talks, and schedule.
    """

    template_name = "django_program/manage/import_pretalx.html"

    def dispatch(self, request: HttpRequest, *args: str, **kwargs: str) -> HttpResponse:
        """Check that the user is a superuser or staff member.

        Args:
            request: The incoming HTTP request.
            *args: Positional arguments from the URL resolver.
            **kwargs: Keyword arguments from the URL pattern.

        Returns:
            The HTTP response.

        Raises:
            PermissionDenied: If the user is not superuser or staff.
        """
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        if not (request.user.is_superuser or request.user.is_staff):
            raise PermissionDenied

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add the import form to the template context.

        Returns:
            Context dict with the form and token status included.
        """
        context = super().get_context_data(**kwargs)
        context.setdefault("form", ImportFromPretalxForm())
        config = get_config()
        context["has_configured_token"] = bool(config.pretalx.token)
        return context

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Handle the import form submission.

        Fetches event metadata from Pretalx, creates the Conference,
        and runs a full sync.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments (unused).

        Returns:
            A redirect to the new conference dashboard on success,
            or re-renders the form with errors.
        """
        form = ImportFromPretalxForm(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        pretalx_slug = form.cleaned_data["pretalx_event_slug"]
        conference_slug = form.cleaned_data.get("conference_slug") or pretalx_slug

        if Conference.objects.filter(slug=conference_slug).exists():
            form.add_error(
                "conference_slug",
                f'A conference with slug "{conference_slug}" already exists.',
            )
            return self.render_to_response(self.get_context_data(form=form))

        config = get_config()
        base_url = config.pretalx.base_url
        api_token = form.cleaned_data.get("api_token") or config.pretalx.token or ""

        client = PretalxClient(pretalx_slug, base_url=base_url, api_token=api_token)

        try:
            event_data = client.fetch_event()
        except RuntimeError as exc:
            error_msg = str(exc)
            if "404" in error_msg:
                hint = (
                    f'Event "{pretalx_slug}" not found. Check the slug matches the Pretalx URL '
                    f"(e.g. pretalx.com/<slug>/) and that your API token is configured "
                    f"(token {'is' if api_token else 'is NOT'} set)."
                )
            else:
                hint = f"Could not fetch event from Pretalx: {error_msg}"
            form.add_error("pretalx_event_slug", hint)
            return self.render_to_response(self.get_context_data(form=form))

        event_name = _localized(event_data.get("name")) or pretalx_slug
        date_from = event_data.get("date_from", "")
        date_to = event_data.get("date_to", "")
        tz = event_data.get("timezone", "UTC")

        if not date_from or not date_to:
            form.add_error(
                "pretalx_event_slug",
                "Event is missing date_from or date_to in the Pretalx API response.",
            )
            return self.render_to_response(self.get_context_data(form=form))

        conference = Conference.objects.create(
            name=event_name,
            slug=conference_slug,
            start_date=date_from,
            end_date=date_to,
            timezone=tz,
            pretalx_event_slug=pretalx_slug,
            is_active=True,
        )

        try:
            service = PretalxSyncService(conference)
            results = service.sync_all()
            messages.success(
                request,
                f'Imported "{event_name}" from Pretalx: '
                f"{results['rooms']} rooms, "
                f"{results['speakers']} speakers, "
                f"{results['talks']} talks, "
                f"{results['schedule_slots']} schedule slots.",
            )
        except (ValueError, RuntimeError) as exc:
            messages.warning(
                request,
                f"Conference created but sync failed: {exc}. You can retry from the dashboard.",
            )

        return redirect("manage:dashboard", conference_slug=conference.slug)


class ImportPretalxStreamView(LoginRequiredMixin, View):
    """Stream Pretalx import progress via Server-Sent Events.

    Returns a ``StreamingHttpResponse`` with ``text/event-stream`` content
    type.  Each import step (fetch metadata, create conference, sync rooms,
    speakers, talks, schedule) emits an SSE event so the client can render
    a live progress bar.
    """

    def dispatch(self, request: HttpRequest, *args: str, **kwargs: str) -> HttpResponse:
        """Enforce staff/superuser permissions."""
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not (request.user.is_superuser or request.user.is_staff):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def post(self, request: HttpRequest, **kwargs: str) -> StreamingHttpResponse:  # noqa: ARG002
        """Start the streaming import and return an SSE response."""
        response = StreamingHttpResponse(
            self._import_stream(request),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response

    @staticmethod
    def _sse(data: dict[str, object]) -> str:
        """Format a dict as an SSE data line."""
        return f"data: {json.dumps(data)}\n\n"

    def _import_stream(self, request: HttpRequest) -> Iterator[str]:
        """Generator that performs the import and yields SSE events."""
        form = ImportFromPretalxForm(request.POST)
        if not form.is_valid():
            errors = "; ".join(f"{field}: {', '.join(errs)}" for field, errs in form.errors.items())
            yield self._sse({"status": "error", "message": f"Validation failed: {errors}"})
            return

        pretalx_slug = form.cleaned_data["pretalx_event_slug"]
        conference_slug = form.cleaned_data.get("conference_slug") or pretalx_slug

        if Conference.objects.filter(slug=conference_slug).exists():
            yield self._sse(
                {
                    "status": "error",
                    "message": f'Conference "{conference_slug}" already exists.',
                }
            )
            return

        config = get_config()
        api_token = form.cleaned_data.get("api_token") or config.pretalx.token or ""

        yield from self._stream_fetch_and_sync(
            pretalx_slug,
            conference_slug,
            config.pretalx.base_url,
            api_token,
        )

    def _stream_fetch_and_sync(
        self,
        pretalx_slug: str,
        conference_slug: str,
        base_url: str,
        api_token: str,
    ) -> Iterator[str]:
        """Fetch event metadata, create conference, and sync entities."""
        total = 6

        # Step 1: Fetch event metadata
        yield self._sse(
            {
                "step": 1,
                "total": total,
                "label": "Fetching event metadata...",
                "status": "in_progress",
            }
        )
        try:
            client = PretalxClient(pretalx_slug, base_url=base_url, api_token=api_token)
            event_data = client.fetch_event()
        except RuntimeError as exc:
            error_msg = str(exc)
            hint = (
                f'Event "{pretalx_slug}" not found. Check the slug and API token.'
                if "404" in error_msg
                else f"Failed to fetch event: {error_msg}"
            )
            yield self._sse({"status": "error", "message": hint, "step": 1})
            return
        yield self._sse(
            {
                "step": 1,
                "total": total,
                "label": "Fetched event metadata",
                "status": "done",
            }
        )

        # Step 2: Create conference
        yield self._sse(
            {
                "step": 2,
                "total": total,
                "label": "Creating conference...",
                "status": "in_progress",
            }
        )
        event_name = _localized(event_data.get("name")) or pretalx_slug
        date_from = event_data.get("date_from", "")
        date_to = event_data.get("date_to", "")
        tz = event_data.get("timezone", "UTC")

        if not date_from or not date_to:
            yield self._sse(
                {
                    "status": "error",
                    "message": "Event missing date_from or date_to.",
                    "step": 2,
                }
            )
            return

        conference = Conference.objects.create(
            name=event_name,
            slug=conference_slug,
            start_date=date_from,
            end_date=date_to,
            timezone=tz,
            pretalx_event_slug=pretalx_slug,
            is_active=True,
        )
        yield self._sse(
            {
                "step": 2,
                "total": total,
                "label": f'Created "{event_name}"',
                "status": "done",
            }
        )

        # Step 3-6: Sync entities
        yield from self._stream_sync_entities(conference, event_name, total)

    def _stream_sync_entities(
        self,
        conference: Conference,
        event_name: str,
        total: int,
    ) -> Iterator[str]:
        """Run each sync step and yield progress events."""
        try:
            service = PretalxSyncService(conference)
        except ValueError as exc:
            yield self._sse({"status": "error", "message": str(exc), "step": 3})
            url = reverse("manage:dashboard", kwargs={"conference_slug": conference.slug})
            yield self._sse(
                {
                    "status": "complete",
                    "redirect": url,
                    "warning": True,
                    "message": f"Conference created but sync failed: {exc}",
                }
            )
            return

        sync_steps = [
            (3, "rooms", service.sync_rooms, None),
            (4, "speakers", service.sync_speakers, service.sync_speakers_iter),
            (5, "talks", service.sync_talks, service.sync_talks_iter),
            (6, "schedule slots", service.sync_schedule, None),
        ]

        counts: dict[str, int] = {}
        had_errors = False
        for step_num, entity_name, sync_fn, iter_fn in sync_steps:
            yield self._sse(
                {
                    "step": step_num,
                    "total": total,
                    "label": f"Syncing {entity_name}...",
                    "status": "in_progress",
                }
            )
            try:
                if iter_fn is not None:
                    count = 0
                    for progress in iter_fn():
                        if "count" in progress:
                            count = int(progress["count"])
                        elif progress.get("phase") == "fetching":
                            yield self._sse(
                                {
                                    "step": step_num,
                                    "total": total,
                                    "label": f"Fetching {entity_name} from API...",
                                    "status": "in_progress",
                                }
                            )
                        else:
                            yield self._sse(
                                {
                                    "step": step_num,
                                    "total": total,
                                    "label": (f"Syncing {entity_name}... ({progress['current']}/{progress['total']})"),
                                    "status": "in_progress",
                                }
                            )
                else:
                    result = sync_fn()
                    if isinstance(result, tuple):
                        count, skipped = result
                    else:
                        count = result
                        skipped = 0
                counts[entity_name] = count
                label = f"Synced {count} {entity_name}"
                if skipped:
                    label += f" ({skipped} unscheduled)"
                yield self._sse(
                    {
                        "step": step_num,
                        "total": total,
                        "label": label,
                        "status": "done",
                    }
                )
            except (RuntimeError, ValueError) as exc:
                counts[entity_name] = 0
                had_errors = True
                yield self._sse(
                    {
                        "step": step_num,
                        "total": total,
                        "label": f"Failed: {entity_name}",
                        "status": "step_error",
                        "detail": str(exc),
                    }
                )

        redirect_url = reverse("manage:dashboard", kwargs={"conference_slug": conference.slug})
        summary = ", ".join(f"{count} {name}" for name, count in counts.items())
        yield self._sse(
            {
                "status": "complete",
                "message": f'Imported "{event_name}": {summary}.',
                "redirect": redirect_url,
                "warning": had_errors,
            }
        )


class DashboardView(ManagePermissionMixin, TemplateView):
    """Conference dashboard with summary statistics.

    Displays counts of rooms, speakers, talks, schedule slots, and
    sections for the selected conference.
    """

    template_name = "django_program/manage/dashboard.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Build dashboard context with summary statistics.

        Returns:
            Context dict containing ``conference``, ``stats``,
            ``last_synced``, and ``active_nav``.
        """
        context = super().get_context_data(**kwargs)
        conference = self.conference
        context["active_nav"] = "dashboard"
        context["stats"] = {
            "rooms": Room.objects.filter(conference=conference).count(),
            "speakers": Speaker.objects.filter(conference=conference).count(),
            "talks": Talk.objects.filter(conference=conference).count(),
            "schedule_slots": ScheduleSlot.objects.filter(conference=conference).count(),
            "sections": Section.objects.filter(conference=conference).count(),
            "unscheduled_talks": Talk.objects.filter(conference=conference, slot_start__isnull=True).count(),
            "sponsors": Sponsor.objects.filter(conference=conference).count(),
            "sponsor_levels": SponsorLevel.objects.filter(conference=conference).count(),
            "activities": Activity.objects.filter(conference=conference).count(),
            "travel_grants": TravelGrant.objects.filter(conference=conference).count(),
            "ticket_types": TicketType.objects.filter(conference=conference).count(),
            "addons": AddOn.objects.filter(conference=conference).count(),
            "vouchers": Voucher.objects.filter(conference=conference).count(),
            "orders": Order.objects.filter(conference=conference).count(),
            "paid_orders": Order.objects.filter(conference=conference, status=Order.Status.PAID).count(),
        }

        sponsor_profile = resolve_sponsor_profile(
            event_slug=conference.pretalx_event_slug or "",
            conference_slug=str(conference.slug),
        )
        context["has_psf_sponsor_sync"] = sponsor_profile.has_api_sync

        return context


class ConferenceEditView(ManagePermissionMixin, UpdateView):
    """Edit conference details.

    Stripe keys are excluded from the form for security.  On success
    the user is redirected back to the dashboard with a flash message.
    """

    template_name = "django_program/manage/conference_edit.html"
    form_class = ConferenceForm
    context_object_name = "conference"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` to the template context.

        Returns:
            Context dict with sidebar active state set.
        """
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "conference-edit"
        return context

    def get_object(self, queryset: QuerySet[Conference] | None = None) -> Conference:  # noqa: ARG002
        """Return the conference resolved by the mixin.

        Returns:
            The current conference instance.
        """
        return self.conference

    def get_success_url(self) -> str:
        """Redirect to the conference dashboard after a successful save.

        Returns:
            URL of the conference dashboard.
        """
        return reverse("manage:dashboard", kwargs={"conference_slug": self.conference.slug})

    def form_valid(self, form: ConferenceForm) -> HttpResponse:
        """Save the form and add a success message.

        Args:
            form: The validated conference form.

        Returns:
            A redirect response to the success URL.
        """
        messages.success(self.request, "Conference updated successfully.")
        return super().form_valid(form)


class SectionListView(ManagePermissionMixin, ListView):
    """List sections for the current conference."""

    template_name = "django_program/manage/section_list.html"
    context_object_name = "sections"
    paginate_by = 50

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "sections"
        return context

    def get_queryset(self) -> QuerySet[Section]:
        """Return sections belonging to the current conference.

        Returns:
            A queryset of Section instances ordered by position and date.
        """
        return Section.objects.filter(conference=self.conference)


class SectionEditView(ManagePermissionMixin, UpdateView):
    """Edit a section belonging to the current conference."""

    template_name = "django_program/manage/section_edit.html"
    form_class = SectionForm
    context_object_name = "section"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "sections"
        return context

    def get_queryset(self) -> QuerySet[Section]:
        """Scope the queryset to the current conference.

        Returns:
            A queryset of Section instances for this conference.
        """
        return Section.objects.filter(conference=self.conference)

    def get_form_kwargs(self) -> dict[str, Any]:
        """Pass the conference to the form."""
        kwargs = super().get_form_kwargs()
        kwargs["conference"] = self.conference
        return kwargs

    def get_success_url(self) -> str:
        """Redirect to the section list after a successful save.

        Returns:
            URL of the section list view.
        """
        return reverse("manage:section-list", kwargs={"conference_slug": self.conference.slug})

    def form_valid(self, form: SectionForm) -> HttpResponse:
        """Re-generate slug from name and save."""
        form.instance.slug = _unique_section_slug(form.instance.name, self.conference, exclude_pk=form.instance.pk)
        messages.success(self.request, "Section updated successfully.")
        return super().form_valid(form)


class SectionCreateView(ManagePermissionMixin, CreateView):
    """Create a new section for the current conference."""

    template_name = "django_program/manage/section_edit.html"
    form_class = SectionForm

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` and ``is_create`` to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "sections"
        context["is_create"] = True
        return context

    def get_form_kwargs(self) -> dict[str, Any]:
        """Pass the conference to the form."""
        kwargs = super().get_form_kwargs()
        kwargs["conference"] = self.conference
        return kwargs

    def form_valid(self, form: SectionForm) -> HttpResponse:
        """Assign the conference and auto-generate slug before saving."""
        form.instance.conference = self.conference
        form.instance.slug = _unique_section_slug(form.instance.name, self.conference)
        messages.success(self.request, "Section created successfully.")
        return super().form_valid(form)

    def get_success_url(self) -> str:
        """Redirect to the section list after creation."""
        return reverse("manage:section-list", kwargs={"conference_slug": self.conference.slug})


class RoomListView(ManagePermissionMixin, ListView):
    """List rooms for the current conference, ordered by position."""

    template_name = "django_program/manage/room_list.html"
    context_object_name = "rooms"
    paginate_by = 50

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "rooms"
        return context

    def get_queryset(self) -> QuerySet[Room]:
        """Return rooms belonging to the current conference.

        Returns:
            A queryset of Room instances ordered by position.
        """
        return Room.objects.filter(conference=self.conference).order_by("position", "name")


class RoomEditView(ManagePermissionMixin, UpdateView):
    """Edit a room belonging to the current conference.

    Fields synced from Pretalx are disabled when the room has a
    ``synced_at`` timestamp.
    """

    template_name = "django_program/manage/room_edit.html"
    form_class = RoomForm
    context_object_name = "room"

    def get_queryset(self) -> QuerySet[Room]:
        """Scope the queryset to the current conference.

        Returns:
            A queryset of Room instances for this conference.
        """
        return Room.objects.filter(conference=self.conference)

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` and ``is_synced`` to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "rooms"
        context["is_synced"] = self.object.synced_at is not None
        return context

    def get_form_kwargs(self) -> dict[str, Any]:
        """Pass the sync status to the form.

        Returns:
            Form keyword arguments including ``is_synced``.
        """
        kwargs = super().get_form_kwargs()
        kwargs["is_synced"] = self.object.synced_at is not None
        return kwargs

    def get_success_url(self) -> str:
        """Redirect to the room list after a successful save.

        Returns:
            URL of the room list view.
        """
        return reverse("manage:room-list", kwargs={"conference_slug": self.conference.slug})

    def form_valid(self, form: RoomForm) -> HttpResponse:
        """Save the form and add a success message.

        Args:
            form: The validated room form.

        Returns:
            A redirect response to the success URL.
        """
        messages.success(self.request, "Room updated successfully.")
        return super().form_valid(form)


class RoomCreateView(ManagePermissionMixin, CreateView):
    """Create a new room for the current conference."""

    template_name = "django_program/manage/room_edit.html"
    form_class = RoomForm

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` and ``is_create`` to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "rooms"
        context["is_create"] = True
        context["is_synced"] = False
        return context

    def get_form_kwargs(self) -> dict[str, Any]:
        """Pass is_synced=False so all fields are editable."""
        kwargs = super().get_form_kwargs()
        kwargs["is_synced"] = False
        return kwargs

    def form_valid(self, form: RoomForm) -> HttpResponse:
        """Assign the conference before saving."""
        form.instance.conference = self.conference
        messages.success(self.request, "Room created successfully.")
        return super().form_valid(form)

    def get_success_url(self) -> str:
        """Redirect to the room list after creation."""
        return reverse("manage:room-list", kwargs={"conference_slug": self.conference.slug})


class SpeakerListView(ManagePermissionMixin, ListView):
    """List speakers for the current conference.

    Supports search via the ``q`` GET parameter, filtering by name or
    email.  This is a read-only view since speaker data comes from
    Pretalx.
    """

    template_name = "django_program/manage/speaker_list.html"
    context_object_name = "speakers"
    paginate_by = 50

    def get_queryset(self) -> QuerySet[Speaker]:
        """Return speakers filtered by the optional search query.

        Returns:
            A queryset of Speaker instances for this conference.
        """
        qs = Speaker.objects.filter(conference=self.conference).annotate(talk_count=Count("talks", distinct=True))
        query = self.request.GET.get("q", "").strip()
        if query:
            qs = qs.filter(Q(name__icontains=query) | Q(email__icontains=query))
        return qs.order_by("-talk_count", "name")

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add the search query and active nav to the template context.

        Returns:
            Context dict with ``search_query`` and ``active_nav`` included.
        """
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "speakers"
        context["search_query"] = self.request.GET.get("q", "")
        return context


class SpeakerDetailView(ManagePermissionMixin, DetailView):
    """Read-only detail view for a speaker in the current conference."""

    template_name = "django_program/manage/speaker_detail.html"
    context_object_name = "speaker"

    def get_queryset(self) -> QuerySet[Speaker]:
        """Scope speaker lookup to the current conference and preload talks."""
        return (
            Speaker.objects.filter(conference=self.conference)
            .prefetch_related("talks")
            .annotate(talk_count=Count("talks", distinct=True))
        )

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add active nav and related talks ordered by schedule/title."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "speakers"
        context["speaker_talks"] = self.object.talks.select_related("room").order_by("slot_start", "title")
        return context


class TalkListView(ManagePermissionMixin, ListView):
    """List talks for the current conference.

    Supports search via ``q`` (title search), filtering via ``state``
    GET parameter, and filtering by submission type via URL slug.
    """

    template_name = "django_program/manage/talk_list.html"
    context_object_name = "talks"
    paginate_by = 50

    def _get_type_filter(self) -> str:
        """Resolve the submission type filter from the URL slug.

        Matches the URL ``type_slug`` against slugified submission type
        names for this conference.

        Returns:
            The original submission_type string, or empty if no match.
        """
        type_slug = self.kwargs.get("type_slug", "")
        if not type_slug:
            return ""
        types = (
            Talk.objects.filter(conference=self.conference)
            .exclude(submission_type="")
            .values_list("submission_type", flat=True)
            .distinct()
        )
        for sub_type in types:
            if slugify(sub_type) == type_slug:
                return sub_type
        return ""

    def get_queryset(self) -> QuerySet[Talk]:
        """Return talks filtered by optional search, state, and type parameters.

        Returns:
            A queryset of Talk instances for this conference.
        """
        qs = (
            Talk.objects.filter(conference=self.conference)
            .select_related("room")
            .prefetch_related("speakers")
            .order_by("slot_start", "title")
        )
        type_filter = self._get_type_filter()
        if type_filter:
            qs = qs.filter(submission_type=type_filter)
        query = self.request.GET.get("q", "").strip()
        if query:
            qs = qs.filter(title__icontains=query)
        state = self.request.GET.get("state", "").strip()
        if state:
            qs = qs.filter(state=state)
        scheduled = self.request.GET.get("scheduled", "").strip()
        if scheduled == "no":
            qs = qs.filter(slot_start__isnull=True)
        elif scheduled == "yes":
            qs = qs.filter(slot_start__isnull=False)
        return qs

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add search query, state filter, type filter, and available states to context.

        Returns:
            Context dict with filter parameters included.
        """
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "talks"
        type_filter = self._get_type_filter()
        context["current_type"] = type_filter
        context["current_type_slug"] = self.kwargs.get("type_slug", "")
        context["search_query"] = self.request.GET.get("q", "")
        context["current_state"] = self.request.GET.get("state", "")
        context["current_scheduled"] = self.request.GET.get("scheduled", "")
        context["available_states"] = (
            Talk.objects.filter(conference=self.conference).values_list("state", flat=True).distinct().order_by("state")
        )
        return context


class TalkDetailView(ManagePermissionMixin, DetailView):
    """Read-only detail view for a talk in the current conference."""

    template_name = "django_program/manage/talk_detail.html"
    context_object_name = "talk"

    def get_queryset(self) -> QuerySet[Talk]:
        """Scope talk lookup to conference and preload related speaker/room data."""
        return (
            Talk.objects.filter(conference=self.conference)
            .select_related("room")
            .prefetch_related("speakers", "schedule_slots")
        )

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add active nav and ordered schedule slots for this talk."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "talks"
        context["talk_slots"] = self.object.schedule_slots.select_related("room").order_by("start")
        return context


class TalkEditView(ManagePermissionMixin, UpdateView):
    """Edit a talk belonging to the current conference.

    Pretalx-synced fields are disabled when the talk has a
    ``synced_at`` timestamp.
    """

    template_name = "django_program/manage/talk_edit.html"
    form_class = TalkForm
    context_object_name = "talk"

    def get_queryset(self) -> QuerySet[Talk]:
        """Scope the queryset to the current conference.

        Returns:
            A queryset of Talk instances for this conference.
        """
        return Talk.objects.filter(conference=self.conference).prefetch_related("speakers")

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav``, ``is_synced``, and ``synced_fields`` to context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "talks"
        context["is_synced"] = self.object.synced_at is not None
        context["synced_fields"] = TalkForm.SYNCED_FIELDS
        return context

    def get_form_kwargs(self) -> dict[str, Any]:
        """Pass the sync status to the form.

        Returns:
            Form keyword arguments including ``is_synced``.
        """
        kwargs = super().get_form_kwargs()
        kwargs["is_synced"] = self.object.synced_at is not None
        return kwargs

    def get_success_url(self) -> str:
        """Redirect to the talk list after a successful save.

        Returns:
            URL of the talk list view.
        """
        return reverse("manage:talk-list", kwargs={"conference_slug": self.conference.slug})

    def form_valid(self, form: TalkForm) -> HttpResponse:
        """Save the form and add a success message.

        Args:
            form: The validated talk form.

        Returns:
            A redirect response to the success URL.
        """
        messages.success(self.request, "Talk updated successfully.")
        return super().form_valid(form)


class ScheduleSlotListView(ManagePermissionMixin, ListView):
    """List schedule slots for the current conference, grouped by date."""

    template_name = "django_program/manage/schedule_list.html"
    context_object_name = "slots"
    paginate_by = 200

    def get_queryset(self) -> QuerySet[ScheduleSlot]:
        """Return schedule slots with related talk and room data.

        Returns:
            A queryset of ScheduleSlot instances for this conference.
        """
        return (
            ScheduleSlot.objects.filter(conference=self.conference)
            .select_related("talk", "room")
            .order_by("start", "room__position", "room__name")
        )

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` and ``grouped_slots`` to the template context.

        Groups the paginated slot queryset by date for display with
        date header rows in the template.
        """
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "schedule"

        # Group slots by date for visual date headers in the template.
        slot_qs = self.get_queryset()
        grouped: list[tuple[object, list[ScheduleSlot]]] = []
        for day, group in itertools.groupby(slot_qs, key=lambda s: localdate(s.start)):
            grouped.append((day, list(group)))
        context["grouped_slots"] = grouped

        return context


class ScheduleSlotEditView(ManagePermissionMixin, UpdateView):
    """Edit a schedule slot belonging to the current conference.

    Pretalx-synced fields are disabled when the slot has a
    ``synced_at`` timestamp.
    """

    template_name = "django_program/manage/slot_edit.html"
    form_class = ScheduleSlotForm
    context_object_name = "slot"

    def get_queryset(self) -> QuerySet[ScheduleSlot]:
        """Scope the queryset to the current conference.

        Returns:
            A queryset of ScheduleSlot instances for this conference.
        """
        return ScheduleSlot.objects.filter(conference=self.conference).select_related("talk", "room")

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav``, ``is_synced``, and ``synced_fields`` to context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "schedule"
        context["is_synced"] = self.object.synced_at is not None
        context["synced_fields"] = ScheduleSlotForm.SYNCED_FIELDS
        return context

    def get_form_kwargs(self) -> dict[str, Any]:
        """Pass the sync status to the form.

        Returns:
            Form keyword arguments including ``is_synced``.
        """
        kwargs = super().get_form_kwargs()
        kwargs["is_synced"] = self.object.synced_at is not None
        return kwargs

    def get_success_url(self) -> str:
        """Redirect to the schedule list after a successful save.

        Returns:
            URL of the schedule list view.
        """
        return reverse("manage:schedule-list", kwargs={"conference_slug": self.conference.slug})

    def form_valid(self, form: ScheduleSlotForm) -> HttpResponse:
        """Save the form and add a success message.

        Args:
            form: The validated schedule slot form.

        Returns:
            A redirect response to the success URL.
        """
        messages.success(self.request, "Schedule slot updated successfully.")
        return super().form_valid(form)


class SponsorLevelListView(ManagePermissionMixin, ListView):
    """List sponsor levels for the current conference."""

    template_name = "django_program/manage/sponsor_level_list.html"
    context_object_name = "levels"
    paginate_by = 50

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "sponsor-levels"
        return context

    def get_queryset(self) -> QuerySet[SponsorLevel]:
        """Return sponsor levels for the current conference."""
        return (
            SponsorLevel.objects.filter(conference=self.conference)
            .annotate(sponsor_count=Count("sponsors"))
            .order_by("order", "name")
        )


class SponsorLevelEditView(ManagePermissionMixin, UpdateView):
    """Edit a sponsor level."""

    template_name = "django_program/manage/sponsor_level_edit.html"
    form_class = SponsorLevelForm
    context_object_name = "level"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "sponsor-levels"
        return context

    def get_queryset(self) -> QuerySet[SponsorLevel]:
        """Scope to the current conference."""
        return SponsorLevel.objects.filter(conference=self.conference)

    def get_success_url(self) -> str:
        """Redirect to the sponsor level list."""
        return reverse("manage:sponsor-level-list", kwargs={"conference_slug": self.conference.slug})

    def form_valid(self, form: SponsorLevelForm) -> HttpResponse:
        """Save and flash success."""
        messages.success(self.request, "Sponsor level updated successfully.")
        return super().form_valid(form)


class SponsorLevelCreateView(ManagePermissionMixin, CreateView):
    """Create a new sponsor level."""

    template_name = "django_program/manage/sponsor_level_edit.html"
    form_class = SponsorLevelForm

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` and ``is_create`` to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "sponsor-levels"
        context["is_create"] = True
        return context

    def form_valid(self, form: SponsorLevelForm) -> HttpResponse:
        """Assign the conference before saving."""
        form.instance.conference = self.conference
        messages.success(self.request, "Sponsor level created successfully.")
        return super().form_valid(form)

    def get_success_url(self) -> str:
        """Redirect to the sponsor level list."""
        return reverse("manage:sponsor-level-list", kwargs={"conference_slug": self.conference.slug})


class SponsorManageListView(ManagePermissionMixin, ListView):
    """List sponsors for the current conference."""

    template_name = "django_program/manage/sponsor_list.html"
    context_object_name = "sponsors"
    paginate_by = 50

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "sponsors"
        return context

    def get_queryset(self) -> QuerySet[Sponsor]:
        """Return sponsors for the current conference."""
        return (
            Sponsor.objects.filter(conference=self.conference).select_related("level").order_by("level__order", "name")
        )


class SponsorEditView(ManagePermissionMixin, UpdateView):
    """Edit a sponsor.

    Fields synced from the PSF API are disabled when the sponsor has
    an ``external_id``.
    """

    template_name = "django_program/manage/sponsor_edit.html"
    form_class = SponsorForm
    context_object_name = "sponsor"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav``, sync status, and benefits to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "sponsors"
        context["benefits"] = self.object.benefits.all()
        context["is_synced"] = bool(self.object.external_id)
        context["synced_fields"] = SponsorForm.SYNCED_FIELDS
        return context

    def get_queryset(self) -> QuerySet[Sponsor]:
        """Scope to the current conference."""
        return Sponsor.objects.filter(conference=self.conference).select_related("level")

    def get_form_kwargs(self) -> dict[str, Any]:
        """Pass the sync status to the form."""
        kwargs = super().get_form_kwargs()
        kwargs["is_synced"] = bool(self.object.external_id)
        return kwargs

    def get_form(self, form_class: type[SponsorForm] | None = None) -> SponsorForm:
        """Scope the level queryset to the current conference."""
        form = super().get_form(form_class)
        form.fields["level"].queryset = SponsorLevel.objects.filter(conference=self.conference)
        return form

    def get_success_url(self) -> str:
        """Redirect to the sponsor list."""
        return reverse("manage:sponsor-manage-list", kwargs={"conference_slug": self.conference.slug})

    def form_valid(self, form: SponsorForm) -> HttpResponse:
        """Save and flash success."""
        messages.success(self.request, "Sponsor updated successfully.")
        return super().form_valid(form)


class SponsorCreateView(ManagePermissionMixin, CreateView):
    """Create a new sponsor."""

    template_name = "django_program/manage/sponsor_edit.html"
    form_class = SponsorForm

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` and ``is_create`` to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "sponsors"
        context["is_create"] = True
        context["is_synced"] = False
        return context

    def get_form_kwargs(self) -> dict[str, Any]:
        """Pass is_synced=False so all fields are editable."""
        kwargs = super().get_form_kwargs()
        kwargs["is_synced"] = False
        return kwargs

    def get_form(self, form_class: type[SponsorForm] | None = None) -> SponsorForm:
        """Scope the level queryset to the current conference."""
        form = super().get_form(form_class)
        form.fields["level"].queryset = SponsorLevel.objects.filter(conference=self.conference)
        return form

    def form_valid(self, form: SponsorForm) -> HttpResponse:
        """Assign the conference before saving."""
        form.instance.conference = self.conference
        messages.success(self.request, "Sponsor created successfully.")
        return super().form_valid(form)

    def get_success_url(self) -> str:
        """Redirect to the sponsor list."""
        return reverse("manage:sponsor-manage-list", kwargs={"conference_slug": self.conference.slug})


class ActivityManageListView(ManagePermissionMixin, ListView):
    """List activities for the current conference."""

    template_name = "django_program/manage/activity_list.html"
    context_object_name = "activities"
    paginate_by = 50

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "activities"
        return context

    def get_queryset(self) -> QuerySet[Activity]:
        """Return activities for the current conference.

        Annotates each activity with ``signup_count`` (confirmed only)
        and ``waitlist_count`` to avoid N+1 queries.
        """
        return (
            Activity.objects.filter(conference=self.conference)
            .select_related("room")
            .annotate(
                signup_count=Count(
                    "signups",
                    filter=models.Q(signups__status=ActivitySignup.SignupStatus.CONFIRMED),
                ),
                waitlist_count=Count(
                    "signups",
                    filter=models.Q(signups__status=ActivitySignup.SignupStatus.WAITLISTED),
                ),
            )
            .order_by("start_time", "name")
        )


class ActivityEditView(ManagePermissionMixin, UpdateView):
    """Edit an activity."""

    template_name = "django_program/manage/activity_edit.html"
    form_class = ActivityForm
    context_object_name = "activity"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` and signup counts to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "activities"
        context["signup_count"] = self.object.signups.filter(status=ActivitySignup.SignupStatus.CONFIRMED).count()
        context["waitlist_count"] = self.object.signups.filter(status=ActivitySignup.SignupStatus.WAITLISTED).count()
        return context

    def get_queryset(self) -> QuerySet[Activity]:
        """Scope to the current conference."""
        return Activity.objects.filter(conference=self.conference)

    def get_form(self, form_class: type[ActivityForm] | None = None) -> ActivityForm:
        """Scope the room queryset to the current conference."""
        form = super().get_form(form_class)
        form.fields["room"].queryset = Room.objects.filter(conference=self.conference)
        return form

    def get_success_url(self) -> str:
        """Redirect to the activity list."""
        return reverse("manage:activity-list", kwargs={"conference_slug": self.conference.slug})

    def form_valid(self, form: ActivityForm) -> HttpResponse:
        """Re-generate slug from name and save."""
        form.instance.slug = _unique_activity_slug(form.instance.name, self.conference, exclude_pk=form.instance.pk)
        messages.success(self.request, "Activity updated successfully.")
        return super().form_valid(form)


class ActivityCreateView(ManagePermissionMixin, CreateView):
    """Create a new activity."""

    template_name = "django_program/manage/activity_edit.html"
    form_class = ActivityForm

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` and ``is_create`` to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "activities"
        context["is_create"] = True
        return context

    def get_form(self, form_class: type[ActivityForm] | None = None) -> ActivityForm:
        """Scope the room queryset to the current conference."""
        form = super().get_form(form_class)
        form.fields["room"].queryset = Room.objects.filter(conference=self.conference)
        return form

    def form_valid(self, form: ActivityForm) -> HttpResponse:
        """Assign the conference and auto-generate slug before saving."""
        form.instance.conference = self.conference
        form.instance.slug = _unique_activity_slug(form.instance.name, self.conference)
        messages.success(self.request, "Activity created successfully.")
        return super().form_valid(form)

    def get_success_url(self) -> str:
        """Redirect to the activity list."""
        return reverse("manage:activity-list", kwargs={"conference_slug": self.conference.slug})


class RoomSearchView(ManagePermissionMixin, View):
    """JSON API endpoint for room autocomplete within a conference."""

    def get(self, request: HttpRequest, **kwargs: str) -> JsonResponse:  # noqa: ARG002
        """Search rooms by name for the current conference.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments (unused).

        Returns:
            A JsonResponse with a list of matching rooms.
        """
        q = request.GET.get("q", "").strip()
        rooms = Room.objects.filter(conference=self.conference).order_by("position", "name")
        if q:
            rooms = rooms.filter(name__icontains=q)
        results = [{"id": room.pk, "name": str(room.name)} for room in rooms[:20]]
        return JsonResponse(results, safe=False)


class TravelGrantManageListView(ManagePermissionMixin, ListView):
    """List travel grant applications for the current conference.

    Provides summary statistics (total requested, total approved, counts
    by status) and a status filter bar for efficient grant review.
    """

    template_name = "django_program/manage/travel_grant_list.html"
    context_object_name = "grants"
    paginate_by = 50

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add summary stats, status filter, and active nav to context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "travel-grants"
        context["current_status"] = self.request.GET.get("status", "")

        all_grants = TravelGrant.objects.filter(conference=self.conference)
        totals = all_grants.aggregate(
            total_requested=Sum("requested_amount"),
            total_approved=Sum("approved_amount"),
        )
        context["grant_stats"] = {
            "total": all_grants.count(),
            "pending": all_grants.filter(status=TravelGrant.GrantStatus.SUBMITTED).count(),
            "approved": all_grants.filter(status=TravelGrant.GrantStatus.ACCEPTED).count(),
            "rejected": all_grants.filter(status=TravelGrant.GrantStatus.REJECTED).count(),
            "withdrawn": all_grants.filter(status=TravelGrant.GrantStatus.WITHDRAWN).count(),
            "disbursed": all_grants.filter(status=TravelGrant.GrantStatus.DISBURSED).count(),
            "total_requested": totals["total_requested"] or 0,
            "total_approved": totals["total_approved"] or 0,
        }
        return context

    def get_queryset(self) -> QuerySet[TravelGrant]:
        """Return travel grants for the current conference."""
        qs = (
            TravelGrant.objects.filter(conference=self.conference)
            .select_related("user", "reviewed_by")
            .annotate(receipt_count=Count("receipts"))
            .order_by("-created_at")
        )
        status_filter = self.request.GET.get("status", "").strip()
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class TravelGrantReviewView(ManagePermissionMixin, UpdateView):
    """Review a travel grant application."""

    template_name = "django_program/manage/travel_grant_edit.html"
    form_class = TravelGrantForm
    context_object_name = "grant"

    def dispatch(self, request: HttpRequest, *args: str, **kwargs: str) -> HttpResponse:
        """Disable browser caching to prevent stale review forms."""
        response = super().dispatch(request, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add messages, message form, and review history to context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "travel-grants"
        context["has_previous_review"] = self.object.reviewed_at is not None
        context["grant_messages"] = TravelGrantMessage.objects.filter(grant=self.object).order_by("created_at")
        context["message_form"] = ReviewerMessageForm()
        return context

    def get_queryset(self) -> QuerySet[TravelGrant]:
        """Scope to the current conference."""
        return TravelGrant.objects.filter(conference=self.conference).select_related("user", "reviewed_by")

    def get_success_url(self) -> str:
        """Redirect to the travel grants list."""
        return reverse("manage:travel-grant-list", kwargs={"conference_slug": self.conference.slug})

    def form_valid(self, form: TravelGrantForm) -> HttpResponse:
        """Record the reviewer and flash success."""
        form.instance.reviewed_by = self.request.user
        form.instance.reviewed_at = timezone.now()
        messages.success(self.request, "Travel grant updated successfully.")
        return super().form_valid(form)


class TravelGrantSendMessageView(ManagePermissionMixin, View):
    """POST-only view for reviewers to send a message on a grant."""

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:
        """Create a message attached to the grant."""
        grant = get_object_or_404(TravelGrant, conference=self.conference, pk=kwargs["pk"])
        form = ReviewerMessageForm(request.POST)
        if form.is_valid():
            msg = form.save(commit=False)
            msg.grant = grant
            msg.user = request.user
            msg.save()
            messages.success(request, "Message sent.")
        return redirect(
            reverse("manage:travel-grant-review", kwargs={"conference_slug": self.conference.slug, "pk": grant.pk})
        )


class TravelGrantDisburseView(ManagePermissionMixin, View):
    """Mark a travel grant as disbursed."""

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:
        """Record disbursement details and transition the grant status.

        Only grants in the ``accepted`` state can be disbursed. On success
        the grant is moved to ``disbursed`` and the disbursement amount,
        timestamp, and processing user are recorded.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments (expects ``pk``).

        Returns:
            A redirect to the grant review page.
        """
        grant = get_object_or_404(TravelGrant, pk=kwargs["pk"], conference=self.conference)
        form = DisbursementForm(request.POST)
        if form.is_valid() and grant.status == TravelGrant.GrantStatus.ACCEPTED:
            grant.status = TravelGrant.GrantStatus.DISBURSED
            grant.disbursed_amount = form.cleaned_data["disbursed_amount"]
            grant.disbursed_at = timezone.now()
            grant.disbursed_by = request.user
            grant.save(update_fields=["status", "disbursed_amount", "disbursed_at", "disbursed_by"])
            display_name = grant.user.get_full_name() or grant.user.username
            messages.success(
                request,
                f"Grant for {display_name} marked as disbursed (${grant.disbursed_amount}).",
            )
        else:
            messages.error(request, "Could not process disbursement.")
        return redirect("manage:travel-grant-review", conference_slug=self.conference.slug, pk=grant.pk)


class ReceiptReviewQueueView(ManagePermissionMixin, View):
    """Pick a random pending receipt for review."""

    def get(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Redirect to a random pending receipt, or back to the grant list if none."""
        pending = (
            Receipt.objects.filter(
                grant__conference=self.conference,
                approved=False,
                flagged=False,
            )
            .select_related("grant__user")
            .order_by("?")
            .first()
        )
        if pending is None:
            messages.info(request, "No pending receipts to review.")
            return redirect(reverse("manage:travel-grant-list", kwargs={"conference_slug": self.conference.slug}))
        return redirect(
            reverse(
                "manage:receipt-review-detail",
                kwargs={"conference_slug": self.conference.slug, "pk": pending.pk},
            )
        )


class ReceiptReviewDetailView(ManagePermissionMixin, DetailView):
    """Display a receipt for review with approve/flag controls."""

    template_name = "django_program/manage/receipt_review.html"
    context_object_name = "receipt"

    def get_queryset(self) -> QuerySet[Receipt]:
        """Return receipts scoped to the current conference."""
        return Receipt.objects.filter(grant__conference=self.conference).select_related("grant__user")

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add navigation and flag form to context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "travel-grants"
        context["flag_form"] = ReceiptFlagForm()
        return context


class ReceiptApproveView(ManagePermissionMixin, View):
    """POST-only view to approve a receipt."""

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:
        """Mark the receipt as approved by the current user."""
        receipt = get_object_or_404(Receipt, pk=kwargs["pk"], grant__conference=self.conference)
        receipt.approved = True
        receipt.approved_by = request.user
        receipt.approved_at = timezone.now()
        receipt.save(update_fields=["approved", "approved_by", "approved_at"])
        messages.success(request, "Receipt approved.")
        return redirect(reverse("manage:receipt-review-queue", kwargs={"conference_slug": self.conference.slug}))


class ReceiptFlagView(ManagePermissionMixin, View):
    """POST-only view to flag a receipt."""

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:
        """Flag the receipt with a reason provided by the reviewer."""
        receipt = get_object_or_404(Receipt, pk=kwargs["pk"], grant__conference=self.conference)
        form = ReceiptFlagForm(request.POST)
        if form.is_valid():
            receipt.flagged = True
            receipt.flagged_reason = form.cleaned_data["reason"]
            receipt.flagged_by = request.user
            receipt.flagged_at = timezone.now()
            receipt.save(update_fields=["flagged", "flagged_reason", "flagged_by", "flagged_at"])
            messages.success(request, "Receipt flagged.")
        return redirect(reverse("manage:receipt-review-queue", kwargs={"conference_slug": self.conference.slug}))


class SyncPretalxView(ManagePermissionMixin, View):
    """Trigger a Pretalx sync for the current conference.

    Accepts POST requests with optional checkboxes to select which
    entities to sync (rooms, speakers, talks, schedule).  When no
    checkboxes are selected, syncs everything.
    """

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Run the Pretalx sync and redirect back to the dashboard.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments (unused).

        Returns:
            A redirect to the conference dashboard with a flash message.
        """
        if not self.conference.pretalx_event_slug:
            messages.error(
                request,
                "This conference has no Pretalx event slug configured. Set it in Conference Settings first.",
            )
            return redirect("manage:dashboard", conference_slug=self.conference.slug)

        try:
            service = PretalxSyncService(self.conference)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("manage:dashboard", conference_slug=self.conference.slug)

        sync_rooms = request.POST.get("sync_rooms") == "on"
        sync_speakers = request.POST.get("sync_speakers") == "on"
        sync_talks = request.POST.get("sync_talks") == "on"
        sync_schedule = request.POST.get("sync_schedule") == "on"
        allow_large_schedule_drop = request.POST.get("allow_large_schedule_drop") == "on"
        no_specific = not (sync_rooms or sync_speakers or sync_talks or sync_schedule)

        try:
            if no_specific:
                results = service.sync_all(allow_large_deletions=allow_large_schedule_drop)
                messages.success(
                    request,
                    f"Synced {results['rooms']} rooms, "
                    f"{results['speakers']} speakers, "
                    f"{results['talks']} talks, "
                    f"{results['schedule_slots']} schedule slots.",
                )
            else:
                parts = []
                if sync_rooms:
                    count = service.sync_rooms()
                    parts.append(f"{count} rooms")
                if sync_speakers:
                    count = service.sync_speakers()
                    parts.append(f"{count} speakers")
                if sync_talks:
                    count = service.sync_talks()
                    parts.append(f"{count} talks")
                if sync_schedule:
                    count, skipped = service.sync_schedule(allow_large_deletions=allow_large_schedule_drop)
                    msg = f"{count} schedule slots"
                    if skipped:
                        msg += f" ({skipped} unscheduled)"
                    parts.append(msg)
                messages.success(request, f"Synced {', '.join(parts)}.")
        except RuntimeError as exc:
            messages.error(request, f"Sync failed: {exc}")

        return redirect("manage:dashboard", conference_slug=self.conference.slug)


class SyncSponsorsView(ManagePermissionMixin, View):
    """Trigger a PSF sponsor sync for the current conference.

    Accepts POST requests. Only available for PyCon US conferences
    where the sponsor profile supports API sync.
    """

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Run the PSF sponsor sync and redirect back to the dashboard.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments (unused).

        Returns:
            A redirect to the conference dashboard with a flash message.
        """
        try:
            service = SponsorSyncService(self.conference)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("manage:dashboard", conference_slug=self.conference.slug)

        try:
            results = service.sync_all()
            messages.success(request, f"Synced {results['sponsors']} sponsors from PSF.")
        except RuntimeError as exc:
            messages.error(request, f"Sponsor sync failed: {exc}")

        return redirect("manage:dashboard", conference_slug=self.conference.slug)


class SyncPretalxStreamView(ManagePermissionMixin, View):
    """Stream Pretalx sync progress via Server-Sent Events.

    Returns a ``StreamingHttpResponse`` that yields progress events as each
    sync step (rooms, speakers, talks, schedule) completes.
    """

    def post(self, request: HttpRequest, **kwargs: str) -> StreamingHttpResponse:  # noqa: ARG002
        """Start the streaming sync and return an SSE response."""
        response = StreamingHttpResponse(
            self._sync_stream(request),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response

    @staticmethod
    def _sse(data: dict[str, object]) -> str:
        """Format a dict as an SSE data line."""
        return f"data: {json.dumps(data)}\n\n"

    def _run_sync_step(
        self,
        step_idx: int,
        total: int,
        entity_name: str,
        sync_fn: Callable[[], int],
        iter_fn: Callable[[], Iterator[dict[str, int | str]]] | None,
    ) -> Iterator[tuple[str, int | None, bool]]:
        """Execute a single sync step and yield SSE events with its result.

        Runs the sync function (or its iterator variant for progress
        reporting) and yields SSE-formatted strings.  The final yield is a
        tuple containing the last SSE string, the synced count (or ``None``
        on error), and whether an error occurred.

        Args:
            step_idx: 1-based index of this step.
            total: Total number of sync steps.
            entity_name: Human-readable label for the entity type.
            sync_fn: Callable that performs the sync and returns a count.
            iter_fn: Optional iterator callable that yields progress dicts.

        Yields:
            Tuples of ``(sse_string, count_or_none, is_error)``.
        """
        yield (
            self._sse(
                {
                    "step": step_idx,
                    "total": total,
                    "label": f"Syncing {entity_name}...",
                    "status": "in_progress",
                }
            ),
            None,
            False,
        )
        try:
            if iter_fn is not None:
                count = 0
                skipped = 0
                for progress in iter_fn():
                    if "count" in progress:
                        count = int(progress["count"])
                    elif progress.get("phase") == "fetching":
                        yield (
                            self._sse(
                                {
                                    "step": step_idx,
                                    "total": total,
                                    "label": f"Fetching {entity_name} from API...",
                                    "status": "in_progress",
                                }
                            ),
                            None,
                            False,
                        )
                    else:
                        yield (
                            self._sse(
                                {
                                    "step": step_idx,
                                    "total": total,
                                    "label": (f"Syncing {entity_name}... ({progress['current']}/{progress['total']})"),
                                    "current": int(progress["current"]),
                                    "current_total": int(progress["total"]),
                                    "status": "in_progress",
                                }
                            ),
                            None,
                            False,
                        )
            else:
                result = sync_fn()
                if isinstance(result, tuple):
                    count, skipped = result
                else:
                    count = result
                    skipped = 0
            label = f"Synced {count} {entity_name}"
            if skipped:
                label += f" ({skipped} unscheduled)"
            yield (
                self._sse(
                    {
                        "step": step_idx,
                        "total": total,
                        "label": label,
                        "status": "done",
                    }
                ),
                count,
                False,
            )
        except RuntimeError, ValueError:
            logger.exception("Sync step %d (%s) failed", step_idx, entity_name)
            yield (
                self._sse(
                    {
                        "step": step_idx,
                        "total": total,
                        "label": f"Failed: {entity_name}",
                        "status": "step_error",
                        "detail": f"Sync failed for {entity_name}. Check server logs for details.",
                    }
                ),
                None,
                True,
            )

    @staticmethod
    def _build_sync_steps(
        request: HttpRequest,
        service: PretalxSyncService,
    ) -> list[tuple[str, object, object]]:
        """Build the list of sync steps based on form checkboxes.

        When no specific checkboxes are selected, all entity types are
        included.

        Args:
            request: The incoming HTTP request with POST data.
            service: The initialized sync service.

        Returns:
            List of ``(entity_name, sync_fn, iter_fn)`` tuples.
        """
        want_rooms = request.POST.get("sync_rooms") == "on"
        want_speakers = request.POST.get("sync_speakers") == "on"
        want_talks = request.POST.get("sync_talks") == "on"
        want_schedule = request.POST.get("sync_schedule") == "on"
        allow_large_schedule_drop = request.POST.get("allow_large_schedule_drop") == "on"
        sync_all = not (want_rooms or want_speakers or want_talks or want_schedule)

        steps: list[tuple[str, object, object]] = []
        if sync_all or want_rooms:
            steps.append(("rooms", service.sync_rooms, None))
        if sync_all or want_speakers:
            steps.append(("speakers", service.sync_speakers, service.sync_speakers_iter))
        if sync_all or want_talks:
            steps.append(("talks", service.sync_talks, service.sync_talks_iter))
        if sync_all or want_schedule:
            steps.append(
                (
                    "schedule slots",
                    lambda: service.sync_schedule(allow_large_deletions=allow_large_schedule_drop),
                    None,
                )
            )
        return steps

    def _sync_stream(self, request: HttpRequest) -> Iterator[str]:
        """Generator that runs sync steps and yields SSE progress events."""
        if not self.conference.pretalx_event_slug:
            yield self._sse(
                {
                    "status": "error",
                    "message": "No Pretalx event slug configured.",
                }
            )
            return

        try:
            service = PretalxSyncService(self.conference)
        except ValueError as exc:
            yield self._sse({"status": "error", "message": str(exc)})
            return

        steps = self._build_sync_steps(request, service)
        total = len(steps)
        counts: dict[str, int] = {}
        had_errors = False

        for idx, (entity_name, sync_fn, iter_fn) in enumerate(steps, 1):
            for sse_event, count, is_error in self._run_sync_step(
                idx,
                total,
                entity_name,
                sync_fn,
                iter_fn,
            ):
                yield sse_event
                if is_error:
                    counts[entity_name] = 0
                    had_errors = True
                elif count is not None:
                    counts[entity_name] = count

        summary = ", ".join(f"{count} {name}" for name, count in counts.items())
        yield self._sse(
            {
                "status": "complete",
                "message": f"Synced {summary}.",
                "warning": had_errors,
            }
        )


_events_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_CACHE_TTL = 300  # 5 minutes


class PretalxEventSearchView(LoginRequiredMixin, View):
    """JSON API endpoint for Pretalx event autocomplete.

    Returns a filtered list of events from the Pretalx API, matched
    against the ``q`` query parameter by slug and localized name.
    Results are cached in-memory for 5 minutes per API token.
    """

    def dispatch(self, request: HttpRequest, *args: str, **kwargs: str) -> HttpResponse:
        """Enforce staff/superuser permissions.

        Args:
            request: The incoming HTTP request.
            *args: Positional arguments from the URL resolver.
            **kwargs: Keyword arguments from the URL pattern.

        Returns:
            The HTTP response.

        Raises:
            PermissionDenied: If the user is not superuser or staff.
        """
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not (request.user.is_superuser or request.user.is_staff):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest, **kwargs: str) -> JsonResponse:  # noqa: ARG002
        """Search Pretalx events by slug or name.

        Reads ``q`` for the search text and an optional ``token`` override.
        Fetches all events from the Pretalx API (cached for 5 minutes),
        filters by case-insensitive substring match on slug and localized
        name, and returns up to 20 results.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments (unused).

        Returns:
            A JsonResponse with a list of matching events, or an error
            payload with status 502 on upstream failure.
        """
        q = request.GET.get("q", "").strip().lower()
        token_override = request.GET.get("token", "").strip()

        config = get_config()
        api_token = token_override or config.pretalx.token or ""
        base_url = config.pretalx.base_url

        try:
            events = self._get_events(base_url, api_token)
        except RuntimeError, ValueError, OSError:
            logger.exception("Failed to fetch Pretalx events")
            return JsonResponse(
                {"error": "Failed to fetch events from Pretalx. Check server logs for details."}, status=502
            )

        if q:
            filtered = [
                ev for ev in events if q in ev.get("slug", "").lower() or q in _localized(ev.get("name")).lower()
            ]
        else:
            filtered = list(events)

        results = [
            {
                "slug": ev.get("slug", ""),
                "name": _localized(ev.get("name")),
                "date_from": ev.get("date_from", ""),
                "date_to": ev.get("date_to", ""),
            }
            for ev in filtered[:20]
        ]
        return JsonResponse(results, safe=False)

    @staticmethod
    def _get_events(base_url: str, api_token: str) -> list[dict[str, Any]]:
        """Return cached events or fetch fresh ones from Pretalx.

        Args:
            base_url: Root URL of the Pretalx instance.
            api_token: API token for authenticated access.

        Returns:
            A list of raw event dicts from the Pretalx API.
        """
        now = time.time()
        cached = _events_cache.get(api_token)
        if cached is not None:
            ts, data = cached
            if now - ts < _CACHE_TTL:
                return data

        data = PretalxClient.fetch_events(base_url=base_url, api_token=api_token)
        _events_cache[api_token] = (now, data)
        return data


# ---------------------------------------------------------------------------
# Registration / Ticketing Management Views
# ---------------------------------------------------------------------------


def _unique_ticket_type_slug(name: str, conference: object, exclude_pk: int | None = None) -> str:
    """Generate a unique slug for a TicketType within a conference.

    Args:
        name: The ticket type name to slugify.
        conference: The conference instance to scope uniqueness to.
        exclude_pk: Optional PK to exclude (for updates).

    Returns:
        A unique slug string.
    """
    base = slugify(name) or "ticket"
    candidate = base
    counter = 1
    while True:
        qs = TicketType.objects.filter(conference=conference, slug=candidate)
        if exclude_pk is not None:
            qs = qs.exclude(pk=exclude_pk)
        if not qs.exists():
            return candidate
        counter += 1
        candidate = f"{base}-{counter}"


def _unique_addon_slug(name: str, conference: object, exclude_pk: int | None = None) -> str:
    """Generate a unique slug for an AddOn within a conference.

    Args:
        name: The add-on name to slugify.
        conference: The conference instance to scope uniqueness to.
        exclude_pk: Optional PK to exclude (for updates).

    Returns:
        A unique slug string.
    """
    base = slugify(name) or "addon"
    candidate = base
    counter = 1
    while True:
        qs = AddOn.objects.filter(conference=conference, slug=candidate)
        if exclude_pk is not None:
            qs = qs.exclude(pk=exclude_pk)
        if not qs.exists():
            return candidate
        counter += 1
        candidate = f"{base}-{counter}"


class TicketTypeListView(ManagePermissionMixin, ListView):
    """List ticket types for the current conference."""

    template_name = "django_program/manage/ticket_type_list.html"
    context_object_name = "ticket_types"
    paginate_by = 50

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "ticket-types"
        return context

    def get_queryset(self) -> QuerySet[TicketType]:
        """Return ticket types for the current conference.

        Annotates each ticket type with ``sold_count`` to display how many
        tickets have been sold (orders in paid or partially refunded status).

        Returns:
            A queryset of TicketType instances ordered by display order.
        """
        return (
            TicketType.objects.filter(conference=self.conference)
            .annotate(
                sold_count=Count(
                    "order_line_items",
                    filter=Q(
                        order_line_items__order__status__in=[
                            Order.Status.PAID,
                            Order.Status.PARTIALLY_REFUNDED,
                        ]
                    ),
                )
            )
            .order_by("order", "name")
        )


class TicketTypeCreateView(ManagePermissionMixin, CreateView):
    """Create a new ticket type for the current conference."""

    template_name = "django_program/manage/ticket_type_edit.html"
    form_class = TicketTypeForm

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` and ``is_create`` to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "ticket-types"
        context["is_create"] = True
        return context

    def form_valid(self, form: TicketTypeForm) -> HttpResponse:
        """Assign the conference and auto-generate slug before saving."""
        form.instance.conference = self.conference
        if not form.cleaned_data.get("slug"):
            form.instance.slug = _unique_ticket_type_slug(form.instance.name, self.conference)
        messages.success(self.request, "Ticket type created successfully.")
        return super().form_valid(form)

    def get_success_url(self) -> str:
        """Redirect to the ticket type list."""
        return reverse("manage:ticket-type-list", kwargs={"conference_slug": self.conference.slug})


class TicketTypeEditView(ManagePermissionMixin, UpdateView):
    """Edit a ticket type belonging to the current conference."""

    template_name = "django_program/manage/ticket_type_edit.html"
    form_class = TicketTypeForm
    context_object_name = "ticket_type"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "ticket-types"
        return context

    def get_queryset(self) -> QuerySet[TicketType]:
        """Scope to the current conference."""
        return TicketType.objects.filter(conference=self.conference)

    def get_success_url(self) -> str:
        """Redirect to the ticket type list."""
        return reverse("manage:ticket-type-list", kwargs={"conference_slug": self.conference.slug})

    def form_valid(self, form: TicketTypeForm) -> HttpResponse:
        """Save and flash success."""
        messages.success(self.request, "Ticket type updated successfully.")
        return super().form_valid(form)


class AddOnListView(ManagePermissionMixin, ListView):
    """List add-ons for the current conference."""

    template_name = "django_program/manage/addon_list.html"
    context_object_name = "addons"
    paginate_by = 50

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "addons"
        return context

    def get_queryset(self) -> QuerySet[AddOn]:
        """Return add-ons for the current conference.

        Annotates each add-on with ``sold_count``.

        Returns:
            A queryset of AddOn instances ordered by display order.
        """
        return (
            AddOn.objects.filter(conference=self.conference)
            .annotate(
                sold_count=Count(
                    "order_line_items",
                    filter=Q(
                        order_line_items__order__status__in=[
                            Order.Status.PAID,
                            Order.Status.PARTIALLY_REFUNDED,
                        ]
                    ),
                )
            )
            .order_by("order", "name")
        )


class AddOnCreateView(ManagePermissionMixin, CreateView):
    """Create a new add-on for the current conference."""

    template_name = "django_program/manage/addon_edit.html"
    form_class = AddOnForm

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` and ``is_create`` to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "addons"
        context["is_create"] = True
        return context

    def form_valid(self, form: AddOnForm) -> HttpResponse:
        """Assign the conference and auto-generate slug before saving."""
        form.instance.conference = self.conference
        if not form.cleaned_data.get("slug"):
            form.instance.slug = _unique_addon_slug(form.instance.name, self.conference)
        messages.success(self.request, "Add-on created successfully.")
        return super().form_valid(form)

    def get_success_url(self) -> str:
        """Redirect to the add-on list."""
        return reverse("manage:addon-list", kwargs={"conference_slug": self.conference.slug})


class AddOnEditView(ManagePermissionMixin, UpdateView):
    """Edit an add-on belonging to the current conference."""

    template_name = "django_program/manage/addon_edit.html"
    form_class = AddOnForm
    context_object_name = "addon"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "addons"
        return context

    def get_queryset(self) -> QuerySet[AddOn]:
        """Scope to the current conference."""
        return AddOn.objects.filter(conference=self.conference)

    def get_success_url(self) -> str:
        """Redirect to the add-on list."""
        return reverse("manage:addon-list", kwargs={"conference_slug": self.conference.slug})

    def form_valid(self, form: AddOnForm) -> HttpResponse:
        """Save and flash success."""
        messages.success(self.request, "Add-on updated successfully.")
        return super().form_valid(form)


class VoucherListView(ManagePermissionMixin, ListView):
    """List vouchers for the current conference.

    Voucher codes are partially masked in the template for security.
    """

    template_name = "django_program/manage/voucher_list.html"
    context_object_name = "vouchers"
    paginate_by = 50

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "vouchers"
        return context

    def get_queryset(self) -> QuerySet[Voucher]:
        """Return vouchers for the current conference.

        Returns:
            A queryset of Voucher instances ordered by creation date.
        """
        return Voucher.objects.filter(conference=self.conference).order_by("-created_at")


class VoucherCreateView(ManagePermissionMixin, CreateView):
    """Create a new voucher for the current conference."""

    template_name = "django_program/manage/voucher_edit.html"
    form_class = VoucherForm

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` and ``is_create`` to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "vouchers"
        context["is_create"] = True
        return context

    def get_form(self, form_class: type[VoucherForm] | None = None) -> VoucherForm:
        """Scope the ticket type and add-on querysets to the current conference."""
        form = super().get_form(form_class)
        form.fields["applicable_ticket_types"].queryset = TicketType.objects.filter(conference=self.conference)
        form.fields["applicable_addons"].queryset = AddOn.objects.filter(conference=self.conference)
        return form

    def form_valid(self, form: VoucherForm) -> HttpResponse:
        """Assign the conference before saving."""
        form.instance.conference = self.conference
        messages.success(self.request, "Voucher created successfully.")
        return super().form_valid(form)

    def get_success_url(self) -> str:
        """Redirect to the voucher list."""
        return reverse("manage:voucher-list", kwargs={"conference_slug": self.conference.slug})


class VoucherEditView(ManagePermissionMixin, UpdateView):
    """Edit a voucher belonging to the current conference."""

    template_name = "django_program/manage/voucher_edit.html"
    form_class = VoucherForm
    context_object_name = "voucher"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "vouchers"
        return context

    def get_queryset(self) -> QuerySet[Voucher]:
        """Scope to the current conference."""
        return Voucher.objects.filter(conference=self.conference)

    def get_form(self, form_class: type[VoucherForm] | None = None) -> VoucherForm:
        """Scope the ticket type and add-on querysets to the current conference."""
        form = super().get_form(form_class)
        form.fields["applicable_ticket_types"].queryset = TicketType.objects.filter(conference=self.conference)
        form.fields["applicable_addons"].queryset = AddOn.objects.filter(conference=self.conference)
        return form

    def get_success_url(self) -> str:
        """Redirect to the voucher list."""
        return reverse("manage:voucher-list", kwargs={"conference_slug": self.conference.slug})

    def form_valid(self, form: VoucherForm) -> HttpResponse:
        """Save and flash success."""
        messages.success(self.request, "Voucher updated successfully.")
        return super().form_valid(form)


class OrderListView(ManagePermissionMixin, ListView):
    """List orders for the current conference.

    Supports filtering by order status via the ``status`` GET parameter.
    Paginated at 50 orders per page.
    """

    template_name = "django_program/manage/order_list.html"
    context_object_name = "orders"
    paginate_by = 50

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` and status filter to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "orders"
        context["current_status"] = self.request.GET.get("status", "")
        context["order_statuses"] = Order.Status.choices
        return context

    def get_queryset(self) -> QuerySet[Order]:
        """Return orders for the current conference with optional status filter.

        Returns:
            A queryset of Order instances ordered by creation date descending.
        """
        qs = Order.objects.filter(conference=self.conference).select_related("user").order_by("-created_at")
        status_filter = self.request.GET.get("status", "").strip()
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class OrderDetailView(ManagePermissionMixin, DetailView):
    """Display full order details with line items and payments.

    Includes a manual payment form for staff to record comp/manual payments.
    """

    template_name = "django_program/manage/order_detail.html"
    context_object_name = "order"

    def get_queryset(self) -> QuerySet[Order]:
        """Scope order lookup to the current conference."""
        return Order.objects.filter(conference=self.conference).select_related("user")

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add line items, payments, and manual payment form to context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "orders"
        context["line_items"] = self.object.line_items.select_related("ticket_type", "addon").order_by("id")
        context["payments"] = self.object.payments.select_related("created_by").order_by("-created_at")
        context["payment_form"] = ManualPaymentForm()
        total_paid = (
            self.object.payments.filter(status=Payment.Status.SUCCEEDED).aggregate(
                total=Sum("amount"),
            )["total"]
            or 0
        )
        context["total_paid"] = total_paid
        context["balance_remaining"] = self.object.total - total_paid
        return context


class ManualPaymentView(ManagePermissionMixin, View):
    """POST-only view to record a manual payment against an order.

    When total successful payments meet or exceed the order total,
    the order status is automatically transitioned to ``paid``.
    """

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:
        """Record a manual payment and optionally mark the order as paid.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments (expects ``pk``).

        Returns:
            A redirect to the order detail page.
        """
        order = get_object_or_404(Order, pk=kwargs["pk"], conference=self.conference)
        form = ManualPaymentForm(request.POST)
        if form.is_valid():
            Payment.objects.create(
                order=order,
                method=form.cleaned_data["method"],
                status=Payment.Status.SUCCEEDED,
                amount=form.cleaned_data["amount"],
                note=form.cleaned_data.get("note", ""),
                created_by=request.user,
            )
            total_paid = (
                order.payments.filter(status=Payment.Status.SUCCEEDED).aggregate(
                    total=Sum("amount"),
                )["total"]
                or 0
            )
            if total_paid >= order.total and order.status == Order.Status.PENDING:
                order.status = Order.Status.PAID
                order.save(update_fields=["status", "updated_at"])
                messages.success(request, f"Payment recorded. Order {order.reference} marked as paid.")
            else:
                messages.success(request, "Payment recorded successfully.")
        else:
            messages.error(request, "Invalid payment data. Please check the form.")
        return redirect("manage:order-detail", conference_slug=self.conference.slug, pk=order.pk)
