"""Registration, ticketing, cart, order, and payment models for django-program."""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class TicketType(models.Model):
    """A purchasable ticket category for a conference.

    Defines a class of ticket (e.g. "Early Bird", "Student", "Corporate") with
    pricing, availability windows, and optional quantity limits. Ticket types
    flagged with ``requires_voucher`` are hidden from the public storefront
    until unlocked by a matching voucher code.
    """

    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="ticket_types",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    description = models.TextField(blank=True, default="")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    available_from = models.DateTimeField(null=True, blank=True)
    available_until = models.DateTimeField(null=True, blank=True)
    total_quantity = models.PositiveIntegerField(
        default=0,
        help_text="Maximum number of tickets available. 0 means unlimited.",
    )
    limit_per_user = models.PositiveIntegerField(default=10)
    requires_voucher = models.BooleanField(
        default=False,
        help_text="When True, this ticket type is hidden unless unlocked by a voucher.",
    )
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "name"]
        unique_together = [("conference", "slug")]

    def __str__(self) -> str:
        return f"{self.name} ({self.conference.slug})"

    @property
    def remaining_quantity(self) -> int | None:
        """Return the number of tickets still available for purchase.

        Returns:
            The remaining count, or ``None`` if this ticket type has unlimited
            quantity (``total_quantity == 0``).
        """
        if self.total_quantity == 0:
            return None
        sold = (
            self.order_line_items.filter(
                order__status__in=[
                    Order.Status.PAID,
                    Order.Status.PARTIALLY_REFUNDED,
                ],
            ).aggregate(total=models.Sum("quantity"))["total"]
            or 0
        )
        return self.total_quantity - sold

    @property
    def is_available(self) -> bool:
        """Check whether this ticket type can currently be purchased.

        A ticket is available when all of the following are true:

        * ``is_active`` is ``True``
        * The current time is within the ``available_from`` / ``available_until``
          window (if set)
        * There is remaining quantity (or quantity is unlimited)
        """
        if not self.is_active:
            return False
        now = timezone.now()
        if self.available_from and now < self.available_from:
            return False
        if self.available_until and now > self.available_until:
            return False
        remaining = self.remaining_quantity
        return not (remaining is not None and remaining <= 0)


class AddOn(models.Model):
    """An optional extra attached to a ticket (e.g. workshop, t-shirt).

    Add-ons can optionally be restricted to specific ticket types via the
    ``requires_ticket_types`` relation. When that relation is empty the add-on
    is available to holders of any ticket type.
    """

    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="addons",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    description = models.TextField(blank=True, default="")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    requires_ticket_types = models.ManyToManyField(
        TicketType,
        blank=True,
        related_name="available_addons",
        help_text="Ticket types this add-on is available for. Empty means all.",
    )
    available_from = models.DateTimeField(null=True, blank=True)
    available_until = models.DateTimeField(null=True, blank=True)
    total_quantity = models.PositiveIntegerField(
        default=0,
        help_text="Maximum number available. 0 means unlimited.",
    )
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "name"]
        unique_together = [("conference", "slug")]

    def __str__(self) -> str:
        return f"{self.name} ({self.conference.slug})"


class Voucher(models.Model):
    """A discount or access code for tickets and add-ons.

    Vouchers can provide a percentage discount, a fixed amount off, or full
    complimentary access (100% off). They can also unlock hidden ticket types
    that require a voucher to purchase.
    """

    class VoucherType(models.TextChoices):
        """The type of discount a voucher provides."""

        COMP = "comp", "Complimentary (100% off)"
        PERCENTAGE = "percentage", "Percentage discount"
        FIXED_AMOUNT = "fixed_amount", "Fixed amount discount"

    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="vouchers",
    )
    code = models.CharField(max_length=100)
    voucher_type = models.CharField(
        max_length=20,
        choices=VoucherType.choices,
        default=VoucherType.COMP,
    )
    discount_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Percentage (0-100) or fixed amount depending on voucher_type.",
    )
    applicable_ticket_types = models.ManyToManyField(
        TicketType,
        blank=True,
        related_name="vouchers",
        help_text="Ticket types this voucher applies to. Empty means all.",
    )
    applicable_addons = models.ManyToManyField(
        AddOn,
        blank=True,
        related_name="vouchers",
        help_text="Add-ons this voucher applies to. Empty means all.",
    )
    max_uses = models.PositiveIntegerField(default=1)
    times_used = models.PositiveIntegerField(default=0)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    unlocks_hidden_tickets = models.BooleanField(
        default=False,
        help_text="When True, reveals ticket types that require a voucher.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("conference", "code")]

    def __str__(self) -> str:
        return f"{self.code} ({self.conference.slug})"

    @property
    def is_valid(self) -> bool:
        """Check whether this voucher can currently be redeemed.

        A voucher is valid when it is active, has remaining uses, and the
        current time falls within the optional validity window.
        """
        if not self.is_active:
            return False
        if self.times_used >= self.max_uses:
            return False
        now = timezone.now()
        if self.valid_from and now < self.valid_from:
            return False
        return not (self.valid_until and now > self.valid_until)


class Cart(models.Model):
    """A user's shopping cart for a conference.

    Carts hold ticket and add-on selections before checkout. They transition
    through statuses from ``OPEN`` to ``CHECKED_OUT`` on successful payment,
    or to ``EXPIRED`` / ``ABANDONED`` when the session times out.
    """

    class Status(models.TextChoices):
        """Lifecycle states for a shopping cart."""

        OPEN = "open", "Open"
        CHECKED_OUT = "checked_out", "Checked Out"
        EXPIRED = "expired", "Expired"
        ABANDONED = "abandoned", "Abandoned"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="carts",
    )
    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="carts",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )
    voucher = models.ForeignKey(
        Voucher,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="carts",
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Cart {self.pk} ({self.user}, {self.status})"


class CartItem(models.Model):
    """A single item (ticket or add-on) in a cart.

    Each cart item references exactly one of ``ticket_type`` or ``addon``,
    enforced by a database-level check constraint. The ``unit_price`` and
    ``line_total`` properties compute pricing from the referenced item.
    """

    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name="items",
    )
    ticket_type = models.ForeignKey(
        TicketType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cart_items",
    )
    addon = models.ForeignKey(
        AddOn,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cart_items",
    )
    quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(ticket_type__isnull=False, addon__isnull=True)
                    | models.Q(ticket_type__isnull=True, addon__isnull=False)
                ),
                name="registration_cartitem_exactly_one_type",
            ),
        ]

    def __str__(self) -> str:
        item = self.ticket_type or self.addon
        return f"{self.quantity}x {item}"

    @property
    def unit_price(self) -> Decimal:
        """Return the per-unit price of this cart item."""
        if self.ticket_type is not None:
            return self.ticket_type.price
        if self.addon is not None:
            return self.addon.price
        return Decimal("0.00")

    @property
    def line_total(self) -> Decimal:
        """Return the total price for this line (unit_price * quantity)."""
        return self.unit_price * self.quantity


class Order(models.Model):
    """A completed checkout with billing and payment info.

    Orders are created when a cart is checked out. They capture a snapshot of
    the pricing, discounts, and billing details at the time of purchase. The
    ``reference`` field holds a unique human-readable order number.
    """

    class Status(models.TextChoices):
        """Lifecycle states for an order."""

        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        REFUNDED = "refunded", "Refunded"
        PARTIALLY_REFUNDED = "partially_refunded", "Partially Refunded"
        CANCELLED = "cancelled", "Cancelled"

    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="orders",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="orders",
    )
    status = models.CharField(
        max_length=25,
        choices=Status.choices,
        default=Status.PENDING,
    )
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    voucher_code = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Snapshot of the voucher code applied at checkout.",
    )
    voucher_details = models.TextField(
        blank=True,
        default="",
        help_text="JSON snapshot of the voucher state at checkout time.",
    )
    billing_name = models.CharField(max_length=200, blank=True, default="")
    billing_email = models.EmailField(blank=True, default="")
    billing_company = models.CharField(max_length=200, blank=True, default="")
    reference = models.CharField(
        max_length=100,
        unique=True,
        help_text='Unique order reference, e.g. "ORD-A1B2C3".',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.reference} ({self.status})"


class OrderLineItem(models.Model):
    """A snapshot of a purchased item at checkout time.

    Line items are immutable records of what was purchased, including the price
    and description at the time of checkout. They may reference the original
    ``TicketType`` or ``AddOn`` for traceability, but those links are optional
    since the source item could be deleted after the order is placed.
    """

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="line_items",
    )
    description = models.CharField(max_length=300)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=10, decimal_places=2)
    ticket_type = models.ForeignKey(
        TicketType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_line_items",
    )
    addon = models.ForeignKey(
        AddOn,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_line_items",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.quantity}x {self.description}"


class Payment(models.Model):
    """A payment record against an order.

    Each payment represents a single financial transaction (Stripe charge,
    complimentary comp, credit application, or manual entry). An order may
    have multiple payments if it is partially refunded and re-paid.
    """

    class Method(models.TextChoices):
        """Supported payment methods."""

        STRIPE = "stripe", "Stripe"
        COMP = "comp", "Complimentary"
        CREDIT = "credit", "Credit"
        MANUAL = "manual", "Manual"

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="payments",
    )
    method = models.CharField(
        max_length=20,
        choices=Method.choices,
        default=Method.STRIPE,
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    stripe_payment_intent_id = models.CharField(max_length=200, blank=True, default="")
    stripe_charge_id = models.CharField(max_length=200, blank=True, default="")
    reference = models.CharField(max_length=200, blank=True, default="")
    note = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_payments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.method} {self.amount} for {self.order.reference}"


class Credit(models.Model):
    """A store credit that can be applied to future orders.

    Credits are typically issued as part of a refund workflow. They are tied
    to a specific conference and user, and can be applied to a new order or
    left to expire.
    """

    class Status(models.TextChoices):
        """Lifecycle states for a store credit."""

        AVAILABLE = "available", "Available"
        APPLIED = "applied", "Applied"
        EXPIRED = "expired", "Expired"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="credits",
    )
    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="credits",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AVAILABLE,
    )
    applied_to_order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="applied_credits",
    )
    source_order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issued_credits",
    )
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Credit {self.amount} for {self.user} ({self.status})"
