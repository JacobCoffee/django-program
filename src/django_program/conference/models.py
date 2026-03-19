"""Conference and Section models for django-program."""

from django.conf import settings
from django.db import models
from encrypted_fields import EncryptedCharField


class Conference(models.Model):
    """A conference event with dates, venue, and integration settings.

    The central model that all other apps reference. Stores Pretalx and Stripe
    configuration so each conference can be managed independently.
    """

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    start_date = models.DateField()
    end_date = models.DateField()
    timezone = models.CharField(max_length=100, default="UTC")
    venue = models.CharField(max_length=300, blank=True, default="")
    address = models.CharField(max_length=500, blank=True, default="")
    website_url = models.URLField(blank=True, default="")

    pretalx_event_slug = models.CharField(max_length=200, blank=True, default="")

    stripe_secret_key = EncryptedCharField(max_length=200, blank=True, null=True, default=None)
    stripe_publishable_key = EncryptedCharField(max_length=200, blank=True, null=True, default=None)
    stripe_webhook_secret = EncryptedCharField(max_length=200, blank=True, null=True, default=None)

    qbo_realm_id = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="QuickBooks Online Company/Realm ID.",
    )
    qbo_access_token = EncryptedCharField(
        max_length=2000,
        blank=True,
        null=True,
        default=None,
        help_text="QBO OAuth2 access token.",
    )
    qbo_refresh_token = EncryptedCharField(
        max_length=2000,
        blank=True,
        null=True,
        default=None,
        help_text="QBO OAuth2 refresh token.",
    )
    qbo_token_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the QBO access token expires.",
    )
    qbo_client_id = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="QBO OAuth2 client ID for token refresh.",
    )
    qbo_client_secret = EncryptedCharField(
        max_length=500,
        blank=True,
        null=True,
        default=None,
        help_text="QBO OAuth2 client secret for token refresh.",
    )

    total_capacity = models.PositiveIntegerField(
        default=0,
        help_text="Maximum total tickets across all types. 0 means unlimited.",
    )

    revenue_budget = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Target revenue budget for this conference.",
    )
    target_attendance = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Target number of attendees.",
    )
    grant_budget = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Budget allocated for travel grants.",
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date"]
        permissions = [
            ("view_dashboard", "Can view conference dashboard"),
            ("manage_conference_settings", "Can edit conference settings and sync"),
            ("view_program", "Can view program content"),
            ("change_program", "Can edit program content"),
            ("view_registration", "Can view attendees and orders"),
            ("change_registration", "Can manage orders and visa letters"),
            ("view_commerce", "Can view ticket types, add-ons, vouchers"),
            ("change_commerce", "Can manage ticket types, add-ons, vouchers"),
            ("view_badges", "Can view badges and templates"),
            ("change_badges", "Can manage badges and templates"),
            ("view_sponsors", "Can view sponsors"),
            ("change_sponsors", "Can manage sponsors"),
            ("view_bulk_purchases", "Can view bulk purchases"),
            ("change_bulk_purchases", "Can manage bulk purchases"),
            ("view_finance", "Can view financial dashboard and expenses"),
            ("change_finance", "Can manage expenses"),
            ("view_reports", "Can view reports and analytics"),
            ("export_reports", "Can export report data"),
            ("view_checkin", "Can access check-in"),
            ("use_terminal", "Can use Terminal POS"),
            ("view_overrides", "Can view Pretalx overrides"),
            ("change_overrides", "Can manage Pretalx overrides"),
        ]

    def __str__(self) -> str:
        return self.name


class Section(models.Model):
    """A distinct segment of a conference (e.g. Tutorials, Talks, Sprints).

    Sections divide a conference into logical time blocks, each with their own
    date range. They are ordered by the ``order`` field for display purposes.
    """

    conference = models.ForeignKey(
        Conference,
        on_delete=models.CASCADE,
        related_name="sections",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    start_date = models.DateField()
    end_date = models.DateField()
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "start_date"]
        unique_together = [("conference", "slug")]

    def __str__(self) -> str:
        return f"{self.name} ({self.conference.slug})"


class FeatureFlags(models.Model):
    """Per-conference feature toggle overrides.

    Database-backed flags that override the defaults from
    ``DJANGO_PROGRAM["features"]``. Changes take effect immediately
    without server restart. Each conference has at most one row.

    All boolean fields are nullable: ``None`` means "use default from
    settings", while an explicit ``True`` or ``False`` overrides.
    """

    conference = models.OneToOneField(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="feature_flags",
    )
    registration_enabled = models.BooleanField(
        null=True,
        blank=True,
        help_text="Override registration toggle. Leave blank to use default from settings.",
    )
    sponsors_enabled = models.BooleanField(
        null=True,
        blank=True,
        help_text="Override sponsors toggle.",
    )
    travel_grants_enabled = models.BooleanField(
        null=True,
        blank=True,
        help_text="Override travel grants toggle.",
    )
    programs_enabled = models.BooleanField(
        null=True,
        blank=True,
        help_text="Override programs/activities toggle.",
    )
    pretalx_sync_enabled = models.BooleanField(
        null=True,
        blank=True,
        help_text="Override Pretalx sync toggle.",
    )
    visa_letters_enabled = models.BooleanField(
        null=True,
        blank=True,
        help_text="Override visa invitation letters toggle.",
    )
    public_ui_enabled = models.BooleanField(
        null=True,
        blank=True,
        help_text="Override public UI toggle.",
    )
    manage_ui_enabled = models.BooleanField(
        null=True,
        blank=True,
        help_text="Override manage UI toggle.",
    )
    all_ui_enabled = models.BooleanField(
        null=True,
        blank=True,
        help_text="Master UI switch override.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "feature flags"
        verbose_name_plural = "feature flags"

    def __str__(self) -> str:
        return f"Feature flags for {self.conference}"


class ExpenseCategory(models.Model):
    """A category for conference expenses (e.g. Venue, F&B, A/V, Travel, Marketing)."""

    conference = models.ForeignKey(
        Conference,
        on_delete=models.CASCADE,
        related_name="expense_categories",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    description = models.TextField(blank=True, default="")
    budget_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Budgeted amount for this expense category.",
    )
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "name"]
        unique_together = [("conference", "slug")]
        verbose_name_plural = "expense categories"

    def __str__(self) -> str:
        return f"{self.name} ({self.conference.slug})"


class Expense(models.Model):
    """An individual expense record for a conference."""

    conference = models.ForeignKey(
        Conference,
        on_delete=models.CASCADE,
        related_name="expenses",
    )
    category = models.ForeignKey(
        ExpenseCategory,
        on_delete=models.CASCADE,
        related_name="expenses",
    )
    description = models.CharField(max_length=500)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    vendor = models.CharField(max_length=300, blank=True, default="")
    date = models.DateField()
    receipt_reference = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Invoice or receipt reference number.",
    )
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self) -> str:
        return f"{self.description} (${self.amount})"


class KPITargets(models.Model):
    """Per-conference configurable KPI thresholds for the analytics dashboard.

    When a field is null, the dashboard falls back to hardcoded industry
    averages. Setting a value overrides the default target for that metric.
    """

    conference = models.OneToOneField(
        Conference,
        on_delete=models.CASCADE,
        related_name="kpi_targets",
    )
    target_conversion_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Target cart-to-order conversion rate (%). Industry avg ~3%.",
    )
    target_refund_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Maximum acceptable refund rate (%). Typical target: 5%.",
    )
    target_checkin_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Target check-in rate (%). Strong turnout >= 80%.",
    )
    target_fulfillment_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Target sponsor benefit fulfillment rate (%). Goal: 90%+.",
    )
    target_revenue_per_attendee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Target revenue per attendee ($).",
    )
    target_room_utilization = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Target room utilization rate (%). Industry avg ~28%.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "KPI targets"
        verbose_name_plural = "KPI targets"

    def __str__(self) -> str:
        return f"KPI targets for {self.conference}"
