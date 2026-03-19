"""Views for purchase order management in the organizer dashboard."""

import datetime
import logging
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from django.contrib import messages
from django.db.models import Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView

from django_program.manage.views import ManagePermissionMixin
from django_program.registration.purchase_order import (
    PurchaseOrder,
    PurchaseOrderCreditNote,
    PurchaseOrderLineItem,
    PurchaseOrderPayment,
)
from django_program.registration.services.purchase_orders import (
    cancel_purchase_order,
    create_purchase_order,
    generate_invoice_pdf,
    issue_credit_note,
    record_payment,
    send_purchase_order,
)
from django_program.registration.services.qbo_invoicing import (
    QBOAPIError,
    QBONotConfiguredError,
    create_qbo_invoice,
    send_qbo_invoice_email,
)
from django_program.registration.services.stripe_invoicing import create_stripe_invoice

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest

logger = logging.getLogger(__name__)


def _parse_line_items(
    descriptions: list[str],
    quantities: list[str],
    unit_prices: list[str],
) -> tuple[list[dict[str, object]], list[str]]:
    """Parse and validate line item data from POST lists.

    Args:
        descriptions: Line item description values.
        quantities: Line item quantity values.
        unit_prices: Line item unit price values.

    Returns:
        A tuple of (valid line items, error messages).
    """
    items: list[dict[str, object]] = []
    errors: list[str] = []
    for i, raw_desc in enumerate(descriptions):
        cleaned = raw_desc.strip()
        if not cleaned:
            continue
        try:
            qty = int(quantities[i]) if i < len(quantities) else 1
            price = Decimal(unit_prices[i]) if i < len(unit_prices) else Decimal("0.00")
        except ValueError, InvalidOperation:
            errors.append(f"Invalid quantity or price for line item {i + 1}.")
            continue
        if qty < 1:
            errors.append(f"Quantity must be at least 1 for line item {i + 1}.")
            continue
        if price < 0:
            errors.append(f"Unit price cannot be negative for line item {i + 1}.")
            continue
        items.append({"description": cleaned, "quantity": qty, "unit_price": price})
    return items, errors


class PurchaseOrderListView(ManagePermissionMixin, ListView):
    """List all purchase orders for the current conference.

    Supports optional filtering by status via the ``?status=`` query
    parameter.
    """

    template_name = "django_program/manage/purchase_order_list.html"
    context_object_name = "purchase_orders"
    paginate_by = 50

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav`` and status filter choices to the template context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "purchase-orders"
        context["status_choices"] = PurchaseOrder.Status.choices
        context["current_status"] = self.request.GET.get("status", "")
        return context

    def get_queryset(self) -> QuerySet[PurchaseOrder]:
        """Return purchase orders for the current conference, optionally filtered by status.

        Annotates ``_annotated_total_paid`` and ``_annotated_total_credited`` so
        that ``balance_due`` can be computed without per-row aggregate queries.
        """
        qs = (
            PurchaseOrder.objects.filter(conference=self.conference)
            .annotate(
                _annotated_total_paid=Coalesce(Sum("payments__amount"), Value(Decimal("0.00"))),
                _annotated_total_credited=Coalesce(Sum("credit_notes__amount"), Value(Decimal("0.00"))),
            )
            .order_by("-created_at")
        )
        status = self.request.GET.get("status", "")
        if status and status in dict(PurchaseOrder.Status.choices):
            qs = qs.filter(status=status)
        return qs


class PurchaseOrderDetailView(ManagePermissionMixin, DetailView):
    """Display full details of a purchase order with payments and credit notes."""

    template_name = "django_program/manage/purchase_order_detail.html"
    context_object_name = "purchase_order"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add ``active_nav``, line items, payments, and credit notes to context."""
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "purchase-orders"
        po = self.object
        context["line_items"] = PurchaseOrderLineItem.objects.filter(purchase_order=po)
        context["payments"] = PurchaseOrderPayment.objects.filter(purchase_order=po).select_related("entered_by")
        context["credit_notes"] = PurchaseOrderCreditNote.objects.filter(purchase_order=po).select_related("issued_by")
        context["payment_methods"] = PurchaseOrderPayment.Method.choices
        context["today"] = timezone.now().date().isoformat()
        return context

    def get_queryset(self) -> QuerySet[PurchaseOrder]:
        """Scope to the current conference."""
        return PurchaseOrder.objects.filter(conference=self.conference)


class PurchaseOrderCreateView(ManagePermissionMixin, View):
    """Create a new purchase order with line items.

    GET renders the create form. POST validates input and creates the PO
    via the service layer, then redirects to the detail view.
    """

    def get(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Render the blank purchase order form."""
        return TemplateResponse(
            request,
            "django_program/manage/purchase_order_form.html",
            {
                "conference": self.conference,
                "active_nav": "purchase-orders",
                "submission_type_nav": self.get_submission_type_nav(),
            },
        )

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Validate and create a purchase order from form data."""
        organization_name = request.POST.get("organization_name", "").strip()
        contact_email = request.POST.get("contact_email", "").strip()
        contact_name = request.POST.get("contact_name", "").strip()
        billing_address = request.POST.get("billing_address", "").strip()
        notes = request.POST.get("notes", "").strip()

        errors: list[str] = []
        if not organization_name:
            errors.append("Organization name is required.")
        if not contact_email:
            errors.append("Contact email is required.")

        line_items, line_errors = _parse_line_items(
            request.POST.getlist("line_description"),
            request.POST.getlist("line_quantity"),
            request.POST.getlist("line_unit_price"),
        )
        errors.extend(line_errors)

        if not line_items and not line_errors:
            errors.append("At least one line item is required.")

        if errors:
            for err in errors:
                messages.error(request, err)
            return TemplateResponse(
                request,
                "django_program/manage/purchase_order_form.html",
                {
                    "conference": self.conference,
                    "active_nav": "purchase-orders",
                    "submission_type_nav": self.get_submission_type_nav(),
                    "form_data": {
                        "organization_name": organization_name,
                        "contact_email": contact_email,
                        "contact_name": contact_name,
                        "billing_address": billing_address,
                        "notes": notes,
                    },
                    "line_items_data": line_items,
                },
            )

        try:
            po = create_purchase_order(
                conference=self.conference,
                organization_name=organization_name,
                contact_email=contact_email,
                contact_name=contact_name,
                billing_address=billing_address,
                line_items=line_items,
                notes=notes,
                created_by=request.user,
            )
        except Exception:
            logger.exception("Failed to create purchase order")
            messages.error(request, "Failed to create purchase order. Please try again.")
            return redirect(reverse("manage:purchase-order-list", kwargs={"conference_slug": self.conference.slug}))

        messages.success(request, f"Purchase order {po.reference} created.")
        return redirect(
            reverse(
                "manage:purchase-order-detail",
                kwargs={"conference_slug": self.conference.slug, "pk": po.pk},
            )
        )


class PurchaseOrderRecordPaymentView(ManagePermissionMixin, View):
    """Record a payment against a purchase order (POST-only)."""

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Validate and record a payment."""
        po = get_object_or_404(PurchaseOrder, pk=self.kwargs["pk"], conference=self.conference)
        detail_url = reverse(
            "manage:purchase-order-detail",
            kwargs={"conference_slug": self.conference.slug, "pk": po.pk},
        )

        if po.status == PurchaseOrder.Status.CANCELLED:
            messages.error(request, "Cannot record payment on a cancelled purchase order.")
            return redirect(detail_url)

        try:
            amount = Decimal(request.POST.get("amount", "0"))
        except InvalidOperation:
            messages.error(request, "Invalid payment amount.")
            return redirect(detail_url)

        if amount <= 0:
            messages.error(request, "Payment amount must be positive.")
            return redirect(detail_url)

        method = request.POST.get("method", PurchaseOrderPayment.Method.WIRE)
        if method not in dict(PurchaseOrderPayment.Method.choices):
            method = PurchaseOrderPayment.Method.WIRE

        reference_str = request.POST.get("reference", "").strip()
        note = request.POST.get("note", "").strip()
        payment_date_str = request.POST.get("payment_date", "")

        today = timezone.now().date()
        try:
            payment_date = datetime.date.fromisoformat(payment_date_str) if payment_date_str else today
        except ValueError:
            payment_date = today

        try:
            record_payment(
                po,
                amount=amount,
                method=method,
                reference=reference_str,
                payment_date=payment_date,
                entered_by=request.user,
                note=note,
            )
        except Exception:
            logger.exception("Failed to record payment for PO %s", po.reference)
            messages.error(request, "Failed to record payment. Please try again.")
            return redirect(detail_url)

        messages.success(request, f"Payment of ${amount} recorded for {po.reference}.")
        return redirect(detail_url)


class PurchaseOrderIssueCreditView(ManagePermissionMixin, View):
    """Issue a credit note against a purchase order (POST-only)."""

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Validate and issue a credit note."""
        po = get_object_or_404(PurchaseOrder, pk=self.kwargs["pk"], conference=self.conference)
        detail_url = reverse(
            "manage:purchase-order-detail",
            kwargs={"conference_slug": self.conference.slug, "pk": po.pk},
        )

        if po.status == PurchaseOrder.Status.CANCELLED:
            messages.error(request, "Cannot issue credit on a cancelled purchase order.")
            return redirect(detail_url)

        try:
            amount = Decimal(request.POST.get("amount", "0"))
        except InvalidOperation:
            messages.error(request, "Invalid credit amount.")
            return redirect(detail_url)

        if amount <= 0:
            messages.error(request, "Credit amount must be positive.")
            return redirect(detail_url)

        reason = request.POST.get("reason", "").strip()
        if not reason:
            messages.error(request, "A reason is required for credit notes.")
            return redirect(detail_url)

        try:
            issue_credit_note(po, amount=amount, reason=reason, issued_by=request.user)
        except Exception:
            logger.exception("Failed to issue credit note for PO %s", po.reference)
            messages.error(request, "Failed to issue credit note. Please try again.")
            return redirect(detail_url)

        messages.success(request, f"Credit note of ${amount} issued for {po.reference}.")
        return redirect(detail_url)


class PurchaseOrderCancelView(ManagePermissionMixin, View):
    """Cancel a purchase order (POST-only)."""

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Cancel the purchase order."""
        po = get_object_or_404(PurchaseOrder, pk=self.kwargs["pk"], conference=self.conference)
        detail_url = reverse(
            "manage:purchase-order-detail",
            kwargs={"conference_slug": self.conference.slug, "pk": po.pk},
        )

        if po.status in (PurchaseOrder.Status.CANCELLED, PurchaseOrder.Status.PAID):
            messages.error(request, f"Cannot cancel a purchase order with status '{po.get_status_display()}'.")
            return redirect(detail_url)

        try:
            cancel_purchase_order(po)
        except Exception:
            logger.exception("Failed to cancel PO %s", po.reference)
            messages.error(request, "Failed to cancel purchase order. Please try again.")
            return redirect(detail_url)

        messages.success(request, f"Purchase order {po.reference} has been cancelled.")
        return redirect(detail_url)


class PurchaseOrderSendView(ManagePermissionMixin, View):
    """Mark a draft purchase order as sent (POST-only)."""

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Transition the PO from draft to sent."""
        po = get_object_or_404(PurchaseOrder, pk=self.kwargs["pk"], conference=self.conference)
        detail_url = reverse(
            "manage:purchase-order-detail",
            kwargs={"conference_slug": self.conference.slug, "pk": po.pk},
        )

        try:
            send_purchase_order(po)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect(detail_url)
        except Exception:
            logger.exception("Failed to send PO %s", po.reference)
            messages.error(request, "Failed to send purchase order. Please try again.")
            return redirect(detail_url)

        messages.success(request, f"Purchase order {po.reference} marked as sent.")
        return redirect(detail_url)


class PurchaseOrderInvoiceView(ManagePermissionMixin, View):
    """Generate and download a PO invoice as PDF."""

    def get(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Generate the invoice PDF and return it as a downloadable attachment."""
        po = get_object_or_404(PurchaseOrder, pk=self.kwargs["pk"], conference=self.conference)
        pdf_bytes = generate_invoice_pdf(po)
        conf_slug = self.conference.slug
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{conf_slug}-invoice-{po.reference}.pdf"'
        return response


class PurchaseOrderStripeInvoiceView(ManagePermissionMixin, View):
    """Create and send a Stripe Invoice for a purchase order (POST-only).

    Uses the conference's Stripe keys to create a hosted invoice that the
    customer can pay via card or ACH. Sets the PO status to SENT on success.
    """

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Create a Stripe invoice and redirect back to the PO detail page."""
        po = get_object_or_404(PurchaseOrder, pk=self.kwargs["pk"], conference=self.conference)
        detail_url = reverse(
            "manage:purchase-order-detail",
            kwargs={"conference_slug": self.conference.slug, "pk": po.pk},
        )

        if po.status not in (PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.SENT):
            messages.error(
                request,
                f"Cannot send a Stripe invoice for a PO with status '{po.get_status_display()}'.",
            )
            return redirect(detail_url)

        try:
            hosted_url = create_stripe_invoice(po)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect(detail_url)
        except Exception:
            logger.exception("Failed to create Stripe invoice for PO %s", po.reference)
            messages.error(request, "Failed to create Stripe invoice. Please try again.")
            return redirect(detail_url)

        if po.status == PurchaseOrder.Status.DRAFT:
            po.status = PurchaseOrder.Status.SENT
            po.save(update_fields=["status", "updated_at"])

        messages.success(
            request,
            f"Stripe invoice sent for {po.reference}. Customer invoice URL: {hosted_url}",
        )
        return redirect(detail_url)


class PurchaseOrderQBOInvoiceView(ManagePermissionMixin, View):
    """Create and send a QuickBooks Online Invoice for a purchase order (POST-only).

    Uses the conference's QBO credentials to create an invoice via the QBO
    REST API and optionally emails it to the customer. Sets the PO status
    to SENT on success if currently in draft.
    """

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Create a QBO invoice and redirect back to the PO detail page."""
        po = get_object_or_404(PurchaseOrder, pk=self.kwargs["pk"], conference=self.conference)
        detail_url = reverse(
            "manage:purchase-order-detail",
            kwargs={"conference_slug": self.conference.slug, "pk": po.pk},
        )

        error_msg = self._validate_po_for_qbo(po)
        if error_msg:
            messages.error(request, error_msg) if "already" not in error_msg else messages.warning(request, error_msg)
            return redirect(detail_url)

        try:
            create_qbo_invoice(po)
            send_qbo_invoice_email(po)
        except QBONotConfiguredError:
            messages.error(request, "QuickBooks Online is not configured for this conference.")
            return redirect(detail_url)
        except (QBOAPIError, ValueError) as exc:
            messages.error(request, f"QBO invoice failed: {exc}")
            return redirect(detail_url)
        except Exception:
            logger.exception("Failed to create/send QBO invoice for PO %s", po.reference)
            messages.error(request, "Failed to create QBO invoice. Please try again.")
            return redirect(detail_url)

        if po.status == PurchaseOrder.Status.DRAFT:
            po.status = PurchaseOrder.Status.SENT
            po.save(update_fields=["status", "updated_at"])

        messages.success(request, f"QBO invoice created and sent for {po.reference}.")
        return redirect(detail_url)

    @staticmethod
    def _validate_po_for_qbo(po: PurchaseOrder) -> str:
        """Return an error message if the PO cannot have a QBO invoice created, or empty string."""
        if po.status not in (PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.SENT):
            return f"Cannot send a QBO invoice for a PO with status '{po.get_status_display()}'."
        if po.qbo_invoice_id:
            return f"PO {po.reference} already has a QBO invoice."
        return ""
