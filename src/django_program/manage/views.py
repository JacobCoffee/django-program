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
from django.db.models import Count, Q, QuerySet
from django.http import HttpRequest, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.text import slugify
from django.utils.timezone import localdate
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from django_program.conference.models import Conference, Section
from django_program.manage.forms import (
    ConferenceForm,
    ImportFromPretalxForm,
    RoomForm,
    ScheduleSlotForm,
    SectionForm,
    SponsorForm,
    SponsorLevelForm,
    TalkForm,
)
from django_program.pretalx.models import Room, ScheduleSlot, Speaker, Talk
from django_program.pretalx.sync import PretalxSyncService
from django_program.settings import get_config
from django_program.sponsors.models import Sponsor, SponsorLevel
from pretalx_client.adapters.normalization import localized as _localized
from pretalx_client.client import PretalxClient

logger = logging.getLogger(__name__)


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
        }

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

    def get_success_url(self) -> str:
        """Redirect to the section list after a successful save.

        Returns:
            URL of the section list view.
        """
        return reverse("manage:section-list", kwargs={"conference_slug": self.conference.slug})

    def form_valid(self, form: SectionForm) -> HttpResponse:
        """Save the form and add a success message.

        Args:
            form: The validated section form.

        Returns:
            A redirect response to the success URL.
        """
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

    def form_valid(self, form: SectionForm) -> HttpResponse:
        """Assign the conference before saving."""
        form.instance.conference = self.conference
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
        return SponsorLevel.objects.filter(conference=self.conference).order_by("order", "name")


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
    """Edit a sponsor."""

    template_name = "django_program/manage/sponsor_edit.html"
    form_class = SponsorForm
    context_object_name = "sponsor"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` and benefits to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "sponsors"
        context["benefits"] = self.object.benefits.all()
        return context

    def get_queryset(self) -> QuerySet[Sponsor]:
        """Scope to the current conference."""
        return Sponsor.objects.filter(conference=self.conference).select_related("level")

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
        return context

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
        no_specific = not (sync_rooms or sync_speakers or sync_talks or sync_schedule)

        try:
            if no_specific:
                results = service.sync_all()
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
                    count, skipped = service.sync_schedule()
                    msg = f"{count} schedule slots"
                    if skipped:
                        msg += f" ({skipped} unscheduled)"
                    parts.append(msg)
                messages.success(request, f"Synced {', '.join(parts)}.")
        except RuntimeError as exc:
            messages.error(request, f"Sync failed: {exc}")

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
        sync_all = not (want_rooms or want_speakers or want_talks or want_schedule)

        steps: list[tuple[str, object, object]] = []
        if sync_all or want_rooms:
            steps.append(("rooms", service.sync_rooms, None))
        if sync_all or want_speakers:
            steps.append(("speakers", service.sync_speakers, service.sync_speakers_iter))
        if sync_all or want_talks:
            steps.append(("talks", service.sync_talks, service.sync_talks_iter))
        if sync_all or want_schedule:
            steps.append(("schedule slots", service.sync_schedule, None))
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
