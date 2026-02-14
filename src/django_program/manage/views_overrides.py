"""Views for managing Pretalx talk overrides and submission type defaults."""

from typing import TYPE_CHECKING, Any

from django.contrib import messages
from django.urls import reverse
from django.views.generic import CreateView, ListView, UpdateView

from django_program.manage.forms_overrides import SubmissionTypeDefaultForm, TalkOverrideForm
from django_program.manage.views import ManagePermissionMixin
from django_program.pretalx.models import SubmissionTypeDefault, TalkOverride

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpResponse


class TalkOverrideListView(ManagePermissionMixin, ListView):
    """List all talk overrides for the current conference."""

    template_name = "django_program/manage/override_list.html"
    context_object_name = "overrides"
    paginate_by = 50

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add active_nav to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "talks"
        return context

    def get_queryset(self) -> QuerySet[TalkOverride]:
        """Return overrides belonging to the current conference.

        Returns:
            A queryset of TalkOverride instances with related talk and room data.
        """
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
        """Add active_nav and is_create to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "talks"
        context["is_create"] = True
        return context

    def get_form_kwargs(self) -> dict[str, Any]:
        """Pass conference to the form for scoping querysets."""
        kwargs = super().get_form_kwargs()
        kwargs["conference"] = self.conference
        kwargs["is_edit"] = False
        return kwargs

    def form_valid(self, form: TalkOverrideForm) -> HttpResponse:
        """Assign the conference and created_by before saving."""
        form.instance.conference = self.conference
        form.instance.created_by = self.request.user
        messages.success(self.request, "Talk override created.")
        return super().form_valid(form)

    def get_success_url(self) -> str:
        """Redirect to the override list after creation."""
        return reverse("manage:override-list", kwargs={"conference_slug": self.conference.slug})


class TalkOverrideEditView(ManagePermissionMixin, UpdateView):
    """Edit an existing talk override."""

    template_name = "django_program/manage/override_form.html"
    form_class = TalkOverrideForm

    def get_queryset(self) -> QuerySet[TalkOverride]:
        """Scope the queryset to the current conference.

        Returns:
            A queryset of TalkOverride instances for this conference.
        """
        return TalkOverride.objects.filter(conference=self.conference)

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add active_nav to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "talks"
        context["is_create"] = False
        return context

    def get_form_kwargs(self) -> dict[str, Any]:
        """Pass conference and is_edit to the form."""
        kwargs = super().get_form_kwargs()
        kwargs["conference"] = self.conference
        kwargs["is_edit"] = True
        return kwargs

    def form_valid(self, form: TalkOverrideForm) -> HttpResponse:
        """Save the override and redirect."""
        messages.success(self.request, "Talk override updated.")
        return super().form_valid(form)

    def get_success_url(self) -> str:
        """Redirect to the override list after editing."""
        return reverse("manage:override-list", kwargs={"conference_slug": self.conference.slug})


class SubmissionTypeDefaultListView(ManagePermissionMixin, ListView):
    """List all submission type defaults for the current conference."""

    template_name = "django_program/manage/submission_type_default_list.html"
    context_object_name = "type_defaults"
    paginate_by = 50

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add active_nav to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "talks"
        return context

    def get_queryset(self) -> QuerySet[SubmissionTypeDefault]:
        """Return type defaults belonging to the current conference.

        Returns:
            A queryset of SubmissionTypeDefault instances with related room data.
        """
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
        """Add active_nav and is_create to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "talks"
        context["is_create"] = True
        return context

    def get_form_kwargs(self) -> dict[str, Any]:
        """Pass conference to the form for scoping querysets."""
        kwargs = super().get_form_kwargs()
        kwargs["conference"] = self.conference
        return kwargs

    def form_valid(self, form: SubmissionTypeDefaultForm) -> HttpResponse:
        """Assign the conference before saving."""
        form.instance.conference = self.conference
        messages.success(self.request, "Submission type default created.")
        return super().form_valid(form)

    def get_success_url(self) -> str:
        """Redirect to the type defaults list after creation."""
        return reverse("manage:type-default-list", kwargs={"conference_slug": self.conference.slug})


class SubmissionTypeDefaultEditView(ManagePermissionMixin, UpdateView):
    """Edit an existing submission type default."""

    template_name = "django_program/manage/submission_type_default_form.html"
    form_class = SubmissionTypeDefaultForm

    def get_queryset(self) -> QuerySet[SubmissionTypeDefault]:
        """Scope the queryset to the current conference.

        Returns:
            A queryset of SubmissionTypeDefault instances for this conference.
        """
        return SubmissionTypeDefault.objects.filter(conference=self.conference)

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add active_nav to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "talks"
        context["is_create"] = False
        return context

    def get_form_kwargs(self) -> dict[str, Any]:
        """Pass conference to the form."""
        kwargs = super().get_form_kwargs()
        kwargs["conference"] = self.conference
        return kwargs

    def form_valid(self, form: SubmissionTypeDefaultForm) -> HttpResponse:
        """Save the type default and redirect."""
        messages.success(self.request, "Submission type default updated.")
        return super().form_valid(form)

    def get_success_url(self) -> str:
        """Redirect to the type defaults list after editing."""
        return reverse("manage:type-default-list", kwargs={"conference_slug": self.conference.slug})
