"""Views for bulk purchase management in the organizer dashboard."""

import logging
from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, DetailView, ListView

from django_program.manage.forms_bulk_purchases import BulkPurchaseCreateForm
from django_program.manage.views import ManagePermissionMixin
from django_program.registration.models import TicketType
from django_program.sponsors.models import BulkPurchase, BulkPurchaseVoucher, Sponsor
from django_program.sponsors.services import BulkPurchaseError, BulkPurchaseService

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest, HttpResponse

logger = logging.getLogger(__name__)


class BulkPurchaseListView(ManagePermissionMixin, ListView):
    """List all bulk purchases for the current conference.

    Supports optional filtering by payment status via the ``?status=``
    query parameter.
    """

    template_name = "django_program/manage/bulk_purchase_list.html"
    required_permission = "view_bulk_purchases"
    context_object_name = "bulk_purchases"
    paginate_by = 50

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` and status filter choices to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "bulk-purchases"
        context["status_choices"] = BulkPurchase.PaymentStatus.choices
        context["current_status"] = self.request.GET.get("status", "")
        return context

    def get_queryset(self) -> QuerySet[BulkPurchase]:
        """Return bulk purchases for the current conference, optionally filtered by status."""
        qs = (
            BulkPurchase.objects.filter(conference=self.conference)
            .select_related("sponsor", "ticket_type", "addon", "requested_by", "approved_by")
            .order_by("-created_at")
        )
        status = self.request.GET.get("status", "")
        if status and status in dict(BulkPurchase.PaymentStatus.choices):
            qs = qs.filter(payment_status=status)
        return qs


class BulkPurchaseDetailView(ManagePermissionMixin, DetailView):
    """Display full details of a bulk purchase with its generated voucher codes."""

    template_name = "django_program/manage/bulk_purchase_detail.html"
    required_permission = "view_bulk_purchases"
    context_object_name = "purchase"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` and related voucher data to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "bulk-purchases"
        context["voucher_links"] = (
            BulkPurchaseVoucher.objects.filter(bulk_purchase=self.object)
            .select_related("voucher")
            .order_by("-created_at")
        )
        return context

    def get_queryset(self) -> QuerySet[BulkPurchase]:
        """Scope to the current conference."""
        return BulkPurchase.objects.filter(conference=self.conference).select_related(
            "sponsor", "ticket_type", "addon", "requested_by", "approved_by"
        )


class BulkPurchaseCreateView(ManagePermissionMixin, CreateView):
    """Create a new bulk purchase on behalf of a sponsor."""

    template_name = "django_program/manage/bulk_purchase_form.html"
    required_permission = "change_bulk_purchases"
    form_class = BulkPurchaseCreateForm

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` and ``is_create`` to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "bulk-purchases"
        context["is_create"] = True
        return context

    def get_form(self, form_class: type[BulkPurchaseCreateForm] | None = None) -> BulkPurchaseCreateForm:
        """Scope sponsor, ticket type, and add-on querysets to the current conference."""
        from django_program.registration.models import AddOn  # noqa: PLC0415

        form = super().get_form(form_class)
        form.fields["sponsor"].queryset = Sponsor.objects.filter(conference=self.conference).order_by("name")
        form.fields["ticket_type"].queryset = TicketType.objects.filter(
            conference=self.conference, bulk_enabled=True
        ).order_by("name")
        form.fields["addon"].queryset = AddOn.objects.filter(conference=self.conference, bulk_enabled=True).order_by(
            "name"
        )
        return form

    def form_valid(self, form: BulkPurchaseCreateForm) -> HttpResponse:
        """Assign the conference and requesting user before saving."""
        form.instance.conference = self.conference
        form.instance.requested_by = self.request.user
        messages.success(self.request, "Bulk purchase created successfully.")
        return super().form_valid(form)

    def get_success_url(self) -> str:
        """Redirect to the bulk purchase list."""
        return reverse("manage:bulk-purchase-list", kwargs={"conference_slug": self.conference.slug})


class BulkPurchaseApproveView(ManagePermissionMixin, View):
    """Approve a pending bulk purchase (POST-only).

    Sets the payment status to APPROVED and records the approving user.
    The organizer must still configure voucher details and pricing before
    fulfillment can proceed.
    """

    required_permission = "change_bulk_purchases"

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Mark the bulk purchase as approved."""
        purchase = get_object_or_404(
            BulkPurchase,
            pk=self.kwargs["pk"],
            conference=self.conference,
        )
        if purchase.payment_status != BulkPurchase.PaymentStatus.PENDING:
            messages.error(request, "Only pending purchases can be approved.")
            return redirect(
                reverse(
                    "manage:bulk-purchase-detail",
                    kwargs={"conference_slug": self.conference.slug, "pk": purchase.pk},
                )
            )

        purchase.payment_status = BulkPurchase.PaymentStatus.APPROVED
        purchase.approved_by = request.user
        purchase.save(update_fields=["payment_status", "approved_by", "updated_at"])
        messages.success(
            request,
            f"Bulk purchase #{purchase.pk} approved. Configure voucher details and pricing before fulfillment.",
        )
        return redirect(
            reverse(
                "manage:bulk-purchase-detail",
                kwargs={"conference_slug": self.conference.slug, "pk": purchase.pk},
            )
        )


class BulkPurchaseFulfillView(ManagePermissionMixin, View):
    """Trigger voucher generation for a paid bulk purchase (POST-only).

    Generates voucher codes using the stored ``voucher_config`` and links
    them back to the purchase via ``BulkPurchaseVoucher`` records.
    """

    required_permission = "change_bulk_purchases"

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Generate vouchers for the bulk purchase."""
        purchase = get_object_or_404(
            BulkPurchase,
            pk=self.kwargs["pk"],
            conference=self.conference,
        )

        detail_url = reverse(
            "manage:bulk-purchase-detail",
            kwargs={"conference_slug": self.conference.slug, "pk": purchase.pk},
        )

        if purchase.payment_status not in (BulkPurchase.PaymentStatus.PAID, BulkPurchase.PaymentStatus.APPROVED):
            messages.error(request, "Only approved or paid purchases can be fulfilled.")
            return redirect(detail_url)

        try:
            vouchers = BulkPurchaseService.fulfill_bulk_purchase(purchase)
        except BulkPurchaseError as exc:
            messages.error(request, str(exc))
            return redirect(detail_url)
        except Exception:
            logger.exception("Failed to generate vouchers for BulkPurchase #%s", purchase.pk)
            messages.error(request, "Voucher generation failed. Please try again.")
            return redirect(detail_url)

        if not vouchers:
            messages.warning(request, "This purchase has already been fulfilled.")
        else:
            messages.success(request, f"Generated {len(vouchers)} voucher codes for bulk purchase #{purchase.pk}.")

        return redirect(detail_url)
