"""Views for managing Pretalx overrides and submission type defaults."""

from typing import TYPE_CHECKING, Any

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import CreateView, ListView, UpdateView

from django_program.manage.forms_overrides import (
    RoomOverrideForm,
    SpeakerOverrideForm,
    SponsorOverrideForm,
    SubmissionTypeDefaultForm,
    TalkOverrideForm,
)
from django_program.manage.views import ManagePermissionMixin
from django_program.pretalx.models import RoomOverride, SpeakerOverride, SubmissionTypeDefault, TalkOverride
from django_program.sponsors.models import SponsorOverride

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpResponse


# ===========================================================================
# Talk Overrides
# ===========================================================================


class TalkOverrideListView(ManagePermissionMixin, ListView):
    """List all talk overrides for the current conference."""

    template_name = "django_program/manage/override_list.html"
    context_object_name = "overrides"
    paginate_by = 50

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Return template context with navigation state."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "overrides"
        context["active_override_tab"] = "talks"
        return context

    def get_queryset(self) -> QuerySet[TalkOverride]:
        """Return overrides filtered to the current conference."""
        return (
            TalkOverride.objects.filter(conference=self.conference)
            .select_related("talk", "override_room", "created_by")
            .order_by("-updated_at")
        )


class TalkOverrideCreateView(ManagePermissionMixin, CreateView):
    """Create a new talk override for the current conference."""

    template_name = "django_program/manage/override_form.html"
    form_class = TalkOverrideForm

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Return template context with navigation state."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "overrides"
        context["active_override_tab"] = "talks"
        context["is_create"] = True
        return context

    def get_initial(self) -> dict[str, Any]:
        """Pre-populate the form from query parameters."""
        initial = super().get_initial()
        talk_pk = self.request.GET.get("talk")
        if talk_pk:
            initial["talk"] = talk_pk
        return initial

    def get_form_kwargs(self) -> dict[str, Any]:
        """Pass conference and edit mode to the form."""
        kwargs = super().get_form_kwargs()
        kwargs["conference"] = self.conference
        kwargs["is_edit"] = False
        return kwargs

    def form_valid(self, form: TalkOverrideForm) -> HttpResponse:
        """Save the override with conference and user context."""
        form.instance.conference = self.conference
        form.instance.created_by = self.request.user
        messages.success(self.request, "Talk override created.")
        return super().form_valid(form)

    def get_success_url(self) -> str:
        """Return the URL to redirect to after form submission."""
        return reverse("manage:override-list", kwargs={"conference_slug": self.conference.slug})


class TalkOverrideEditView(ManagePermissionMixin, UpdateView):
    """Edit an existing talk override."""

    template_name = "django_program/manage/override_form.html"
    form_class = TalkOverrideForm

    def get_queryset(self) -> QuerySet[TalkOverride]:
        """Return overrides filtered to the current conference."""
        return TalkOverride.objects.filter(conference=self.conference)

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Return template context with navigation state."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "overrides"
        context["active_override_tab"] = "talks"
        context["is_create"] = False
        return context

    def get_form_kwargs(self) -> dict[str, Any]:
        """Pass conference and edit mode to the form."""
        kwargs = super().get_form_kwargs()
        kwargs["conference"] = self.conference
        kwargs["is_edit"] = True
        return kwargs

    def form_valid(self, form: TalkOverrideForm) -> HttpResponse:
        """Save the override with conference and user context."""
        override = form.save(commit=False)
        if override.is_empty:
            override.delete()
            messages.success(self.request, "Override removed (all fields were empty).")
            return redirect(self.get_success_url())
        override.save()
        messages.success(self.request, "Talk override updated.")
        return redirect(self.get_success_url())

    def get_success_url(self) -> str:
        """Return the URL to redirect to after form submission."""
        return reverse("manage:override-list", kwargs={"conference_slug": self.conference.slug})


# ===========================================================================
# Speaker Overrides
# ===========================================================================


class SpeakerOverrideListView(ManagePermissionMixin, ListView):
    """List all speaker overrides for the current conference."""

    template_name = "django_program/manage/speaker_override_list.html"
    context_object_name = "overrides"
    paginate_by = 50

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Return template context with navigation state."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "overrides"
        context["active_override_tab"] = "speakers"
        return context

    def get_queryset(self) -> QuerySet[SpeakerOverride]:
        """Return overrides filtered to the current conference."""
        return (
            SpeakerOverride.objects.filter(conference=self.conference)
            .select_related("speaker", "created_by")
            .order_by("-updated_at")
        )


class SpeakerOverrideCreateView(ManagePermissionMixin, CreateView):
    """Create a new speaker override."""

    template_name = "django_program/manage/speaker_override_form.html"
    form_class = SpeakerOverrideForm

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Return template context with navigation state."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "overrides"
        context["active_override_tab"] = "speakers"
        context["is_create"] = True
        return context

    def get_initial(self) -> dict[str, Any]:
        """Pre-populate the form from query parameters."""
        initial = super().get_initial()
        speaker_pk = self.request.GET.get("speaker")
        if speaker_pk:
            initial["speaker"] = speaker_pk
        return initial

    def get_form_kwargs(self) -> dict[str, Any]:
        """Pass conference and edit mode to the form."""
        kwargs = super().get_form_kwargs()
        kwargs["conference"] = self.conference
        kwargs["is_edit"] = False
        return kwargs

    def form_valid(self, form: SpeakerOverrideForm) -> HttpResponse:
        """Save the override with conference and user context."""
        form.instance.conference = self.conference
        form.instance.created_by = self.request.user
        messages.success(self.request, "Speaker override created.")
        return super().form_valid(form)

    def get_success_url(self) -> str:
        """Return the URL to redirect to after form submission."""
        return reverse("manage:speaker-override-list", kwargs={"conference_slug": self.conference.slug})


class SpeakerOverrideEditView(ManagePermissionMixin, UpdateView):
    """Edit an existing speaker override."""

    template_name = "django_program/manage/speaker_override_form.html"
    form_class = SpeakerOverrideForm

    def get_queryset(self) -> QuerySet[SpeakerOverride]:
        """Return overrides filtered to the current conference."""
        return SpeakerOverride.objects.filter(conference=self.conference)

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Return template context with navigation state."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "overrides"
        context["active_override_tab"] = "speakers"
        context["is_create"] = False
        return context

    def get_form_kwargs(self) -> dict[str, Any]:
        """Pass conference and edit mode to the form."""
        kwargs = super().get_form_kwargs()
        kwargs["conference"] = self.conference
        kwargs["is_edit"] = True
        return kwargs

    def form_valid(self, form: SpeakerOverrideForm) -> HttpResponse:
        """Save the override with conference and user context."""
        override = form.save(commit=False)
        if override.is_empty:
            override.delete()
            messages.success(self.request, "Override removed (all fields were empty).")
            return redirect(self.get_success_url())
        override.save()
        messages.success(self.request, "Speaker override updated.")
        return redirect(self.get_success_url())

    def get_success_url(self) -> str:
        """Return the URL to redirect to after form submission."""
        return reverse("manage:speaker-override-list", kwargs={"conference_slug": self.conference.slug})


# ===========================================================================
# Room Overrides
# ===========================================================================


class RoomOverrideListView(ManagePermissionMixin, ListView):
    """List all room overrides for the current conference."""

    template_name = "django_program/manage/room_override_list.html"
    context_object_name = "overrides"
    paginate_by = 50

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Return template context with navigation state."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "overrides"
        context["active_override_tab"] = "rooms"
        return context

    def get_queryset(self) -> QuerySet[RoomOverride]:
        """Return overrides filtered to the current conference."""
        return (
            RoomOverride.objects.filter(conference=self.conference)
            .select_related("room", "created_by")
            .order_by("-updated_at")
        )


class RoomOverrideCreateView(ManagePermissionMixin, CreateView):
    """Create a new room override."""

    template_name = "django_program/manage/room_override_form.html"
    form_class = RoomOverrideForm

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Return template context with navigation state."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "overrides"
        context["active_override_tab"] = "rooms"
        context["is_create"] = True
        return context

    def get_initial(self) -> dict[str, Any]:
        """Pre-populate the form from query parameters."""
        initial = super().get_initial()
        room_pk = self.request.GET.get("room")
        if room_pk:
            initial["room"] = room_pk
        return initial

    def get_form_kwargs(self) -> dict[str, Any]:
        """Pass conference and edit mode to the form."""
        kwargs = super().get_form_kwargs()
        kwargs["conference"] = self.conference
        kwargs["is_edit"] = False
        return kwargs

    def form_valid(self, form: RoomOverrideForm) -> HttpResponse:
        """Save the override with conference and user context."""
        form.instance.conference = self.conference
        form.instance.created_by = self.request.user
        messages.success(self.request, "Room override created.")
        return super().form_valid(form)

    def get_success_url(self) -> str:
        """Return the URL to redirect to after form submission."""
        return reverse("manage:room-override-list", kwargs={"conference_slug": self.conference.slug})


class RoomOverrideEditView(ManagePermissionMixin, UpdateView):
    """Edit an existing room override."""

    template_name = "django_program/manage/room_override_form.html"
    form_class = RoomOverrideForm

    def get_queryset(self) -> QuerySet[RoomOverride]:
        """Return overrides filtered to the current conference."""
        return RoomOverride.objects.filter(conference=self.conference)

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Return template context with navigation state."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "overrides"
        context["active_override_tab"] = "rooms"
        context["is_create"] = False
        return context

    def get_form_kwargs(self) -> dict[str, Any]:
        """Pass conference and edit mode to the form."""
        kwargs = super().get_form_kwargs()
        kwargs["conference"] = self.conference
        kwargs["is_edit"] = True
        return kwargs

    def form_valid(self, form: RoomOverrideForm) -> HttpResponse:
        """Save the override with conference and user context."""
        override = form.save(commit=False)
        if override.is_empty:
            override.delete()
            messages.success(self.request, "Override removed (all fields were empty).")
            return redirect(self.get_success_url())
        override.save()
        messages.success(self.request, "Room override updated.")
        return redirect(self.get_success_url())

    def get_success_url(self) -> str:
        """Return the URL to redirect to after form submission."""
        return reverse("manage:room-override-list", kwargs={"conference_slug": self.conference.slug})


# ===========================================================================
# Sponsor Overrides
# ===========================================================================


class SponsorOverrideListView(ManagePermissionMixin, ListView):
    """List all sponsor overrides for the current conference."""

    template_name = "django_program/manage/sponsor_override_list.html"
    context_object_name = "overrides"
    paginate_by = 50

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Return template context with navigation state."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "overrides"
        context["active_override_tab"] = "sponsors"
        return context

    def get_queryset(self) -> QuerySet[SponsorOverride]:
        """Return overrides filtered to the current conference."""
        return (
            SponsorOverride.objects.filter(conference=self.conference)
            .select_related("sponsor", "sponsor__level", "override_level", "created_by")
            .order_by("-updated_at")
        )


class SponsorOverrideCreateView(ManagePermissionMixin, CreateView):
    """Create a new sponsor override."""

    template_name = "django_program/manage/sponsor_override_form.html"
    form_class = SponsorOverrideForm

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Return template context with navigation state."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "overrides"
        context["active_override_tab"] = "sponsors"
        context["is_create"] = True
        return context

    def get_initial(self) -> dict[str, Any]:
        """Pre-populate the form from query parameters."""
        initial = super().get_initial()
        sponsor_pk = self.request.GET.get("sponsor")
        if sponsor_pk:
            initial["sponsor"] = sponsor_pk
        return initial

    def get_form_kwargs(self) -> dict[str, Any]:
        """Pass conference and edit mode to the form."""
        kwargs = super().get_form_kwargs()
        kwargs["conference"] = self.conference
        kwargs["is_edit"] = False
        return kwargs

    def form_valid(self, form: SponsorOverrideForm) -> HttpResponse:
        """Save the override with conference and user context."""
        form.instance.conference = self.conference
        form.instance.created_by = self.request.user
        messages.success(self.request, "Sponsor override created.")
        return super().form_valid(form)

    def get_success_url(self) -> str:
        """Return the URL to redirect to after form submission."""
        return reverse("manage:sponsor-override-list", kwargs={"conference_slug": self.conference.slug})


class SponsorOverrideEditView(ManagePermissionMixin, UpdateView):
    """Edit an existing sponsor override."""

    template_name = "django_program/manage/sponsor_override_form.html"
    form_class = SponsorOverrideForm

    def get_queryset(self) -> QuerySet[SponsorOverride]:
        """Return overrides filtered to the current conference."""
        return SponsorOverride.objects.filter(conference=self.conference)

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Return template context with navigation state."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "overrides"
        context["active_override_tab"] = "sponsors"
        context["is_create"] = False
        return context

    def get_form_kwargs(self) -> dict[str, Any]:
        """Pass conference and edit mode to the form."""
        kwargs = super().get_form_kwargs()
        kwargs["conference"] = self.conference
        kwargs["is_edit"] = True
        return kwargs

    def form_valid(self, form: SponsorOverrideForm) -> HttpResponse:
        """Save the override with conference and user context."""
        override = form.save(commit=False)
        if override.is_empty:
            override.delete()
            messages.success(self.request, "Override removed (all fields were empty).")
            return redirect(self.get_success_url())
        override.save()
        messages.success(self.request, "Sponsor override updated.")
        return redirect(self.get_success_url())

    def get_success_url(self) -> str:
        """Return the URL to redirect to after form submission."""
        return reverse("manage:sponsor-override-list", kwargs={"conference_slug": self.conference.slug})


# ===========================================================================
# Submission Type Defaults
# ===========================================================================


class SubmissionTypeDefaultListView(ManagePermissionMixin, ListView):
    """List all submission type defaults for the current conference."""

    template_name = "django_program/manage/submission_type_default_list.html"
    context_object_name = "type_defaults"
    paginate_by = 50

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Return template context with navigation state."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "overrides"
        context["active_override_tab"] = "type-defaults"
        return context

    def get_queryset(self) -> QuerySet[SubmissionTypeDefault]:
        """Return overrides filtered to the current conference."""
        return (
            SubmissionTypeDefault.objects.filter(conference=self.conference)
            .select_related("default_room")
            .order_by("submission_type")
        )


class SubmissionTypeDefaultCreateView(ManagePermissionMixin, CreateView):
    """Create a new submission type default for the current conference."""

    template_name = "django_program/manage/submission_type_default_form.html"
    form_class = SubmissionTypeDefaultForm

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Return template context with navigation state."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "overrides"
        context["active_override_tab"] = "type-defaults"
        context["is_create"] = True
        return context

    def get_form_kwargs(self) -> dict[str, Any]:
        """Pass conference and edit mode to the form."""
        kwargs = super().get_form_kwargs()
        kwargs["conference"] = self.conference
        return kwargs

    def form_valid(self, form: SubmissionTypeDefaultForm) -> HttpResponse:
        """Save the override with conference and user context."""
        form.instance.conference = self.conference
        messages.success(self.request, "Submission type default created.")
        return super().form_valid(form)

    def get_success_url(self) -> str:
        """Return the URL to redirect to after form submission."""
        return reverse("manage:type-default-list", kwargs={"conference_slug": self.conference.slug})


class SubmissionTypeDefaultEditView(ManagePermissionMixin, UpdateView):
    """Edit an existing submission type default."""

    template_name = "django_program/manage/submission_type_default_form.html"
    form_class = SubmissionTypeDefaultForm

    def get_queryset(self) -> QuerySet[SubmissionTypeDefault]:
        """Return overrides filtered to the current conference."""
        return SubmissionTypeDefault.objects.filter(conference=self.conference)

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Return template context with navigation state."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "overrides"
        context["active_override_tab"] = "type-defaults"
        context["is_create"] = False
        return context

    def get_form_kwargs(self) -> dict[str, Any]:
        """Pass conference and edit mode to the form."""
        kwargs = super().get_form_kwargs()
        kwargs["conference"] = self.conference
        return kwargs

    def form_valid(self, form: SubmissionTypeDefaultForm) -> HttpResponse:
        """Save the override with conference and user context."""
        messages.success(self.request, "Submission type default updated.")
        return super().form_valid(form)

    def get_success_url(self) -> str:
        """Return the URL to redirect to after form submission."""
        return reverse("manage:type-default-list", kwargs={"conference_slug": self.conference.slug})
