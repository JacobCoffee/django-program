"""Visa & Invitation Letter management views for the manage app.

Provides the staff-facing interface for reviewing, approving, generating,
and sending invitation letters for conference attendees who need visa
support documentation.
"""

import logging

from django.contrib import messages
from django.db.models import Count, QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView

from django_program.manage.views import ManagePermissionMixin
from django_program.registration.letter import LetterRequest
from django_program.registration.services.letters import generate_invitation_letter, send_invitation_letter

logger = logging.getLogger(__name__)


class LetterRequestListView(ManagePermissionMixin, ListView):
    """Staff list of all letter requests for a conference.

    Supports filtering by status via the ``?status=`` query parameter and
    provides aggregate status counts for the sidebar/header summary.
    """

    template_name = "django_program/manage/letter_request_list.html"
    required_permission = "view_registration"
    context_object_name = "letter_requests"
    paginate_by = 50

    def get_queryset(self) -> QuerySet[LetterRequest]:
        """Return letter requests for the current conference, optionally filtered by status.

        Returns:
            Queryset of letter requests ordered by creation date descending.
        """
        qs = (
            LetterRequest.objects.filter(conference=self.conference)
            .select_related("user", "attendee", "reviewed_by")
            .order_by("-created_at")
        )
        status = self.request.GET.get("status", "").strip()
        if status and status in LetterRequest.Status.values:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add status filter state and aggregate counts to the template context.

        Args:
            **kwargs: Additional context data.

        Returns:
            Template context with status counts, active filter, and navigation state.
        """
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "letters"
        context["current_status"] = self.request.GET.get("status", "")

        counts = LetterRequest.objects.filter(conference=self.conference).values("status").annotate(count=Count("id"))
        status_counts: dict[str, int] = {s.value: 0 for s in LetterRequest.Status}
        for row in counts:
            status_counts[row["status"]] = row["count"]
        context["status_counts"] = status_counts
        context["total_count"] = sum(status_counts.values())
        return context


class LetterRequestReviewView(ManagePermissionMixin, DetailView):
    """Review a single letter request with status transition actions.

    GET renders the detail page with available actions. POST handles
    status transitions: approve, reject (with reason), or mark as
    under review.
    """

    template_name = "django_program/manage/letter_request_review.html"
    required_permission = "change_registration"
    context_object_name = "letter_request"

    def get_queryset(self) -> QuerySet[LetterRequest]:
        """Scope to the current conference with related objects.

        Returns:
            Queryset of letter requests for the active conference.
        """
        return LetterRequest.objects.filter(conference=self.conference).select_related(
            "user", "attendee", "reviewed_by"
        )

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add navigation state and available actions to context.

        Args:
            **kwargs: Additional context data.

        Returns:
            Template context with letter request detail and action flags.
        """
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "letters"
        lr: LetterRequest = self.object  # type: ignore[assignment]
        context["can_approve"] = lr.status in (
            LetterRequest.Status.SUBMITTED,
            LetterRequest.Status.UNDER_REVIEW,
        )
        context["can_reject"] = lr.status in (
            LetterRequest.Status.SUBMITTED,
            LetterRequest.Status.UNDER_REVIEW,
        )
        context["can_generate"] = lr.status == LetterRequest.Status.APPROVED
        context["can_send"] = lr.status == LetterRequest.Status.GENERATED
        context["can_download"] = bool(lr.generated_pdf)
        return context

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Handle status transition actions on a letter request.

        Supported actions via the ``action`` POST parameter:
        - ``under_review``: Move to under-review status.
        - ``approve``: Approve the request and record reviewer.
        - ``reject``: Reject the request with a reason and record reviewer.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments including ``pk``.

        Returns:
            A redirect back to the review page.
        """
        letter_request = self.get_object()
        action = request.POST.get("action", "")
        review_url = reverse(
            "manage:letter-review",
            kwargs={"conference_slug": self.conference.slug, "pk": letter_request.pk},
        )

        action_map = {
            "under_review": LetterRequest.Status.UNDER_REVIEW,
            "approve": LetterRequest.Status.APPROVED,
            "reject": LetterRequest.Status.REJECTED,
        }
        target_status = action_map.get(action)
        if target_status is None:
            messages.error(request, "Invalid action or status transition.")
            return redirect(review_url)

        if action == "reject":
            reason = request.POST.get("rejection_reason", "").strip()
            if not reason:
                messages.error(request, "A rejection reason is required.")
                return redirect(review_url)

        try:
            letter_request.transition_to(target_status)
        except ValueError:
            messages.error(request, "Invalid action or status transition.")
            return redirect(review_url)

        if action in ("approve", "reject"):
            letter_request.reviewed_by = request.user
            letter_request.reviewed_at = timezone.now()

        update_fields = ["status", "updated_at"]
        if action == "reject":
            letter_request.rejection_reason = reason
            update_fields.extend(["rejection_reason", "reviewed_by", "reviewed_at"])
        elif action == "approve":
            update_fields.extend(["reviewed_by", "reviewed_at"])

        letter_request.save(update_fields=update_fields)

        action_labels = {
            "under_review": "Letter request marked as under review.",
            "approve": "Letter request approved.",
            "reject": "Letter request rejected.",
        }
        messages.success(request, action_labels[action])

        return redirect(review_url)


class LetterRequestGenerateView(ManagePermissionMixin, View):
    """Generate an invitation letter PDF for an approved request.

    POST-only. Calls the letter generation service and redirects back
    to the review page.
    """

    required_permission = "change_registration"

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:
        """Generate the PDF for an approved letter request.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments including ``pk``.

        Returns:
            A redirect to the letter review page.
        """
        letter_request = get_object_or_404(LetterRequest, pk=kwargs["pk"], conference=self.conference)
        review_url = reverse(
            "manage:letter-review",
            kwargs={"conference_slug": self.conference.slug, "pk": letter_request.pk},
        )

        if letter_request.status != LetterRequest.Status.APPROVED:
            messages.error(request, "Only approved requests can have PDFs generated.")
            return redirect(review_url)

        try:
            generate_invitation_letter(letter_request)
            messages.success(request, "Invitation letter PDF generated successfully.")
        except Exception:
            logger.exception("Failed to generate invitation letter for request %s", letter_request.pk)
            messages.error(request, "Failed to generate the invitation letter PDF.")

        return redirect(review_url)


class LetterRequestBulkGenerateView(ManagePermissionMixin, View):
    """Bulk-generate invitation letter PDFs for all approved requests.

    POST-only. Generates PDFs for every letter request in the conference
    that has ``APPROVED`` status, then redirects to the list view with a
    summary message.
    """

    required_permission = "change_registration"

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Generate PDFs for all approved letter requests in the conference.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments.

        Returns:
            A redirect to the letter request list.
        """
        approved = LetterRequest.objects.filter(conference=self.conference, status=LetterRequest.Status.APPROVED)
        generated = 0
        failed = 0
        for letter_request in approved:
            try:
                generate_invitation_letter(letter_request)
                generated += 1
            except Exception:
                logger.exception("Failed to generate letter for request %s", letter_request.pk)
                failed += 1

        if generated:
            messages.success(request, f"Generated {generated} invitation letter(s).")
        if failed:
            messages.error(request, f"Failed to generate {failed} letter(s). Check logs for details.")
        if not generated and not failed:
            messages.info(request, "No approved letter requests to generate.")

        return redirect(reverse("manage:letter-list", kwargs={"conference_slug": self.conference.slug}))


class LetterRequestSendView(ManagePermissionMixin, View):
    """Send a generated invitation letter to the requester.

    POST-only. Calls the letter sending service, updates the sent
    timestamp, and redirects back to the review page.
    """

    required_permission = "change_registration"

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:
        """Send the invitation letter for a generated request.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments including ``pk``.

        Returns:
            A redirect to the letter review page.
        """
        letter_request = get_object_or_404(LetterRequest, pk=kwargs["pk"], conference=self.conference)
        review_url = reverse(
            "manage:letter-review",
            kwargs={"conference_slug": self.conference.slug, "pk": letter_request.pk},
        )

        if letter_request.status != LetterRequest.Status.GENERATED:
            messages.error(request, "Only generated letters can be sent.")
            return redirect(review_url)

        try:
            send_invitation_letter(letter_request)
            messages.success(request, "Invitation letter sent successfully.")
        except Exception:
            logger.exception("Failed to send invitation letter for request %s", letter_request.pk)
            messages.error(request, "Failed to send the invitation letter.")

        return redirect(review_url)


class LetterRequestDownloadView(ManagePermissionMixin, View):
    """Download the generated PDF for a letter request.

    GET-only. Returns the PDF file as an attachment response. Only works
    if a generated PDF exists on the letter request. Requires write-level
    access because the PDF contains passport PII.
    """

    required_permission = "change_registration"

    def get(self, request: HttpRequest, **kwargs: str) -> HttpResponse:
        """Return the generated PDF as a downloadable attachment.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments including ``pk``.

        Returns:
            An HTTP response with the PDF content.
        """
        letter_request = get_object_or_404(
            LetterRequest.objects.select_related("user"),
            pk=kwargs["pk"],
            conference=self.conference,
        )
        list_url = reverse("manage:letter-list", kwargs={"conference_slug": self.conference.slug})

        if not letter_request.generated_pdf:
            messages.error(request, "No PDF has been generated for this request.")
            return redirect(list_url)

        username = letter_request.user.username
        filename = f"invitation-letter-{username}.pdf"
        with letter_request.generated_pdf.open("rb") as pdf_file:
            pdf_data = pdf_file.read()
        response = HttpResponse(pdf_data, content_type="application/pdf")
        disposition = "inline" if request.GET.get("inline") else "attachment"
        response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
        return response
