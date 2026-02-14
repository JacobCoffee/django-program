"""Views for the sponsors app.

Provides sponsor listing and detail views scoped to a conference
via the ``conference_slug`` URL kwarg.
"""

from typing import TYPE_CHECKING

from django.shortcuts import get_object_or_404
from django.views.generic import DetailView, ListView

from django_program.features import FeatureRequiredMixin
from django_program.pretalx.views import ConferenceMixin
from django_program.sponsors.models import Sponsor, SponsorLevel

if TYPE_CHECKING:
    from django.db.models import QuerySet


class SponsorListView(ConferenceMixin, FeatureRequiredMixin, ListView):
    """List view of all active sponsors for a conference, grouped by level."""

    required_feature = ("sponsors", "public_ui")
    template_name = "django_program/sponsors/sponsor_list.html"
    context_object_name = "sponsors"

    def get_queryset(self) -> QuerySet[Sponsor]:
        """Return active sponsors for the current conference.

        Returns:
            A queryset of active Sponsor instances ordered by level and name.
        """
        return (
            Sponsor.objects.filter(conference=self.conference, is_active=True)
            .select_related("level")
            .order_by("level__order", "name")
        )

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add sponsor levels to the template context.

        Returns:
            Context dict containing ``conference``, ``sponsors``, and ``levels``.
        """
        context = super().get_context_data(**kwargs)
        context["levels"] = (
            SponsorLevel.objects.filter(conference=self.conference, sponsors__is_active=True)
            .distinct()
            .order_by("order")
        )
        return context


class SponsorDetailView(ConferenceMixin, FeatureRequiredMixin, DetailView):
    """Detail view for a single sponsor."""

    required_feature = ("sponsors", "public_ui")
    template_name = "django_program/sponsors/sponsor_detail.html"
    context_object_name = "sponsor"

    def get_object(self, queryset: QuerySet[Sponsor] | None = None) -> Sponsor:  # noqa: ARG002
        """Look up the sponsor by conference and slug.

        Returns:
            The matched Sponsor instance.

        Raises:
            Http404: If no active sponsor matches the conference and slug.
        """
        return get_object_or_404(
            Sponsor.objects.select_related("level"),
            conference=self.conference,
            slug=self.kwargs["slug"],
            is_active=True,
        )

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add benefits to the template context.

        Returns:
            Context dict containing ``conference``, ``sponsor``, and ``benefits``.
        """
        context = super().get_context_data(**kwargs)
        context["benefits"] = self.object.benefits.all()
        return context
