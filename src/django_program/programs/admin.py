"""Django admin configuration for the programs app."""

from django.contrib import admin

from django_program.programs.models import (
    Activity,
    ActivitySignup,
    PaymentInfo,
    Receipt,
    TravelGrant,
    TravelGrantMessage,
)


class ActivitySignupInline(admin.TabularInline):
    """Inline editor for activity signups within the activity admin."""

    model = ActivitySignup
    extra = 0
    fields = ("user", "status", "note", "cancelled_at", "created_at")
    readonly_fields = ("cancelled_at", "created_at")


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    """Admin interface for managing activities."""

    list_display = (
        "name",
        "conference",
        "activity_type",
        "start_time",
        "max_participants",
        "is_active",
        "pretalx_submission_type",
    )
    list_filter = ("conference", "activity_type", "is_active")
    search_fields = ("name", "slug", "pretalx_submission_type")
    prepopulated_fields = {"slug": ("name",)}
    inlines = (ActivitySignupInline,)


@admin.register(ActivitySignup)
class ActivitySignupAdmin(admin.ModelAdmin):
    """Admin interface for managing activity signups."""

    list_display = ("user", "activity", "status", "cancelled_at", "created_at")
    list_filter = ("status", "activity__conference")
    search_fields = ("user__username", "user__email", "activity__name")
    readonly_fields = ("cancelled_at", "created_at")


class TravelGrantMessageInline(admin.TabularInline):
    """Inline editor for grant messages within the grant admin."""

    model = TravelGrantMessage
    extra = 0
    fields = ("user", "visible", "message", "created_at")
    readonly_fields = ("created_at",)


class ReceiptInline(admin.TabularInline):
    """Inline editor for receipts within the travel grant admin."""

    model = Receipt
    extra = 0
    fields = ("receipt_type", "amount", "date", "approved", "flagged", "created_at")
    readonly_fields = ("created_at",)


@admin.register(TravelGrant)
class TravelGrantAdmin(admin.ModelAdmin):
    """Admin interface for managing travel grant applications."""

    list_display = (
        "user",
        "conference",
        "status",
        "application_type",
        "request_type",
        "requested_amount",
        "approved_amount",
        "disbursed_amount",
        "travel_from",
        "international",
    )
    list_filter = ("conference", "status", "application_type", "request_type", "international")
    search_fields = ("user__username", "user__email", "travel_from")
    list_editable = ("status",)
    readonly_fields = ("created_at", "updated_at", "disbursed_at", "disbursed_by")
    inlines = (TravelGrantMessageInline, ReceiptInline)


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    """Admin interface for managing travel grant receipts."""

    list_display = ("grant", "receipt_type", "amount", "date", "approved", "flagged", "created_at")
    list_filter = ("receipt_type", "approved", "flagged")
    search_fields = ("grant__user__username", "grant__user__email", "description")
    readonly_fields = ("created_at",)


@admin.register(PaymentInfo)
class PaymentInfoAdmin(admin.ModelAdmin):
    """Admin interface for managing travel grant payment info."""

    list_display = ("grant", "payment_method", "legal_name", "address_country", "created_at")
    list_filter = ("payment_method",)
    search_fields = ("grant__user__username", "grant__user__email", "legal_name")
    readonly_fields = ("created_at", "updated_at")
