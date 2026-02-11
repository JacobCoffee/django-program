"""Views for the pretalx integration app.

Provides read-only schedule, talk, and speaker views scoped to a conference
via the ``conference_slug`` URL kwarg.  All views resolve the conference from
the URL and return a 404 if the slug does not match.
"""

import itertools
from typing import TYPE_CHECKING

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from django_program.conference.models import Conference
from django_program.pretalx.models import ScheduleSlot, Speaker, Talk

if TYPE_CHECKING:
    from datetime import date

    from django.db.models import QuerySet
    from django.http import HttpRequest


class ConferenceMixin:
    """Mixin that resolves the conference from the ``conference_slug`` URL kwarg.

    Stores the conference on ``self.conference`` and adds it to the template
    context.  Returns a 404 if no conference matches the slug.
    """

    conference: Conference
    kwargs: dict[str, str]

    def get_conference(self) -> Conference:
        """Look up the conference by slug from the URL.

        Returns:
            The matched conference instance.

        Raises:
            Http404: If no conference matches the slug.
        """
        return get_object_or_404(Conference, slug=self.kwargs["conference_slug"])

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add the conference to the template context.

        Args:
            **kwargs: Additional context data.

        Returns:
            The template context dict with the conference included.
        """
        context: dict[str, object] = super().get_context_data(**kwargs)  # type: ignore[misc]
        context["conference"] = self.conference
        return context

    def dispatch(self, request: HttpRequest, *args: str, **kwargs: str) -> HttpResponse:
        """Resolve the conference before dispatching.

        Args:
            request: The incoming HTTP request.
            *args: Positional arguments from the URL resolver.
            **kwargs: Keyword arguments from the URL pattern.

        Returns:
            The HTTP response.
        """
        self.conference = self.get_conference()
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]


class ScheduleView(ConferenceMixin, TemplateView):
    """Full schedule view grouped by day.

    Renders the conference schedule with slots organized by date. Each day
    is a ``(date, list[ScheduleSlot])`` tuple ordered by start time.
    """

    template_name = "django_program/pretalx/schedule.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Build schedule context grouped by day.

        Returns:
            Context dict containing ``conference`` and ``days``.
        """
        context = super().get_context_data(**kwargs)
        slots = (
            ScheduleSlot.objects.filter(
                conference=self.conference,
            )
            .select_related("talk")
            .order_by("start", "room")
        )

        days: list[tuple[date, list[ScheduleSlot]]] = [
            (day, list(day_slots)) for day, day_slots in itertools.groupby(slots, key=lambda s: s.start.date())
        ]

        context["days"] = days
        return context


class ScheduleJSONView(ConferenceMixin, View):
    """JSON endpoint for schedule data.

    Returns a JSON array of schedule slots suitable for embedding in
    JavaScript schedule widgets. Each slot includes title, room, start/end
    times, slot type, and the linked talk code when available.
    """

    def get(self, _request: HttpRequest, **_kwargs: str) -> JsonResponse:
        """Return schedule slots as a JSON array.

        Args:
            _request: The incoming HTTP request.
            **_kwargs: URL keyword arguments (unused).

        Returns:
            A JSON response with the schedule data.
        """
        slots = (
            ScheduleSlot.objects.filter(
                conference=self.conference,
            )
            .select_related("talk")
            .order_by("start", "room")
        )

        data = [
            {
                "title": slot.display_title,
                "room": slot.room,
                "start": slot.start.isoformat(),
                "end": slot.end.isoformat(),
                "slot_type": slot.slot_type,
                "talk_code": slot.talk.pretalx_code if slot.talk else "",
            }
            for slot in slots
        ]

        return JsonResponse(data, safe=False)


class TalkDetailView(ConferenceMixin, DetailView):
    """Detail view for a single talk.

    Looks up the talk by its Pretalx code within the conference scope.
    Prefetches the speakers relation for display.
    """

    template_name = "django_program/pretalx/talk_detail.html"
    context_object_name = "talk"

    def get_object(self, queryset: QuerySet[Talk] | None = None) -> Talk:  # noqa: ARG002
        """Look up the talk by conference and pretalx_code.

        Returns:
            The matched Talk instance.

        Raises:
            Http404: If no talk matches the conference and code.
        """
        return get_object_or_404(
            Talk.objects.prefetch_related("speakers"),
            conference=self.conference,
            pretalx_code=self.kwargs["pretalx_code"],
        )

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add speakers to the template context.

        Returns:
            Context dict containing ``conference``, ``talk``, and ``speakers``.
        """
        context = super().get_context_data(**kwargs)
        context["speakers"] = self.object.speakers.all()
        return context


class SpeakerListView(ConferenceMixin, ListView):
    """List view of all speakers for a conference, ordered by name."""

    template_name = "django_program/pretalx/speaker_list.html"
    context_object_name = "speakers"

    def get_queryset(self) -> QuerySet[Speaker]:
        """Return speakers for the current conference ordered by name.

        Returns:
            A queryset of Speaker instances.
        """
        return Speaker.objects.filter(conference=self.conference).order_by("name")


class SpeakerDetailView(ConferenceMixin, DetailView):
    """Detail view for a single speaker.

    Looks up the speaker by their Pretalx code within the conference scope.
    Prefetches talks for display.
    """

    template_name = "django_program/pretalx/speaker_detail.html"
    context_object_name = "speaker"

    def get_object(self, queryset: QuerySet[Speaker] | None = None) -> Speaker:  # noqa: ARG002
        """Look up the speaker by conference and pretalx_code.

        Returns:
            The matched Speaker instance.

        Raises:
            Http404: If no speaker matches the conference and code.
        """
        return get_object_or_404(
            Speaker.objects.prefetch_related("talks"),
            conference=self.conference,
            pretalx_code=self.kwargs["pretalx_code"],
        )

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add talks to the template context.

        Returns:
            Context dict containing ``conference``, ``speaker``, and ``talks``.
        """
        context = super().get_context_data(**kwargs)
        context["talks"] = self.object.talks.all()
        return context
