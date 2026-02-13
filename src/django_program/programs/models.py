"""Activity, signup, and travel grant models for django-program."""

from decimal import Decimal

from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models, transaction
from encrypted_fields import EncryptedCharField, EncryptedTextField


class Activity(models.Model):
    """A conference activity such as a sprint, workshop, or social event.

    Represents a scheduled or unscheduled activity that attendees can
    sign up for.  The ``max_participants`` field caps signups when set,
    and ``spots_remaining`` computes the live availability.

    Activities can be linked to Pretalx submission types via the
    ``pretalx_submission_type`` field.  When set, the ``talks`` M2M
    is populated during sync with all talks of that submission type.
    """

    class ActivityType(models.TextChoices):
        """Classification of conference activities."""

        SPRINT = "sprint", "Sprint"
        WORKSHOP = "workshop", "Workshop"
        TUTORIAL = "tutorial", "Tutorial"
        LIGHTNING_TALK = "lightning_talk", "Lightning Talk"
        SOCIAL = "social", "Social Event"
        OPEN_SPACE = "open_space", "Open Space"
        SUMMIT = "summit", "Summit"
        OTHER = "other", "Other"

    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="activities",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    activity_type = models.CharField(
        max_length=20,
        choices=ActivityType.choices,
        default=ActivityType.OTHER,
    )
    description = models.TextField(blank=True, default="")
    location = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Manual location for off-venue or non-Pretalx activities.",
    )
    room = models.ForeignKey(
        "program_pretalx.Room",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities",
        help_text="Pretalx room assignment.",
    )
    pretalx_submission_type = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Pretalx submission type name to link talks (e.g. 'Tutorial', 'Workshop').",
    )
    talks = models.ManyToManyField(
        "program_pretalx.Talk",
        related_name="activities",
        blank=True,
        help_text="Talks linked via submission type match during Pretalx sync.",
    )
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    max_participants = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Leave blank for unlimited.",
    )
    requires_ticket = models.BooleanField(
        default=False,
        help_text="Whether a conference ticket is required to sign up.",
    )
    external_url = models.URLField(
        blank=True,
        default="",
        help_text="External link for more details.",
    )
    is_active = models.BooleanField(default=True)
    synced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this activity was last synced from Pretalx.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_time", "name"]
        unique_together = [("conference", "slug")]

    def __str__(self) -> str:
        return str(self.name)

    @property
    def spots_remaining(self) -> int | None:
        """Return the number of remaining confirmed spots, or None if unlimited."""
        if self.max_participants is None:
            return None
        confirmed = self.signups.filter(status=ActivitySignup.SignupStatus.CONFIRMED).count()
        return max(0, self.max_participants - confirmed)

    def promote_next_waitlisted(self) -> ActivitySignup | None:
        """Promote the oldest waitlisted signup to confirmed.

        Must be called inside a transaction. Returns the promoted signup
        or None if no one is waitlisted.
        """
        with transaction.atomic():
            next_signup = (
                self.signups.select_for_update()
                .filter(status=ActivitySignup.SignupStatus.WAITLISTED)
                .order_by("created_at")
                .first()
            )
            if next_signup is not None:
                next_signup.status = ActivitySignup.SignupStatus.CONFIRMED
                next_signup.save(update_fields=["status"])
            return next_signup


class ActivitySignup(models.Model):
    """A user's signup for an activity.

    Each user may have at most one non-cancelled signup per activity,
    enforced by a conditional ``UniqueConstraint``.  The status field
    tracks whether the signup is confirmed, waitlisted, or cancelled.
    """

    class SignupStatus(models.TextChoices):
        """Lifecycle states for an activity signup."""

        CONFIRMED = "confirmed", "Confirmed"
        WAITLISTED = "waitlisted", "Waitlisted"
        CANCELLED = "cancelled", "Cancelled"

    activity = models.ForeignKey(
        Activity,
        on_delete=models.CASCADE,
        related_name="signups",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="activity_signups",
    )
    status = models.CharField(
        max_length=20,
        choices=SignupStatus.choices,
        default=SignupStatus.CONFIRMED,
    )
    note = models.TextField(
        blank=True,
        default="",
        help_text="Optional note from the attendee.",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["activity", "user"],
                condition=~models.Q(status="cancelled"),
                name="unique_active_signup_per_user",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} - {self.activity.name}"

    @property
    def is_confirmed(self) -> bool:
        """Whether this signup is confirmed."""
        return self.status == self.SignupStatus.CONFIRMED

    @property
    def is_waitlisted(self) -> bool:
        """Whether this signup is on the waitlist."""
        return self.status == self.SignupStatus.WAITLISTED

    @property
    def is_cancelled(self) -> bool:
        """Whether this signup has been cancelled."""
        return self.status == self.SignupStatus.CANCELLED

    @property
    def can_cancel(self) -> bool:
        """Whether this signup can be cancelled (confirmed or waitlisted)."""
        return self.status in (self.SignupStatus.CONFIRMED, self.SignupStatus.WAITLISTED)


# ---------------------------------------------------------------------------
# Travel Grants
# ---------------------------------------------------------------------------


class TravelGrant(models.Model):
    """A travel grant application for a conference.

    Modeled after PyCon US's travel grant system.  Tracks the full
    application lifecycle from submission through review, offer, and
    acceptance.  Sensitive reimbursement details (bank info) are NOT
    stored here — they belong in a separate secure model collected
    only after acceptance.
    """

    class GrantStatus(models.TextChoices):
        """Lifecycle states for a travel grant application."""

        SUBMITTED = "submitted", "Submitted"
        WITHDRAWN = "withdrawn", "Withdrawn"
        INFO_NEEDED = "info_needed", "Information Needed"
        OFFERED = "offered", "Offered"
        NEED_MORE = "need_more", "Requesting More Funds"
        REJECTED = "rejected", "Rejected"
        DECLINED = "declined", "Declined"
        ACCEPTED = "accepted", "Accepted"
        DISBURSED = "disbursed", "Disbursed"

    class RequestType(models.TextChoices):
        """What the applicant is requesting."""

        TICKET_ONLY = "ticket_only", "In-Person Ticket Only"
        TICKET_AND_GRANT = "ticket_and_grant", "In-Person Ticket and Travel Grant"

    class ExperienceLevel(models.TextChoices):
        """Python experience level of the applicant."""

        BEGINNER = "beginner", "Beginner"
        INTERMEDIATE = "intermediate", "Intermediate"
        EXPERT = "expert", "Expert"

    class ApplicationType(models.TextChoices):
        """Classification of the grant application."""

        GENERAL = "general", "General Applicant"
        STAFF = "staff", "Conference Staff/Volunteer"
        SPEAKER = "speaker", "Speaker"
        CORE_DEV = "core_dev", "Core Developer"
        PSF_BOARD = "psf_board", "PSF Board Member"
        COMMUNITY = "community", "Outstanding Community Member"
        EDUCATION = "education", "Education"
        PYLADIES = "pyladies", "PyLadies"
        OTHER = "other", "Other"

    # ---- Core fields ----
    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="travel_grants",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="travel_grants",
    )
    status = models.CharField(
        max_length=20,
        choices=GrantStatus.choices,
        default=GrantStatus.SUBMITTED,
    )
    application_type = models.CharField(
        max_length=20,
        choices=ApplicationType.choices,
        default=ApplicationType.GENERAL,
        help_text="Application classification.",
    )
    request_type = models.CharField(
        max_length=20,
        choices=RequestType.choices,
        default=RequestType.TICKET_AND_GRANT,
        help_text="What kind of request you are submitting.",
    )

    # ---- Travel details ----
    travel_from = models.CharField(
        max_length=200,
        help_text="City or region the applicant is traveling from.",
    )
    international = models.BooleanField(
        default=False,
        help_text="Whether the applicant is traveling internationally.",
    )
    first_time = models.BooleanField(
        null=True,
        blank=True,
        help_text="Is this the applicant's first time attending?",
    )

    # ---- Travel plan breakdown ----
    travel_plans_airfare_description = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="Description of airfare plans.",
    )
    travel_plans_airfare_amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
        blank=True,
        help_text="Estimated airfare cost in USD.",
    )
    travel_plans_lodging_description = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="Description of lodging plans.",
    )
    travel_plans_lodging_amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
        blank=True,
        help_text="Estimated lodging cost in USD.",
    )
    travel_plans_transit_description = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="Description of local transit plans.",
    )
    travel_plans_transit_amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
        blank=True,
        help_text="Estimated local transit cost in USD.",
    )
    travel_plans_visa_description = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="Description of visa costs.",
    )
    travel_plans_visa_amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
        blank=True,
        help_text="Estimated visa cost in USD.",
    )

    # ---- Amounts ----
    requested_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Total amount of assistance requested in USD.",
    )
    approved_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # ---- Applicant profile ----
    experience_level = models.CharField(
        max_length=20,
        choices=ExperienceLevel.choices,
        blank=True,
        default="",
        help_text="Python experience level.",
    )
    occupation = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Current occupation or situation.",
    )
    involvement = models.TextField(
        blank=True,
        default="",
        help_text="Involvement in open source projects or community.",
    )
    reason = models.TextField(
        help_text="Why the applicant needs a travel grant.",
    )

    # ---- Conference attendance ----
    days_attending = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Which conference days the applicant plans to attend.",
    )
    sharing_expenses = models.BooleanField(
        default=False,
        help_text="Whether sharing travel expenses with another applicant.",
    )
    traveling_with = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Names of other grant applicants sharing expenses.",
    )

    # ---- Review ----
    reviewer_notes = models.TextField(blank=True, default="")
    promo_code = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Voucher/promo code for ticket.",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_grants",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    # ---- Disbursement ----
    disbursed_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Actual amount disbursed to the grantee.",
    )
    disbursed_at = models.DateTimeField(null=True, blank=True)
    disbursed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="disbursed_grants",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("conference", "user")]
        permissions = [
            ("review_travel_grant", "Can review travel grant applications"),
        ]

    def __str__(self) -> str:
        return f"Travel grant: {self.user} ({self.status})"

    @property
    def travel_plans_total(self) -> Decimal:
        """Sum of airfare and lodging breakdown amounts."""
        return self.travel_plans_airfare_amount + self.travel_plans_lodging_amount

    @property
    def is_editable(self) -> bool:
        """Whether the applicant can still edit their application."""
        return self.status in (self.GrantStatus.SUBMITTED, self.GrantStatus.INFO_NEEDED)

    @property
    def is_actionable(self) -> bool:
        """Whether the applicant can accept/decline (offered state)."""
        return self.status == self.GrantStatus.OFFERED

    @property
    def show_accept_button(self) -> bool:
        """Show accept button only when grant is offered."""
        return self.status == self.GrantStatus.OFFERED

    @property
    def show_decline_button(self) -> bool:
        """Show decline button only when grant is offered."""
        return self.status == self.GrantStatus.OFFERED

    @property
    def show_withdraw_button(self) -> bool:
        """Show withdraw button for submitted or info-needed grants."""
        return self.status in (self.GrantStatus.SUBMITTED, self.GrantStatus.INFO_NEEDED)

    @property
    def show_edit_button(self) -> bool:
        """Show edit button for submitted or info-needed grants."""
        return self.status in (self.GrantStatus.SUBMITTED, self.GrantStatus.INFO_NEEDED)

    @property
    def is_ready_for_disbursement(self) -> bool:
        """Whether grant has approved receipts and payment info, ready to disburse."""
        if self.status != self.GrantStatus.ACCEPTED:
            return False
        has_payment = hasattr(self, "payment_info")
        has_approved_receipts = self.receipts.filter(approved=True).exists()
        return has_payment and has_approved_receipts

    @property
    def show_provide_info_button(self) -> bool:
        """Show provide-info button when reviewers request more info."""
        return self.status == self.GrantStatus.INFO_NEEDED


class TravelGrantMessage(models.Model):
    """Message attached to a travel grant application.

    Reviewers can leave internal notes (visible=False) or messages
    visible to the applicant (visible=True).  Applicant messages are
    always visible to reviewers.
    """

    grant = models.ForeignKey(
        TravelGrant,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        help_text="User who submitted the message.",
    )
    visible = models.BooleanField(
        default=False,
        help_text="Whether message is visible to the applicant.",
    )
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"Grant message for {self.grant.user} by {self.user}"


def receipt_upload_path(instance: Receipt, filename: str) -> str:
    """Build per-user upload path: ``travel_grant_receipts/<username>/<filename>``."""
    return f"travel_grant_receipts/{instance.grant.user.username}/{filename}"


class Receipt(models.Model):
    """An expense receipt uploaded by a travel grant recipient."""

    class ReceiptType(models.TextChoices):
        AIRFARE = "airfare", "Airfare"
        LODGING = "lodging", "Lodging"

    grant = models.ForeignKey(TravelGrant, on_delete=models.CASCADE, related_name="receipts")
    receipt_type = models.CharField(max_length=20, choices=ReceiptType.choices)
    description = models.CharField(max_length=255, blank=True, default="")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField()
    receipt_file = models.FileField(
        upload_to=receipt_upload_path,
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "jpg", "jpeg", "png"])],
    )
    approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_receipts"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    flagged = models.BooleanField(default=False)
    flagged_reason = models.CharField(max_length=1024, blank=True, default="")
    flagged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="flagged_receipts"
    )
    flagged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [("review_receipt", "Can review travel grant receipts")]

    def __str__(self) -> str:
        return f"{self.get_receipt_type_display()} receipt - ${self.amount}"

    @property
    def status(self) -> str:
        """Return the current review status of this receipt."""
        if self.approved:
            return "approved"
        if self.flagged:
            return "flagged"
        return "pending"

    @property
    def can_delete(self) -> bool:
        """Whether this receipt can be deleted by the applicant."""
        return not self.approved and not self.flagged


class PaymentInfo(models.Model):
    """Secure payment details for travel grant reimbursement."""

    class PaymentMethod(models.TextChoices):
        ZELLE = "zelle", "Zelle"
        PAYPAL = "paypal", "PayPal"
        ACH = "ach", "ACH (Direct Deposit)"
        WIRE = "wire", "Wire Transfer"
        WISE = "wise", "Wise"
        CHECK = "check", "Check"

    grant = models.OneToOneField(TravelGrant, on_delete=models.CASCADE, related_name="payment_info")
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    legal_name = models.CharField(max_length=500)
    address_street = models.CharField(max_length=512)
    address_city = models.CharField(max_length=256)
    address_state = models.CharField(max_length=256, blank=True, default="")
    address_zip = models.CharField(max_length=64)
    address_country = models.CharField(max_length=256)

    # Method-specific encrypted fields
    paypal_email = EncryptedCharField(max_length=500, blank=True, null=True, default=None)
    zelle_email = EncryptedCharField(max_length=500, blank=True, null=True, default=None)
    wise_email = EncryptedCharField(max_length=500, blank=True, null=True, default=None)
    bank_name = EncryptedCharField(max_length=256, blank=True, null=True, default=None)
    bank_account_number = EncryptedCharField(max_length=128, blank=True, null=True, default=None)
    bank_routing_number = EncryptedCharField(max_length=128, blank=True, null=True, default=None)
    bank_holder_name = EncryptedCharField(max_length=512, blank=True, null=True, default=None)
    bank_holder_address = EncryptedTextField(blank=True, null=True, default=None)
    bank_address = EncryptedTextField(blank=True, null=True, default=None)
    bank_additional = EncryptedTextField(blank=True, null=True, default=None)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "payment info"

    def __str__(self) -> str:
        return f"Payment info for {self.grant.user} ({self.get_payment_method_display()})"
