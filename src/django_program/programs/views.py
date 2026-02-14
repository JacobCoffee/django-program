"""Views for the programs app.

Provides activity listing, detail, signup, travel grant application,
status, accept, decline, withdraw, edit, and messaging views scoped
to a conference via the ``conference_slug`` URL kwarg.
"""

import itertools
from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, models, transaction
from django.db.models import Count, Prefetch, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView

from django_program.features import FeatureRequiredMixin
from django_program.pretalx.views import ConferenceMixin
from django_program.programs.forms import (
    PaymentInfoForm,
    ReceiptForm,
    TravelGrantApplicationForm,
    TravelGrantMessageForm,
)
from django_program.programs.models import (
    Activity,
    ActivitySignup,
    PaymentInfo,
    Receipt,
    TravelGrant,
    TravelGrantMessage,
)

if TYPE_CHECKING:
    from datetime import date

    from django.db.models import QuerySet
    from django.http import HttpRequest, HttpResponse

    from django_program.pretalx.models import Talk


class ActivityListView(ConferenceMixin, FeatureRequiredMixin, ListView):
    """List view of all active activities for a conference."""

    required_feature = ("programs", "public_ui")
    template_name = "django_program/programs/activity_list.html"
    context_object_name = "activities"

    def get_queryset(self) -> QuerySet[Activity]:
        """Return active activities for the current conference.

        Supports an optional ``?type=`` query parameter to filter by
        activity type.  Annotates ``signup_count`` (confirmed only),
        ``waitlist_count``, and ``talk_count`` to avoid N+1 queries.

        Returns:
            A queryset of active Activity instances ordered by time and name.
        """
        qs = (
            Activity.objects.filter(conference=self.conference, is_active=True)
            .select_related("room")
            .annotate(
                signup_count=Count(
                    "signups", filter=models.Q(signups__status=ActivitySignup.SignupStatus.CONFIRMED), distinct=True
                ),
                waitlist_count=Count(
                    "signups", filter=models.Q(signups__status=ActivitySignup.SignupStatus.WAITLISTED), distinct=True
                ),
                talk_count=Count("talks", distinct=True),
            )
            .order_by("start_time", "name")
        )
        activity_type = self.request.GET.get("type", "")
        if activity_type:
            qs = qs.filter(activity_type=activity_type)
        return qs

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add activity type choices and current filter to context.

        Returns:
            Context dict with ``activity_types`` and ``current_type``.
        """
        context = super().get_context_data(**kwargs)
        context["activity_types"] = Activity.ActivityType.choices
        context["current_type"] = self.request.GET.get("type", "")
        return context


class ActivityDetailView(ConferenceMixin, FeatureRequiredMixin, DetailView):
    """Detail view for a single activity with linked talks."""

    required_feature = ("programs", "public_ui")
    template_name = "django_program/programs/activity_detail.html"
    context_object_name = "activity"

    def get_object(self, queryset: QuerySet[Activity] | None = None) -> Activity:  # noqa: ARG002
        """Look up the activity by conference and slug.

        Returns:
            The matched Activity instance.

        Raises:
            Http404: If no active activity matches the conference and slug.
        """
        return get_object_or_404(
            Activity.objects.select_related("room"),
            conference=self.conference,
            slug=self.kwargs["slug"],
            is_active=True,
        )

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add signups, linked talks, speakers, and schedule to context.

        Returns:
            Context dict with ``signups``, ``spots_remaining``,
            ``user_signup``, ``waitlist_count``, ``linked_talks``,
            ``speakers``, and ``schedule_by_day``.
        """
        context = super().get_context_data(**kwargs)
        activity: Activity = self.object

        context["signups"] = activity.signups.filter(status=ActivitySignup.SignupStatus.CONFIRMED).select_related(
            "user"
        )
        context["spots_remaining"] = activity.spots_remaining
        context["waitlist_count"] = activity.signups.filter(status=ActivitySignup.SignupStatus.WAITLISTED).count()

        user_signup = None
        if self.request.user.is_authenticated:
            user_signup = (
                activity.signups.filter(user=self.request.user)
                .exclude(status=ActivitySignup.SignupStatus.CANCELLED)
                .first()
            )
        context["user_signup"] = user_signup

        linked_talks = (
            activity.talks.select_related("room")
            .prefetch_related(
                Prefetch("speakers"),
            )
            .order_by("slot_start", "title")
        )
        context["linked_talks"] = linked_talks

        speakers_seen: dict[int, object] = {}
        for talk in linked_talks:
            for speaker in talk.speakers.all():
                speakers_seen.setdefault(speaker.pk, speaker)
        context["speakers"] = list(speakers_seen.values())

        schedule_by_day: list[tuple[date, list[Talk]]] = [
            (day, list(talks))
            for day, talks in itertools.groupby(
                (t for t in linked_talks if t.slot_start),
                key=lambda t: t.slot_start.date(),
            )
        ]
        context["schedule_by_day"] = schedule_by_day

        return context


class ActivitySignupView(LoginRequiredMixin, ConferenceMixin, FeatureRequiredMixin, View):
    """POST-only view for signing up to an activity."""

    required_feature = ("programs", "public_ui")

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Handle the signup form submission.

        Uses ``select_for_update`` inside a transaction to prevent race
        conditions when checking capacity.  When the activity is at
        capacity the signup is created with ``WAITLISTED`` status.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments (unused).

        Returns:
            A redirect to the activity detail page.
        """
        with transaction.atomic():
            activity = get_object_or_404(
                Activity.objects.select_for_update(),
                conference=self.conference,
                slug=self.kwargs["slug"],
                is_active=True,
            )
            existing = (
                ActivitySignup.objects.filter(activity=activity, user=request.user)
                .exclude(status=ActivitySignup.SignupStatus.CANCELLED)
                .first()
            )
            if existing:
                messages.info(request, "You are already signed up for this activity.")
                return redirect(reverse("programs:activity-detail", args=[self.conference.slug, activity.slug]))

            at_capacity = activity.spots_remaining is not None and activity.spots_remaining <= 0
            status = ActivitySignup.SignupStatus.WAITLISTED if at_capacity else ActivitySignup.SignupStatus.CONFIRMED
            ActivitySignup.objects.create(
                activity=activity,
                user=request.user,
                status=status,
                note=request.POST.get("note", ""),
            )

        detail_url = reverse("programs:activity-detail", args=[self.conference.slug, activity.slug])
        if status == ActivitySignup.SignupStatus.WAITLISTED:
            messages.success(
                request, f"This activity is full. You have been added to the waitlist for {activity.name}."
            )
        else:
            messages.success(request, f"You have signed up for {activity.name}.")
        return redirect(detail_url)


class ActivityCancelSignupView(LoginRequiredMixin, ConferenceMixin, FeatureRequiredMixin, View):
    """POST-only view for cancelling an activity signup."""

    required_feature = ("programs", "public_ui")

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Cancel the user's signup and promote the next waitlisted person if applicable."""
        with transaction.atomic():
            activity = get_object_or_404(
                Activity.objects.select_for_update(),
                conference=self.conference,
                slug=self.kwargs["slug"],
                is_active=True,
            )
            signup = (
                ActivitySignup.objects.filter(activity=activity, user=request.user)
                .exclude(status=ActivitySignup.SignupStatus.CANCELLED)
                .first()
            )
            if signup is None:
                messages.error(request, "You do not have an active signup for this activity.")
                return redirect(reverse("programs:activity-detail", args=[self.conference.slug, activity.slug]))

            was_confirmed = signup.is_confirmed
            signup.status = ActivitySignup.SignupStatus.CANCELLED
            signup.cancelled_at = timezone.now()
            signup.save(update_fields=["status", "cancelled_at"])

            if was_confirmed:
                activity.promote_next_waitlisted()

        messages.success(request, f"Your signup for {activity.name} has been cancelled.")
        return redirect(reverse("programs:activity-detail", args=[self.conference.slug, activity.slug]))


class TravelGrantApplyView(LoginRequiredMixin, ConferenceMixin, FeatureRequiredMixin, View):
    """View for applying for a travel grant.

    Uses ``TravelGrantApplicationForm`` for server-side validation of
    the requested amount, travel origin, and reason fields.
    """

    required_feature = ("travel_grants", "public_ui")
    template_name = "django_program/programs/travel_grant_form.html"

    def get(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Render the travel grant application form.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments (unused).

        Returns:
            The rendered form page.
        """
        form = TravelGrantApplicationForm(conference=self.conference)
        return render(request, self.template_name, {"conference": self.conference, "form": form})

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Handle the travel grant application submission.

        Args:
            request: The incoming HTTP request.
            **kwargs: URL keyword arguments (unused).

        Returns:
            A redirect to the grant status page on success, or the form
            with errors on validation failure.
        """
        form = TravelGrantApplicationForm(request.POST, conference=self.conference)
        if not form.is_valid():
            return render(request, self.template_name, {"conference": self.conference, "form": form})

        grant = form.save(commit=False)
        grant.conference = self.conference
        grant.user = request.user
        try:
            with transaction.atomic():
                grant.save()
        except IntegrityError:
            messages.error(request, "You have already applied for a travel grant for this conference.")
            return redirect(reverse("programs:travel-grant-status", args=[self.conference.slug]))
        messages.success(request, "Your travel grant application has been submitted.")
        return redirect(reverse("programs:travel-grant-status", args=[self.conference.slug]))


class TravelGrantStatusView(LoginRequiredMixin, ConferenceMixin, FeatureRequiredMixin, View):
    """View for checking travel grant application status.

    Shows current grant status, action buttons based on state,
    visible messages from reviewers, and a message form.
    """

    required_feature = ("travel_grants", "public_ui")
    template_name = "django_program/programs/travel_grant_status.html"

    def get(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Render the travel grant status page."""
        grant = (
            TravelGrant.objects.filter(conference=self.conference, user=request.user)
            .select_related("reviewed_by")
            .first()
        )
        grant_messages = []
        message_form = None
        if grant:
            grant_messages = TravelGrantMessage.objects.filter(grant=grant, visible=True).order_by("created_at")
            message_form = TravelGrantMessageForm()
        return render(
            request,
            self.template_name,
            {
                "conference": self.conference,
                "grant": grant,
                "grant_messages": grant_messages,
                "message_form": message_form,
            },
        )


def _get_user_grant(request: HttpRequest, conference: object) -> TravelGrant:
    """Fetch the current user's grant for the conference or raise 404."""
    grant = TravelGrant.objects.filter(conference=conference, user=request.user).first()
    if grant is None:
        raise Http404
    return grant


class TravelGrantAcceptView(LoginRequiredMixin, ConferenceMixin, FeatureRequiredMixin, View):
    """POST-only view to accept an offered travel grant."""

    required_feature = ("travel_grants", "public_ui")

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Accept the offered grant."""
        grant = _get_user_grant(request, self.conference)
        if not grant.show_accept_button:
            messages.error(request, "This grant cannot be accepted in its current state.")
            return redirect(reverse("programs:travel-grant-status", args=[self.conference.slug]))
        grant.status = TravelGrant.GrantStatus.ACCEPTED
        grant.save(update_fields=["status", "updated_at"])
        TravelGrantMessage.objects.create(
            grant=grant,
            user=request.user,
            visible=True,
            message="Accepted the travel grant offer.",
        )
        messages.success(request, "You have accepted the travel grant offer.")
        return redirect(reverse("programs:travel-grant-status", args=[self.conference.slug]))


class TravelGrantDeclineView(LoginRequiredMixin, ConferenceMixin, FeatureRequiredMixin, View):
    """POST-only view to decline an offered travel grant."""

    required_feature = ("travel_grants", "public_ui")

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Decline the offered grant."""
        grant = _get_user_grant(request, self.conference)
        if not grant.show_decline_button:
            messages.error(request, "This grant cannot be declined in its current state.")
            return redirect(reverse("programs:travel-grant-status", args=[self.conference.slug]))
        grant.status = TravelGrant.GrantStatus.DECLINED
        grant.save(update_fields=["status", "updated_at"])
        TravelGrantMessage.objects.create(
            grant=grant,
            user=request.user,
            visible=True,
            message="Declined the travel grant offer.",
        )
        messages.success(request, "You have declined the travel grant offer.")
        return redirect(reverse("programs:travel-grant-status", args=[self.conference.slug]))


class TravelGrantWithdrawView(LoginRequiredMixin, ConferenceMixin, FeatureRequiredMixin, View):
    """POST-only view to withdraw a travel grant application."""

    required_feature = ("travel_grants", "public_ui")

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Withdraw the application."""
        grant = _get_user_grant(request, self.conference)
        if not grant.show_withdraw_button:
            messages.error(request, "This application cannot be withdrawn in its current state.")
            return redirect(reverse("programs:travel-grant-status", args=[self.conference.slug]))
        grant.status = TravelGrant.GrantStatus.WITHDRAWN
        grant.save(update_fields=["status", "updated_at"])
        TravelGrantMessage.objects.create(
            grant=grant,
            user=request.user,
            visible=True,
            message="Withdrew the travel grant application.",
        )
        messages.success(request, "Your travel grant application has been withdrawn.")
        return redirect(reverse("programs:travel-grant-status", args=[self.conference.slug]))


class TravelGrantEditView(LoginRequiredMixin, ConferenceMixin, FeatureRequiredMixin, View):
    """View for editing an existing travel grant application."""

    required_feature = ("travel_grants", "public_ui")
    template_name = "django_program/programs/travel_grant_form.html"

    def get(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Render the edit form pre-filled with existing data."""
        grant = _get_user_grant(request, self.conference)
        if not grant.show_edit_button:
            messages.error(request, "This application cannot be edited in its current state.")
            return redirect(reverse("programs:travel-grant-status", args=[self.conference.slug]))
        form = TravelGrantApplicationForm(instance=grant, conference=self.conference)
        return render(request, self.template_name, {"conference": self.conference, "form": form, "is_edit": True})

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Handle the edit form submission."""
        grant = _get_user_grant(request, self.conference)
        if not grant.show_edit_button:
            messages.error(request, "This application cannot be edited in its current state.")
            return redirect(reverse("programs:travel-grant-status", args=[self.conference.slug]))
        form = TravelGrantApplicationForm(request.POST, instance=grant, conference=self.conference)
        if not form.is_valid():
            return render(request, self.template_name, {"conference": self.conference, "form": form, "is_edit": True})
        form.save()
        messages.success(request, "Your travel grant application has been updated.")
        return redirect(reverse("programs:travel-grant-status", args=[self.conference.slug]))


class TravelGrantProvideInfoView(LoginRequiredMixin, ConferenceMixin, FeatureRequiredMixin, View):
    """View for applicants to provide information requested by reviewers."""

    required_feature = ("travel_grants", "public_ui")
    template_name = "django_program/programs/travel_grant_provide_info.html"

    def get(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Render the provide-info form."""
        grant = _get_user_grant(request, self.conference)
        if not grant.show_provide_info_button:
            messages.error(request, "No information has been requested for this application.")
            return redirect(reverse("programs:travel-grant-status", args=[self.conference.slug]))
        form = TravelGrantMessageForm()
        return render(request, self.template_name, {"conference": self.conference, "grant": grant, "form": form})

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Handle info submission — sends message and resets status to submitted."""
        grant = _get_user_grant(request, self.conference)
        if not grant.show_provide_info_button:
            messages.error(request, "No information has been requested for this application.")
            return redirect(reverse("programs:travel-grant-status", args=[self.conference.slug]))
        form = TravelGrantMessageForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"conference": self.conference, "grant": grant, "form": form})
        msg = form.save(commit=False)
        msg.grant = grant
        msg.user = request.user
        msg.visible = True
        msg.save()
        grant.status = TravelGrant.GrantStatus.SUBMITTED
        grant.save(update_fields=["status", "updated_at"])
        messages.success(request, "Your information has been submitted. Your application is back under review.")
        return redirect(reverse("programs:travel-grant-status", args=[self.conference.slug]))


class TravelGrantMessageView(LoginRequiredMixin, ConferenceMixin, FeatureRequiredMixin, View):
    """POST-only view for sending a message on an existing grant."""

    required_feature = ("travel_grants", "public_ui")

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Create a visible message from the applicant."""
        grant = _get_user_grant(request, self.conference)
        form = TravelGrantMessageForm(request.POST)
        if form.is_valid():
            msg = form.save(commit=False)
            msg.grant = grant
            msg.user = request.user
            msg.visible = True
            msg.save()
            messages.success(request, "Your message has been sent.")
        return redirect(reverse("programs:travel-grant-status", args=[self.conference.slug]))


class ReceiptUploadView(LoginRequiredMixin, ConferenceMixin, FeatureRequiredMixin, View):
    """View for uploading and listing expense receipts."""

    required_feature = ("travel_grants", "public_ui")
    template_name = "django_program/programs/travel_grant_receipts.html"

    def get(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Render the receipt upload form and existing receipts."""
        grant = _get_user_grant(request, self.conference)
        if grant.status != TravelGrant.GrantStatus.ACCEPTED or not grant.approved_amount:
            messages.error(request, "Receipts can only be uploaded for accepted grants with an approved amount.")
            return redirect(reverse("programs:travel-grant-status", args=[self.conference.slug]))
        form = ReceiptForm()
        receipts = grant.receipts.all()
        receipt_total = receipts.aggregate(total=Sum("amount"))["total"] or 0
        return render(
            request,
            self.template_name,
            {
                "conference": self.conference,
                "grant": grant,
                "form": form,
                "receipts": receipts,
                "receipt_total": receipt_total,
            },
        )

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Handle receipt file upload."""
        grant = _get_user_grant(request, self.conference)
        if grant.status != TravelGrant.GrantStatus.ACCEPTED or not grant.approved_amount:
            messages.error(request, "Receipts can only be uploaded for accepted grants with an approved amount.")
            return redirect(reverse("programs:travel-grant-status", args=[self.conference.slug]))
        form = ReceiptForm(request.POST, request.FILES)
        if form.is_valid():
            receipt = form.save(commit=False)
            receipt.grant = grant
            receipt.save()
            messages.success(request, "Receipt uploaded successfully.")
            return redirect(reverse("programs:travel-grant-receipts", args=[self.conference.slug]))
        receipts = grant.receipts.all()
        return render(
            request,
            self.template_name,
            {
                "conference": self.conference,
                "grant": grant,
                "form": form,
                "receipts": receipts,
            },
        )


class ReceiptDeleteView(LoginRequiredMixin, ConferenceMixin, FeatureRequiredMixin, View):
    """POST-only view for deleting a receipt."""

    required_feature = ("travel_grants", "public_ui")

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:
        """Delete the receipt if it has not been approved or flagged."""
        grant = _get_user_grant(request, self.conference)
        receipt = get_object_or_404(Receipt, pk=kwargs["pk"], grant=grant)
        if not receipt.can_delete:
            messages.error(request, "This receipt cannot be deleted.")
        else:
            receipt.receipt_file.delete(save=False)
            receipt.delete()
            messages.success(request, "Receipt deleted.")
        return redirect(reverse("programs:travel-grant-receipts", args=[self.conference.slug]))


class PaymentInfoView(LoginRequiredMixin, ConferenceMixin, FeatureRequiredMixin, View):
    """View for submitting or editing payment information."""

    required_feature = ("travel_grants", "public_ui")
    template_name = "django_program/programs/travel_grant_payment_info.html"

    def get(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Render the payment info form."""
        grant = _get_user_grant(request, self.conference)
        if grant.status != TravelGrant.GrantStatus.ACCEPTED or not grant.approved_amount:
            messages.error(request, "Payment info can only be submitted for accepted grants with an approved amount.")
            return redirect(reverse("programs:travel-grant-status", args=[self.conference.slug]))
        try:
            payment_info = grant.payment_info
            form = PaymentInfoForm(instance=payment_info)
        except PaymentInfo.DoesNotExist:
            form = PaymentInfoForm()
        return render(
            request,
            self.template_name,
            {
                "conference": self.conference,
                "grant": grant,
                "form": form,
            },
        )

    def post(self, request: HttpRequest, **kwargs: str) -> HttpResponse:  # noqa: ARG002
        """Handle payment info form submission."""
        grant = _get_user_grant(request, self.conference)
        if grant.status != TravelGrant.GrantStatus.ACCEPTED or not grant.approved_amount:
            messages.error(request, "Payment info can only be submitted for accepted grants with an approved amount.")
            return redirect(reverse("programs:travel-grant-status", args=[self.conference.slug]))
        try:
            payment_info = grant.payment_info
            form = PaymentInfoForm(request.POST, instance=payment_info)
        except PaymentInfo.DoesNotExist:
            form = PaymentInfoForm(request.POST)
        if form.is_valid():
            info = form.save(commit=False)
            info.grant = grant
            info.save()
            messages.success(request, "Payment information saved.")
            return redirect(reverse("programs:travel-grant-status", args=[self.conference.slug]))
        return render(
            request,
            self.template_name,
            {
                "conference": self.conference,
                "grant": grant,
                "form": form,
            },
        )
