"""Views for the sponsors app.

Provides sponsor listing and detail views scoped to a conference
via the ``conference_slug`` URL kwarg, plus a self-service portal
where sponsor contacts can view purchases, download voucher CSVs,
and request new bulk purchases.
"""

import csv
import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, FormView, ListView, TemplateView

from django_program.conference.models import Conference
from django_program.features import FeatureRequiredMixin
from django_program.pretalx.views import ConferenceMixin
from django_program.sponsors.forms import BulkPurchaseRequestForm
from django_program.sponsors.models import BulkPurchase, BulkPurchaseVoucher, Sponsor, SponsorLevel

if TYPE_CHECKING:
    from django.db.models import QuerySet

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public views
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Sponsor self-service portal
# ---------------------------------------------------------------------------


class SponsorPortalMixin(LoginRequiredMixin):
    """Permission mixin for the sponsor self-service portal.

    Resolves the conference from the ``conference_slug`` URL kwarg and
    verifies that the authenticated user's email matches the sponsor's
    ``contact_email``, or that the user is staff/superuser.

    Sets ``self.conference`` and ``self.sponsor`` for use by subclasses.
    """

    conference: Conference
    sponsor: Sponsor
    kwargs: dict[str, str]

    def dispatch(self, request: HttpRequest, *args: str, **kwargs: str) -> HttpResponse:
        """Resolve the conference and sponsor, then enforce access.

        Performs conference resolution and sponsor authorization BEFORE
        calling ``super().dispatch()`` so that ``self.conference`` and
        ``self.sponsor`` are available when the view method executes.

        Args:
            request: The incoming HTTP request.
            *args: Positional arguments from the URL resolver.
            **kwargs: Keyword arguments from the URL pattern.

        Returns:
            The HTTP response.

        Raises:
            PermissionDenied: If the user is not authorized for this sponsor portal.
        """
        if not request.user.is_authenticated:
            return self.handle_no_permission()  # type: ignore[return-value]

        self.conference = get_object_or_404(Conference, slug=kwargs.get("conference_slug", ""))
        self.sponsor = self._resolve_sponsor()
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]

    def _resolve_sponsor(self) -> Sponsor:
        """Find the sponsor this user is authorized to view.

        Returns:
            The matched Sponsor instance.

        Raises:
            PermissionDenied: If no sponsor matches the user's email and
                the user is not staff/superuser.
        """
        request = self.request  # type: ignore[attr-defined]
        if request.user.is_superuser or request.user.is_staff:
            sponsors = Sponsor.objects.filter(conference=self.conference, is_active=True)
            if sponsors.exists():
                return sponsors.first()  # type: ignore[return-value]
            raise PermissionDenied("No active sponsors found for this conference.")

        user_email = request.user.email
        if not user_email:
            raise PermissionDenied("Your account has no email address configured.")

        sponsors = Sponsor.objects.filter(conference=self.conference, is_active=True).select_related(
            "level", "override"
        )
        for sponsor in sponsors:
            if sponsor.effective_contact_email.lower() == user_email.lower():
                return sponsor

        raise PermissionDenied("You do not have access to any sponsor portal for this conference.")

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Inject conference and sponsor into the template context.

        Args:
            **kwargs: Additional context data.

        Returns:
            Context dict with ``conference`` and ``sponsor``.
        """
        context: dict[str, object] = super().get_context_data(**kwargs)  # type: ignore[misc]
        context["conference"] = self.conference
        context["sponsor"] = self.sponsor
        return context


class SponsorPortalView(SponsorPortalMixin, TemplateView):
    """Landing page for the sponsor self-service portal.

    Shows sponsor info and a list of all bulk purchases with their
    current status.
    """

    template_name = "django_program/sponsors/portal_home.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add bulk purchases to the template context.

        Returns:
            Context dict with ``purchases`` queryset.
        """
        context = super().get_context_data(**kwargs)
        context["purchases"] = (
            BulkPurchase.objects.filter(sponsor=self.sponsor).select_related("ticket_type").order_by("-created_at")
        )
        return context


class BulkPurchaseDetailView(SponsorPortalMixin, TemplateView):
    """Detail view for a specific bulk purchase.

    Shows all voucher codes associated with the purchase along with
    their redemption counts.
    """

    template_name = "django_program/sponsors/purchase_detail.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add purchase and voucher details to context.

        Returns:
            Context dict with ``purchase``, ``voucher_links``, and summary stats.
        """
        context = super().get_context_data(**kwargs)
        purchase = get_object_or_404(
            BulkPurchase.objects.select_related("sponsor", "ticket_type"),
            pk=self.kwargs["pk"],
            sponsor=self.sponsor,
        )
        voucher_links = (
            BulkPurchaseVoucher.objects.filter(bulk_purchase=purchase)
            .select_related("voucher")
            .order_by("voucher__code")
        )

        total_uses = sum(link.voucher.times_used for link in voucher_links)
        total_max = sum(link.voucher.max_uses for link in voucher_links)

        context["purchase"] = purchase
        context["voucher_links"] = voucher_links
        context["total_uses"] = total_uses
        context["total_max"] = total_max
        return context


class BulkPurchaseExportCSVView(SponsorPortalMixin, View):
    """Export voucher codes for a bulk purchase as a CSV download."""

    def get(self, request: HttpRequest, *args: str, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Generate and return the CSV response.

        Args:
            request: The incoming HTTP request.
            *args: Positional arguments from the URL resolver.
            **kwargs: Keyword arguments from the URL pattern.

        Returns:
            An HTTP response with CSV content disposition.
        """
        purchase = get_object_or_404(
            BulkPurchase,
            pk=self.kwargs["pk"],
            sponsor=self.sponsor,
        )
        voucher_links = (
            BulkPurchaseVoucher.objects.filter(bulk_purchase=purchase)
            .select_related("voucher")
            .order_by("voucher__code")
        )

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="vouchers-purchase-{purchase.pk}.csv"'

        writer = csv.writer(response)
        writer.writerow(["code", "times_used", "max_uses", "is_active", "valid_from", "valid_until"])

        for link in voucher_links:
            v = link.voucher
            writer.writerow(
                [
                    str(v.code),
                    v.times_used,
                    v.max_uses,
                    v.is_active,
                    v.valid_from.isoformat() if v.valid_from else "",
                    v.valid_until.isoformat() if v.valid_until else "",
                ]
            )

        return response


class BulkPurchaseRequestView(SponsorPortalMixin, FormView):
    """Form view for sponsors to request a new bulk voucher purchase.

    Creates a BulkPurchase in PENDING state for organizer approval.
    """

    template_name = "django_program/sponsors/purchase_request.html"
    form_class = BulkPurchaseRequestForm

    def form_valid(self, form: BulkPurchaseRequestForm) -> HttpResponse:
        """Create a pending BulkPurchase from the form data.

        Args:
            form: The validated form instance.

        Returns:
            A redirect to the portal home page.
        """
        quantity = form.cleaned_data["quantity"]
        notes = form.cleaned_data.get("notes", "")
        ticket_pref = form.cleaned_data.get("ticket_type_preference", "")

        BulkPurchase.objects.create(
            conference=self.conference,
            sponsor=self.sponsor,
            quantity=quantity,
            product_description=ticket_pref,
            payment_status=BulkPurchase.PaymentStatus.PENDING,
            unit_price=Decimal("0.00"),
            total_amount=Decimal("0.00"),
            voucher_config={"notes": notes, "ticket_type_preference": ticket_pref},
            requested_by=self.request.user,
        )

        logger.info(
            "Sponsor %s requested bulk purchase of %d vouchers for %s",
            self.sponsor.name,
            quantity,
            self.conference.slug,
        )

        return redirect(
            reverse(
                "sponsors:portal-home",
                kwargs={"conference_slug": self.conference.slug},
            )
        )
