"""Views for voucher bulk operations in the management dashboard."""

import logging
from typing import TYPE_CHECKING

from django.contrib import messages
from django.db import IntegrityError
from django.urls import reverse
from django.views.generic import FormView

from django_program.manage.forms_vouchers import VoucherBulkGenerateForm
from django_program.manage.views import ManagePermissionMixin
from django_program.registration.models import AddOn, TicketType
from django_program.registration.services.voucher_service import VoucherBulkConfig, generate_voucher_codes

if TYPE_CHECKING:
    from django.http import HttpResponse

logger = logging.getLogger(__name__)


class VoucherBulkGenerateView(ManagePermissionMixin, FormView):
    """Bulk-generate a batch of voucher codes for the current conference.

    Renders a form for configuring the batch parameters (prefix, count,
    discount type, etc.) and delegates to the voucher service for creation.
    On success, redirects to the voucher list with a confirmation message.
    """

    template_name = "django_program/manage/voucher_bulk_generate.html"
    form_class = VoucherBulkGenerateForm

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "vouchers"
        return context

    def get_form(self, form_class: type[VoucherBulkGenerateForm] | None = None) -> VoucherBulkGenerateForm:
        """Scope the ticket type and add-on querysets to the current conference."""
        form = super().get_form(form_class)
        form.fields["applicable_ticket_types"].queryset = TicketType.objects.filter(conference=self.conference)
        form.fields["applicable_addons"].queryset = AddOn.objects.filter(conference=self.conference)
        return form

    def form_valid(self, form: VoucherBulkGenerateForm) -> HttpResponse:
        """Generate the voucher batch and redirect to the voucher list."""
        data = form.cleaned_data
        config = VoucherBulkConfig(
            conference=self.conference,
            prefix=data["prefix"],
            count=data["count"],
            voucher_type=data["voucher_type"],
            discount_value=data["discount_value"],
            max_uses=data["max_uses"],
            valid_from=data.get("valid_from"),
            valid_until=data.get("valid_until"),
            unlocks_hidden_tickets=data.get("unlocks_hidden_tickets", False),
            applicable_ticket_types=data.get("applicable_ticket_types"),
            applicable_addons=data.get("applicable_addons"),
        )
        try:
            created = generate_voucher_codes(config)
            messages.success(
                self.request,
                f"Successfully generated {len(created)} voucher codes with prefix '{data['prefix']}'.",
            )
        except (RuntimeError, IntegrityError):  # fmt: skip
            logger.exception("Voucher bulk generation failed")
            messages.error(self.request, "Failed to generate voucher codes. Please try again.")

        return super().form_valid(form)

    def get_success_url(self) -> str:
        """Redirect to the voucher list after generation."""
        return reverse("manage:voucher-list", kwargs={"conference_slug": self.conference.slug})
