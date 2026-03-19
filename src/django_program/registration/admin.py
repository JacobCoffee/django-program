"""Django admin configuration for the registration app."""

from django.contrib import admin
from django.http import HttpRequest  # noqa: TC002

from django_program.registration.badge import Badge, BadgeTemplate
from django_program.registration.checkin import CheckIn, DoorCheck, ProductRedemption
from django_program.registration.conditions import (
    DiscountForCategory,
    DiscountForProduct,
    GroupMemberCondition,
    IncludedProductCondition,
    SpeakerCondition,
    TimeOrStockLimitCondition,
)
from django_program.registration.models import (
    AddOn,
    Attendee,
    Cart,
    CartItem,
    Credit,
    EventProcessingException,
    Order,
    OrderLineItem,
    Payment,
    StripeCustomer,
    StripeEvent,
    TicketType,
    Voucher,
)
from django_program.registration.purchase_order import (
    PurchaseOrder,
    PurchaseOrderCreditNote,
    PurchaseOrderLineItem,
    PurchaseOrderPayment,
)
from django_program.registration.terminal import TerminalPayment


@admin.register(Attendee)
class AttendeeAdmin(admin.ModelAdmin):
    """Admin interface for viewing and managing conference attendees."""

    list_display = ("user", "conference", "access_code", "completed_registration", "checked_in_at")
    list_filter = ("conference", "completed_registration")
    search_fields = ("user__username", "user__email", "access_code")
    readonly_fields = ("access_code",)


@admin.register(TicketType)
class TicketTypeAdmin(admin.ModelAdmin):
    """Admin interface for managing ticket types.

    Provides filtering by conference and active status, search by name and
    slug, and auto-population of the slug from the ticket name.
    """

    list_display = ("name", "conference", "price", "is_active", "bulk_enabled", "order")
    list_filter = ("conference", "is_active", "bulk_enabled")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(AddOn)
class AddOnAdmin(admin.ModelAdmin):
    """Admin interface for managing add-ons.

    Uses ``filter_horizontal`` for the ``requires_ticket_types`` many-to-many
    field to provide a friendlier selection widget.
    """

    list_display = ("name", "conference", "price", "is_active", "bulk_enabled")
    list_filter = ("conference", "is_active", "bulk_enabled")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("requires_ticket_types",)


@admin.register(Voucher)
class VoucherAdmin(admin.ModelAdmin):
    """Admin interface for managing vouchers.

    Displays usage counts alongside the voucher configuration and allows
    filtering by conference, type, and active status.
    """

    list_display = (
        "code",
        "conference",
        "voucher_type",
        "discount_value",
        "times_used",
        "max_uses",
        "is_active",
    )
    list_filter = ("conference", "voucher_type", "is_active")
    search_fields = ("code",)
    filter_horizontal = ("applicable_ticket_types", "applicable_addons")


class CartItemInline(admin.TabularInline):
    """Inline display of cart items within the cart admin.

    Items are shown as read-only since they are managed through the
    storefront, not directly in the admin.
    """

    model = CartItem
    extra = 0
    readonly_fields = ("ticket_type", "addon", "quantity")


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    """Admin interface for viewing shopping carts.

    Carts are primarily managed by the storefront; the admin provides a
    read-oriented view with inline cart items.
    """

    list_display = ("user", "conference", "status", "voucher", "expires_at")
    list_filter = ("conference", "status")
    inlines = (CartItemInline,)


class OrderLineItemInline(admin.TabularInline):
    """Inline display of order line items within the order admin.

    Line items are immutable snapshots from checkout and are shown read-only.
    """

    model = OrderLineItem
    extra = 0
    readonly_fields = (
        "description",
        "quantity",
        "unit_price",
        "discount_amount",
        "line_total",
        "ticket_type",
        "addon",
    )


class PaymentInline(admin.TabularInline):
    """Inline display of payments within the order admin."""

    model = Payment
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """Admin interface for managing orders.

    Displays order reference, user, status, and financial totals. Money fields
    are read-only to prevent accidental edits; changes should flow through the
    payment and refund workflows instead.
    """

    list_display = ("reference", "user", "conference", "status", "total", "created_at")
    list_filter = ("conference", "status")
    search_fields = ("reference", "user__email", "billing_email")
    readonly_fields = ("subtotal", "discount_amount", "total")
    inlines = (OrderLineItemInline, PaymentInline)


@admin.register(Credit)
class CreditAdmin(admin.ModelAdmin):
    """Admin interface for managing store credits.

    Provides filtering by conference and credit status, and displays the
    amount and creation date at a glance.
    """

    list_display = ("user", "conference", "amount", "status", "created_at")
    list_filter = ("conference", "status")


@admin.register(StripeCustomer)
class StripeCustomerAdmin(admin.ModelAdmin):
    """Read-only admin for Stripe customer mappings."""

    list_display = ("user", "conference", "stripe_customer_id", "created_at")
    list_filter = ("conference",)
    search_fields = ("user__email", "stripe_customer_id")
    readonly_fields = ("user", "conference", "stripe_customer_id", "created_at")

    def has_add_permission(self, request: HttpRequest) -> bool:  # noqa: ARG002, D102
        return False

    def has_change_permission(self, request: HttpRequest, obj: StripeCustomer | None = None) -> bool:  # noqa: ARG002, D102
        return False

    def has_delete_permission(self, request: HttpRequest, obj: StripeCustomer | None = None) -> bool:  # noqa: ARG002, D102
        return False


@admin.register(StripeEvent)
class StripeEventAdmin(admin.ModelAdmin):
    """Read-only admin for Stripe webhook events."""

    list_display = ("stripe_id", "kind", "processed", "livemode", "created_at")
    list_filter = ("kind", "processed", "livemode")
    search_fields = ("stripe_id", "customer_id")
    readonly_fields = (
        "stripe_id",
        "kind",
        "livemode",
        "payload",
        "customer_id",
        "processed",
        "api_version",
        "created_at",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:  # noqa: ARG002, D102
        return False

    def has_change_permission(self, request: HttpRequest, obj: StripeEvent | None = None) -> bool:  # noqa: ARG002, D102
        return False

    def has_delete_permission(self, request: HttpRequest, obj: StripeEvent | None = None) -> bool:  # noqa: ARG002, D102
        return False


@admin.register(EventProcessingException)
class EventProcessingExceptionAdmin(admin.ModelAdmin):
    """Read-only admin for webhook processing errors."""

    list_display = ("message", "event", "created_at")
    list_filter = ("created_at",)
    search_fields = ("message",)
    readonly_fields = ("event", "data", "message", "traceback", "created_at")

    def has_add_permission(self, request: HttpRequest) -> bool:  # noqa: ARG002, D102
        return False

    def has_change_permission(self, request: HttpRequest, obj: EventProcessingException | None = None) -> bool:  # noqa: ARG002, D102
        return False

    def has_delete_permission(self, request: HttpRequest, obj: EventProcessingException | None = None) -> bool:  # noqa: ARG002, D102
        return False


# -- Condition / Discount admin -----------------------------------------------


@admin.register(TimeOrStockLimitCondition)
class TimeOrStockLimitConditionAdmin(admin.ModelAdmin):
    """Admin for time-window and stock-limited conditions."""

    list_display = (
        "name",
        "conference",
        "is_active",
        "priority",
        "discount_type",
        "discount_value",
        "start_time",
        "end_time",
        "times_used",
        "limit",
    )
    list_filter = ("conference", "is_active", "discount_type")
    search_fields = ("name",)
    filter_horizontal = ("applicable_ticket_types", "applicable_addons")


@admin.register(SpeakerCondition)
class SpeakerConditionAdmin(admin.ModelAdmin):
    """Admin for speaker-based discount conditions."""

    list_display = (
        "name",
        "conference",
        "is_active",
        "priority",
        "discount_type",
        "discount_value",
        "is_presenter",
        "is_copresenter",
    )
    list_filter = ("conference", "is_active", "is_presenter", "is_copresenter")
    search_fields = ("name",)
    filter_horizontal = ("applicable_ticket_types", "applicable_addons")


@admin.register(GroupMemberCondition)
class GroupMemberConditionAdmin(admin.ModelAdmin):
    """Admin for group-membership-based discount conditions."""

    list_display = ("name", "conference", "is_active", "priority", "discount_type", "discount_value")
    list_filter = ("conference", "is_active")
    search_fields = ("name",)
    filter_horizontal = ("applicable_ticket_types", "applicable_addons", "groups")


@admin.register(IncludedProductCondition)
class IncludedProductConditionAdmin(admin.ModelAdmin):
    """Admin for included-product discount conditions."""

    list_display = ("name", "conference", "is_active", "priority", "discount_type", "discount_value")
    list_filter = ("conference", "is_active")
    search_fields = ("name",)
    filter_horizontal = ("applicable_ticket_types", "applicable_addons", "enabling_ticket_types")


@admin.register(DiscountForProduct)
class DiscountForProductAdmin(admin.ModelAdmin):
    """Admin for direct product discounts."""

    list_display = (
        "name",
        "conference",
        "is_active",
        "priority",
        "discount_type",
        "discount_value",
        "start_time",
        "end_time",
        "times_used",
        "limit",
    )
    list_filter = ("conference", "is_active", "discount_type")
    search_fields = ("name",)
    filter_horizontal = ("applicable_ticket_types", "applicable_addons")


@admin.register(DiscountForCategory)
class DiscountForCategoryAdmin(admin.ModelAdmin):
    """Admin for category-wide percentage discounts."""

    list_display = (
        "name",
        "conference",
        "is_active",
        "priority",
        "percentage",
        "apply_to_tickets",
        "apply_to_addons",
        "times_used",
        "limit",
    )
    list_filter = ("conference", "is_active", "apply_to_tickets", "apply_to_addons")
    search_fields = ("name",)


# -- Check-in admin -----------------------------------------------------------


@admin.register(CheckIn)
class CheckInAdmin(admin.ModelAdmin):
    """Admin interface for viewing conference check-in records."""

    list_display = ("attendee", "conference", "station", "checked_in_by", "checked_in_at")
    list_filter = ("conference", "station")
    search_fields = ("attendee__user__username", "attendee__user__email", "attendee__access_code")
    readonly_fields = ("attendee", "conference", "checked_in_at", "checked_in_by", "station", "note")

    def has_add_permission(self, request: HttpRequest) -> bool:  # noqa: ARG002, D102
        return False

    def has_change_permission(self, request: HttpRequest, obj: CheckIn | None = None) -> bool:  # noqa: ARG002, D102
        return False

    def has_delete_permission(self, request: HttpRequest, obj: CheckIn | None = None) -> bool:  # noqa: ARG002, D102
        return False


@admin.register(DoorCheck)
class DoorCheckAdmin(admin.ModelAdmin):
    """Admin interface for viewing per-product door check records."""

    list_display = ("attendee", "conference", "ticket_type", "addon", "station", "checked_by", "checked_at")
    list_filter = ("conference", "station")
    search_fields = ("attendee__user__username", "attendee__user__email", "attendee__access_code")
    readonly_fields = (
        "attendee",
        "ticket_type",
        "addon",
        "conference",
        "checked_at",
        "checked_by",
        "station",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:  # noqa: ARG002, D102
        return False

    def has_change_permission(self, request: HttpRequest, obj: DoorCheck | None = None) -> bool:  # noqa: ARG002, D102
        return False

    def has_delete_permission(self, request: HttpRequest, obj: DoorCheck | None = None) -> bool:  # noqa: ARG002, D102
        return False


@admin.register(ProductRedemption)
class ProductRedemptionAdmin(admin.ModelAdmin):
    """Read-only admin for viewing product redemption audit records."""

    list_display = ("attendee", "order_line_item", "conference", "redeemed_by", "redeemed_at")
    list_filter = ("conference",)
    search_fields = ("attendee__user__username", "attendee__user__email", "attendee__access_code")
    readonly_fields = ("attendee", "order_line_item", "conference", "redeemed_at", "redeemed_by", "note")

    def has_add_permission(self, request: HttpRequest) -> bool:  # noqa: ARG002, D102
        return False

    def has_change_permission(self, request: HttpRequest, obj: ProductRedemption | None = None) -> bool:  # noqa: ARG002, D102
        return False

    def has_delete_permission(self, request: HttpRequest, obj: ProductRedemption | None = None) -> bool:  # noqa: ARG002, D102
        return False


# -- Badge admin --------------------------------------------------------------


@admin.register(BadgeTemplate)
class BadgeTemplateAdmin(admin.ModelAdmin):
    """Admin interface for managing badge layout templates."""

    list_display = ("name", "conference", "is_default", "width_mm", "height_mm")
    list_filter = ("conference", "is_default")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Badge)
class BadgeAdmin(admin.ModelAdmin):
    """Read-only admin for viewing generated badges."""

    list_display = ("attendee", "format", "generated_at", "created_at")
    list_filter = ("format", "generated_at")
    search_fields = ("attendee__user__username", "attendee__user__email", "attendee__access_code")
    readonly_fields = ("attendee", "template", "format", "file", "generated_at")

    def has_add_permission(self, request: HttpRequest) -> bool:  # noqa: ARG002, D102
        return False

    def has_change_permission(self, request: HttpRequest, obj: Badge | None = None) -> bool:  # noqa: ARG002, D102
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Badge | None = None) -> bool:  # noqa: ARG002, D102
        return False


# -- Terminal payment admin ---------------------------------------------------


@admin.register(TerminalPayment)
class TerminalPaymentAdmin(admin.ModelAdmin):
    """Read-only admin for Stripe Terminal payment records."""

    list_display = (
        "payment_intent_id",
        "conference",
        "capture_status",
        "card_brand",
        "card_last4",
        "reader_id",
        "created_at",
    )
    list_filter = ("conference", "capture_status", "card_brand")
    search_fields = ("payment_intent_id", "reader_id", "terminal_id", "card_last4")
    readonly_fields = (
        "payment",
        "conference",
        "terminal_id",
        "reader_id",
        "payment_intent_id",
        "capture_status",
        "captured_at",
        "cancelled_at",
        "card_brand",
        "card_last4",
        "receipt_url",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:  # noqa: ARG002, D102
        return False

    def has_change_permission(self, request: HttpRequest, obj: TerminalPayment | None = None) -> bool:  # noqa: ARG002, D102
        return False

    def has_delete_permission(self, request: HttpRequest, obj: TerminalPayment | None = None) -> bool:  # noqa: ARG002, D102
        return False


# -- Purchase Order admin -----------------------------------------------------


class PurchaseOrderLineItemInline(admin.TabularInline):
    """Inline display of purchase order line items.

    Line items are pricing snapshots and ``line_total`` is read-only to
    prevent manual edits that would desynchronize the PO totals.
    """

    model = PurchaseOrderLineItem
    extra = 0
    readonly_fields = ("line_total",)


class PurchaseOrderPaymentInline(admin.TabularInline):
    """Read-only inline display of payments recorded against a purchase order.

    Payments should be recorded through the management dashboard to ensure
    proper status transitions. The inline is read-only to prevent bypassing
    the service layer invariants.
    """

    model = PurchaseOrderPayment
    extra = 0
    readonly_fields = ("amount", "method", "reference", "payment_date", "entered_by", "note", "created_at")

    def has_add_permission(self, request: HttpRequest, obj: PurchaseOrder | None = None) -> bool:  # noqa: ARG002, D102
        return False

    def has_delete_permission(self, request: HttpRequest, obj: PurchaseOrder | None = None) -> bool:  # noqa: ARG002, D102
        return False


class PurchaseOrderCreditNoteInline(admin.TabularInline):
    """Read-only inline display of credit notes issued against a purchase order.

    Credit notes should be issued through the management dashboard to ensure
    proper status recalculation. The inline is read-only for audit integrity.
    """

    model = PurchaseOrderCreditNote
    extra = 0
    readonly_fields = ("amount", "reason", "issued_by", "created_at")

    def has_add_permission(self, request: HttpRequest, obj: PurchaseOrder | None = None) -> bool:  # noqa: ARG002, D102
        return False

    def has_delete_permission(self, request: HttpRequest, obj: PurchaseOrder | None = None) -> bool:  # noqa: ARG002, D102
        return False


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    """Admin interface for managing corporate purchase orders.

    Displays the PO reference, organization, status, and financial summary.
    Money fields are read-only to prevent manual edits; changes should flow
    through the payment recording and credit note workflows.
    """

    list_display = (
        "reference",
        "organization_name",
        "conference",
        "status",
        "total",
        "balance_due_display",
        "created_at",
    )
    list_filter = ("conference", "status")
    search_fields = ("reference", "organization_name", "contact_email")
    readonly_fields = ("reference", "subtotal", "total", "balance_due_display", "total_paid_display")
    inlines = (PurchaseOrderLineItemInline, PurchaseOrderPaymentInline, PurchaseOrderCreditNoteInline)

    @admin.display(description="Balance Due")
    def balance_due_display(self, obj: PurchaseOrder) -> str:
        """Render the computed balance due for the list and detail views."""
        return str(obj.balance_due)

    @admin.display(description="Total Paid")
    def total_paid_display(self, obj: PurchaseOrder) -> str:
        """Render the computed total paid for the detail view."""
        return str(obj.total_paid)
