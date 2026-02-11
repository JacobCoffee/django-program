"""Django admin configuration for the registration app."""

from typing import TYPE_CHECKING

from django.contrib import admin

if TYPE_CHECKING:
    from django.http import HttpRequest

from django_program.registration.models import (
    AddOn,
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


@admin.register(TicketType)
class TicketTypeAdmin(admin.ModelAdmin):
    """Admin interface for managing ticket types.

    Provides filtering by conference and active status, search by name and
    slug, and auto-population of the slug from the ticket name.
    """

    list_display = ("name", "conference", "price", "is_active", "order")
    list_filter = ("conference", "is_active")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(AddOn)
class AddOnAdmin(admin.ModelAdmin):
    """Admin interface for managing add-ons.

    Uses ``filter_horizontal`` for the ``requires_ticket_types`` many-to-many
    field to provide a friendlier selection widget.
    """

    list_display = ("name", "conference", "price", "is_active")
    list_filter = ("conference", "is_active")
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
