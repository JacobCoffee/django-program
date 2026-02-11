"""Cart management service for conference registration.

Handles cart lifecycle, item management, voucher application, and pricing
summary computation. All methods are stateless and operate on Cart model
instances directly.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from django_program.registration.models import (
    AddOn,
    Cart,
    CartItem,
    Order,
    OrderLineItem,
    TicketType,
    Voucher,
)
from django_program.settings import get_config


@dataclass
class LineItemSummary:
    """Pricing breakdown for a single cart item."""

    item_id: int
    description: str
    quantity: int
    unit_price: Decimal
    discount: Decimal
    line_total: Decimal


@dataclass
class CartSummary:
    """Full pricing summary of a cart including voucher discounts."""

    items: list[LineItemSummary]
    subtotal: Decimal
    discount: Decimal
    total: Decimal


class CartService:
    """Stateless service for cart operations.

    All methods are static and enforce business rules around ticket
    availability, quantity limits, voucher validation, and add-on
    prerequisites.
    """

    @staticmethod
    def get_or_create_cart(user: object, conference: object) -> Cart:
        """Return the user's open cart, creating one if none exists.

        Expires any stale open carts for this user and conference before
        looking up or creating a fresh cart.

        Args:
            user: The authenticated user (AUTH_USER_MODEL instance).
            conference: The conference to create the cart for.

        Returns:
            An open Cart instance with a valid expiry time.
        """
        now = timezone.now()
        config = get_config()

        Cart.objects.filter(
            user=user,
            conference=conference,
            status=Cart.Status.OPEN,
            expires_at__lt=now,
        ).update(status=Cart.Status.EXPIRED)

        cart = Cart.objects.filter(
            user=user,
            conference=conference,
            status=Cart.Status.OPEN,
        ).first()

        if cart is not None:
            if cart.expires_at is None:
                cart.expires_at = now + timedelta(minutes=config.cart_expiry_minutes)
                cart.save(update_fields=["expires_at", "updated_at"])
            return cart

        return Cart.objects.create(
            user=user,
            conference=conference,
            status=Cart.Status.OPEN,
            expires_at=now + timedelta(minutes=config.cart_expiry_minutes),
        )

    @staticmethod
    @transaction.atomic
    def add_ticket(cart: Cart, ticket_type: TicketType, qty: int = 1) -> CartItem:
        """Add a ticket to the cart or increase its quantity.

        Validates availability, stock limits, per-user limits, and voucher
        requirements before modifying the cart.

        Args:
            cart: The open cart to add the ticket to.
            ticket_type: The ticket type to add.
            qty: Number of tickets to add (must be >= 1).

        Returns:
            The created or updated CartItem.

        Raises:
            ValidationError: If the ticket cannot be added due to business
                rule violations (unavailable, out of stock, limit exceeded,
                or voucher required).
        """
        _assert_cart_open(cart)

        if qty < 1:
            raise ValidationError("Quantity must be at least 1.")

        if ticket_type.conference_id != cart.conference_id:
            raise ValidationError("Ticket type does not belong to this cart's conference.")

        if not ticket_type.is_available:
            raise ValidationError(f"Ticket type '{ticket_type.name}' is not available.")

        item = cart.items.select_for_update().filter(ticket_type=ticket_type).first()
        existing_in_cart = item.quantity if item is not None else 0
        existing_in_orders = _ticket_order_quantity(cart, ticket_type)
        _validate_ticket_stock_and_limit(
            ticket_type=ticket_type,
            qty=qty,
            existing_in_cart=existing_in_cart,
            existing_in_orders=existing_in_orders,
        )

        if ticket_type.requires_voucher:
            voucher = cart.voucher
            if voucher is None or not voucher.unlocks_hidden_tickets:
                raise ValidationError(
                    f"Ticket type '{ticket_type.name}' requires a voucher that unlocks hidden tickets."
                )
            applicable_ids = set(voucher.applicable_ticket_types.values_list("pk", flat=True))
            if applicable_ids and ticket_type.pk not in applicable_ids:
                raise ValidationError(f"The applied voucher does not cover ticket type '{ticket_type.name}'.")

        item = _upsert_ticket_item(
            cart=cart,
            ticket_type=ticket_type,
            qty=qty,
            item=item,
            existing_in_orders=existing_in_orders,
        )

        _extend_cart_expiry(cart)
        return item

    @staticmethod
    @transaction.atomic
    def add_addon(cart: Cart, addon: AddOn, qty: int = 1) -> CartItem:
        """Add an add-on to the cart or increase its quantity.

        Validates availability, stock, and ticket-type prerequisites before
        modifying the cart.

        Args:
            cart: The open cart to add the add-on to.
            addon: The add-on to add.
            qty: Number of add-ons to add (must be >= 1).

        Returns:
            The created or updated CartItem.

        Raises:
            ValidationError: If the add-on cannot be added due to business
                rule violations (inactive, out of window, prerequisite
                ticket missing, or out of stock).
        """
        _assert_cart_open(cart)

        if qty < 1:
            raise ValidationError("Quantity must be at least 1.")

        if addon.conference_id != cart.conference_id:
            raise ValidationError("Add-on does not belong to this cart's conference.")

        _validate_addon_available(addon)

        required_ticket_ids = set(addon.requires_ticket_types.values_list("pk", flat=True))
        if required_ticket_ids:
            ticket_ids_in_cart = set(
                cart.items.filter(
                    ticket_type__isnull=False,
                ).values_list("ticket_type_id", flat=True)
            )
            if not required_ticket_ids & ticket_ids_in_cart:
                raise ValidationError(
                    f"Add-on '{addon.name}' requires one of the following ticket "
                    f"types in your cart: "
                    f"{', '.join(str(pk) for pk in sorted(required_ticket_ids))}."
                )

        item = cart.items.select_for_update().filter(addon=addon).first()
        existing_in_cart = item.quantity if item is not None else 0
        _validate_addon_stock(addon, existing_in_cart + qty)
        item = _upsert_addon_item(cart=cart, addon=addon, qty=qty, item=item)

        _extend_cart_expiry(cart)
        return item

    @staticmethod
    @transaction.atomic
    def remove_item(cart: Cart, item_id: int) -> None:
        """Remove an item from the cart, cascading add-on removals if needed.

        When removing a ticket type, any add-ons that require that ticket type
        (and no other qualifying ticket type remains in the cart) are also
        removed.

        Args:
            cart: The cart to remove the item from.
            item_id: The primary key of the CartItem to remove.

        Raises:
            ValidationError: If the item does not exist or does not belong
                to this cart.
        """
        _assert_cart_open(cart)

        try:
            item = cart.items.get(pk=item_id)
        except CartItem.DoesNotExist:
            raise ValidationError("Cart item not found.") from None

        if item.ticket_type_id is not None:
            _cascade_remove_orphaned_addons(cart, removing_ticket_type_id=item.ticket_type_id)

        item.delete()

    @staticmethod
    @transaction.atomic
    def update_quantity(cart: Cart, item_id: int, qty: int) -> CartItem | None:
        """Update the quantity of a cart item.

        If the new quantity is zero or negative the item is removed instead.
        Re-validates stock and per-user limits for the new quantity.

        Args:
            cart: The cart containing the item.
            item_id: The primary key of the CartItem to update.
            qty: The new absolute quantity.

        Returns:
            The updated CartItem, or ``None`` if the item was removed.

        Raises:
            ValidationError: If the new quantity violates stock or per-user
                limits, or if the item does not belong to this cart.
        """
        _assert_cart_open(cart)

        if qty <= 0:
            CartService.remove_item(cart, item_id)
            return None

        try:
            item = cart.items.get(pk=item_id)
        except CartItem.DoesNotExist:
            raise ValidationError("Cart item not found.") from None

        if item.ticket_type_id is not None:
            _validate_ticket_quantity(cart, item.ticket_type, qty)
        elif item.addon_id is not None:
            _validate_addon_quantity(item.addon, qty)

        item.quantity = qty
        item.save(update_fields=["quantity"])
        _extend_cart_expiry(cart)
        return item

    @staticmethod
    def apply_voucher(cart: Cart, code: str) -> Voucher:
        """Apply a voucher code to the cart.

        Args:
            cart: The cart to apply the voucher to.
            code: The voucher code string.

        Returns:
            The validated Voucher instance now attached to the cart.

        Raises:
            ValidationError: If the voucher code is not found, not valid,
                or does not belong to this cart's conference.
        """
        _assert_cart_open(cart)

        try:
            voucher = Voucher.objects.get(code=code, conference=cart.conference)
        except Voucher.DoesNotExist:
            raise ValidationError(f"Voucher code '{code}' not found.") from None

        if not voucher.is_valid:
            raise ValidationError(f"Voucher code '{code}' is no longer valid.")

        cart.voucher = voucher
        cart.save(update_fields=["voucher", "updated_at"])
        return voucher

    @staticmethod
    def get_summary(cart: Cart) -> CartSummary:
        """Compute a full pricing summary of the cart.

        Iterates all cart items, applies any voucher discounts, and returns
        a structured summary with per-item and aggregate totals.

        Args:
            cart: The cart to summarise.

        Returns:
            A CartSummary with line items, subtotal, discount, and total.
        """
        items = list(cart.items.select_related("ticket_type", "addon"))
        voucher = cart.voucher

        applicable_ticket_ids, applicable_addon_ids = _resolve_voucher_scope(voucher)

        line_summaries, subtotal, applicable_line_totals = _build_line_summaries(
            items,
            voucher,
            applicable_ticket_ids,
            applicable_addon_ids,
        )

        total_discount = _apply_voucher_discounts(
            voucher,
            line_summaries,
            applicable_line_totals,
        )

        for summary in line_summaries:
            summary.line_total = summary.line_total - summary.discount

        return CartSummary(
            items=line_summaries,
            subtotal=subtotal,
            discount=total_discount,
            total=max(subtotal - total_discount, Decimal("0.00")),
        )


def _assert_cart_open(cart: Cart) -> None:
    """Raise ValidationError when the cart cannot be modified."""
    now = timezone.now()
    if cart.expires_at and cart.expires_at < now:
        raise ValidationError("Cart has expired.")

    if cart.status != Cart.Status.OPEN:
        raise ValidationError("Only open carts can be modified.")


def _ticket_order_quantity(cart: Cart, ticket_type: TicketType) -> int:
    """Return quantity already purchased by this user for this ticket."""
    return (
        OrderLineItem.objects.filter(
            order__user=cart.user,
            order__conference=cart.conference,
            ticket_type=ticket_type,
            order__status__in=[Order.Status.PAID, Order.Status.PARTIALLY_REFUNDED],
        ).aggregate(total=models.Sum("quantity"))["total"]
        or 0
    )


def _validate_ticket_stock_and_limit(
    *,
    ticket_type: TicketType,
    qty: int,
    existing_in_cart: int,
    existing_in_orders: int,
) -> None:
    """Validate ticket stock and per-user limits for add quantity."""
    remaining = ticket_type.remaining_quantity
    if remaining is not None and remaining < existing_in_cart + qty:
        raise ValidationError(f"Only {remaining} tickets of type '{ticket_type.name}' remaining.")

    if existing_in_cart + existing_in_orders + qty > ticket_type.limit_per_user:
        raise ValidationError(
            f"Adding {qty} would exceed the per-user limit of {ticket_type.limit_per_user} for '{ticket_type.name}'."
        )


def _upsert_ticket_item(
    *,
    cart: Cart,
    ticket_type: TicketType,
    qty: int,
    item: CartItem | None,
    existing_in_orders: int,
) -> CartItem:
    """Increment/create ticket cart item safely under concurrent inserts."""
    if item is not None:
        item.quantity += qty
        item.save(update_fields=["quantity"])
        return item

    try:
        return CartItem.objects.create(
            cart=cart,
            ticket_type=ticket_type,
            quantity=qty,
        )
    except IntegrityError:
        item = cart.items.select_for_update().get(ticket_type=ticket_type)
        _validate_ticket_stock_and_limit(
            ticket_type=ticket_type,
            qty=qty,
            existing_in_cart=item.quantity,
            existing_in_orders=existing_in_orders,
        )
        item.quantity += qty
        item.save(update_fields=["quantity"])
        return item


def _addon_sold_quantity(addon: AddOn) -> int:
    """Return quantity already sold for an add-on."""
    return (
        OrderLineItem.objects.filter(
            addon=addon,
            order__status__in=[Order.Status.PAID, Order.Status.PARTIALLY_REFUNDED],
        ).aggregate(total=models.Sum("quantity"))["total"]
        or 0
    )


def _validate_addon_stock(addon: AddOn, desired_total_qty: int) -> None:
    """Validate add-on stock against desired total in-cart quantity."""
    if addon.total_quantity <= 0:
        return

    sold = _addon_sold_quantity(addon)
    remaining = addon.total_quantity - sold
    if remaining < desired_total_qty:
        raise ValidationError(f"Only {remaining} of add-on '{addon.name}' remaining.")


def _upsert_addon_item(*, cart: Cart, addon: AddOn, qty: int, item: CartItem | None) -> CartItem:
    """Increment/create add-on cart item safely under concurrent inserts."""
    if item is not None:
        item.quantity += qty
        item.save(update_fields=["quantity"])
        return item

    try:
        return CartItem.objects.create(
            cart=cart,
            addon=addon,
            quantity=qty,
        )
    except IntegrityError:
        item = cart.items.select_for_update().get(addon=addon)
        _validate_addon_stock(addon, item.quantity + qty)
        item.quantity += qty
        item.save(update_fields=["quantity"])
        return item


def _resolve_voucher_scope(
    voucher: Voucher | None,
) -> tuple[set[int] | None, set[int] | None]:
    """Extract the set of ticket/addon IDs a voucher applies to.

    Returns ``(None, None)`` when no voucher is attached. A ``None`` set
    means the voucher applies to all items of that type.
    """
    if voucher is None:
        return None, None

    ticket_ids = set(voucher.applicable_ticket_types.values_list("pk", flat=True))
    addon_ids = set(voucher.applicable_addons.values_list("pk", flat=True))
    return (ticket_ids or None), (addon_ids or None)


def _build_line_summaries(
    items: list[CartItem],
    voucher: Voucher | None,
    applicable_ticket_ids: set[int] | None,
    applicable_addon_ids: set[int] | None,
) -> tuple[list[LineItemSummary], Decimal, list[tuple[int, Decimal]]]:
    """Build undiscounted line summaries and identify voucher-applicable lines.

    Returns:
        A tuple of (line_summaries, subtotal, applicable_line_totals) where
        applicable_line_totals maps summary indices to their undiscounted
        line totals for later discount calculation.
    """
    line_summaries: list[LineItemSummary] = []
    subtotal = Decimal("0.00")
    applicable_line_totals: list[tuple[int, Decimal]] = []

    for item in items:
        description = _cart_item_description(item)
        line_total = item.line_total
        subtotal += line_total

        is_applicable = _item_is_voucher_applicable(
            item,
            applicable_ticket_ids,
            applicable_addon_ids,
        )
        if voucher is not None and is_applicable:
            applicable_line_totals.append((len(line_summaries), line_total))

        line_summaries.append(
            LineItemSummary(
                item_id=item.pk,
                description=description,
                quantity=item.quantity,
                unit_price=item.unit_price,
                discount=Decimal("0.00"),
                line_total=line_total,
            )
        )

    return line_summaries, subtotal, applicable_line_totals


def _cart_item_description(item: CartItem) -> str:
    """Return a safe cart item description without type ignores/asserts."""
    if item.ticket_type is not None:
        return item.ticket_type.name
    if item.addon is not None:
        return item.addon.name
    return "Unknown item"


def _apply_voucher_discounts(
    voucher: Voucher | None,
    line_summaries: list[LineItemSummary],
    applicable_line_totals: list[tuple[int, Decimal]],
) -> Decimal:
    """Apply voucher discounts to the applicable line summaries in-place.

    Returns:
        The total discount amount across all applicable lines.
    """
    if voucher is None or not applicable_line_totals:
        return Decimal("0.00")

    if voucher.voucher_type == Voucher.VoucherType.COMP:
        return _apply_comp_discount(line_summaries, applicable_line_totals)

    if voucher.voucher_type == Voucher.VoucherType.PERCENTAGE:
        return _apply_percentage_discount(
            voucher.discount_value,
            line_summaries,
            applicable_line_totals,
        )

    if voucher.voucher_type == Voucher.VoucherType.FIXED_AMOUNT:
        return _apply_fixed_discount(
            voucher.discount_value,
            line_summaries,
            applicable_line_totals,
        )

    return Decimal("0.00")


def _apply_comp_discount(
    line_summaries: list[LineItemSummary],
    applicable_line_totals: list[tuple[int, Decimal]],
) -> Decimal:
    """Apply a 100% complimentary discount to applicable lines."""
    total_discount = Decimal("0.00")
    for idx, line_total in applicable_line_totals:
        line_summaries[idx].discount = line_total
        total_discount += line_total
    return total_discount


def _apply_percentage_discount(
    discount_value: Decimal,
    line_summaries: list[LineItemSummary],
    applicable_line_totals: list[tuple[int, Decimal]],
) -> Decimal:
    """Apply a percentage discount to applicable lines."""
    pct = discount_value / Decimal(100)
    total_discount = Decimal("0.00")
    for idx, line_total in applicable_line_totals:
        discount = (line_total * pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        line_summaries[idx].discount = discount
        total_discount += discount
    return total_discount


def _apply_fixed_discount(
    discount_value: Decimal,
    line_summaries: list[LineItemSummary],
    applicable_line_totals: list[tuple[int, Decimal]],
) -> Decimal:
    """Distribute a fixed amount discount proportionally across applicable lines.

    The last applicable line receives any remainder to avoid rounding drift.
    """
    applicable_subtotal = sum((lt for _, lt in applicable_line_totals), Decimal("0.00"))
    budget = min(discount_value, applicable_subtotal)
    remaining_budget = budget
    total_discount = Decimal("0.00")

    for i, (idx, line_total) in enumerate(applicable_line_totals):
        is_last = i == len(applicable_line_totals) - 1
        if is_last or applicable_subtotal == 0:
            share = remaining_budget
        else:
            share = (budget * line_total / applicable_subtotal).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
            share = min(share, remaining_budget)

        line_summaries[idx].discount = share
        total_discount += share
        remaining_budget -= share

    return total_discount


def _extend_cart_expiry(cart: Cart) -> None:
    """Push the cart expiry out to now + configured expiry minutes."""
    config = get_config()
    cart.expires_at = timezone.now() + timedelta(minutes=config.cart_expiry_minutes)
    cart.save(update_fields=["expires_at", "updated_at"])


def _validate_addon_available(addon: AddOn) -> None:
    """Raise ValidationError if the add-on is not currently purchasable."""
    if not addon.is_active:
        raise ValidationError(f"Add-on '{addon.name}' is not active.")
    now = timezone.now()
    if addon.available_from and now < addon.available_from:
        raise ValidationError(f"Add-on '{addon.name}' is not yet available.")
    if addon.available_until and now > addon.available_until:
        raise ValidationError(f"Add-on '{addon.name}' is no longer available.")


def _validate_ticket_quantity(cart: Cart, ticket_type: TicketType, new_qty: int) -> None:
    """Validate stock and per-user limits for a new ticket quantity."""
    remaining = ticket_type.remaining_quantity
    if remaining is not None and remaining < new_qty:
        raise ValidationError(f"Only {remaining} tickets of type '{ticket_type.name}' remaining.")

    existing_in_orders = (
        OrderLineItem.objects.filter(
            order__user=cart.user,
            order__conference=cart.conference,
            ticket_type=ticket_type,
            order__status__in=[Order.Status.PAID, Order.Status.PARTIALLY_REFUNDED],
        ).aggregate(total=models.Sum("quantity"))["total"]
        or 0
    )
    if existing_in_orders + new_qty > ticket_type.limit_per_user:
        raise ValidationError(
            f"Quantity {new_qty} would exceed the per-user limit of "
            f"{ticket_type.limit_per_user} for '{ticket_type.name}'."
        )


def _validate_addon_quantity(addon: AddOn, new_qty: int) -> None:
    """Validate remaining stock for a new add-on quantity."""
    if addon.total_quantity > 0:
        sold = (
            OrderLineItem.objects.filter(
                addon=addon,
                order__status__in=[Order.Status.PAID, Order.Status.PARTIALLY_REFUNDED],
            ).aggregate(total=models.Sum("quantity"))["total"]
            or 0
        )
        remaining = addon.total_quantity - sold
        if remaining < new_qty:
            raise ValidationError(f"Only {remaining} of add-on '{addon.name}' remaining.")


def _cascade_remove_orphaned_addons(cart: Cart, removing_ticket_type_id: int) -> None:
    """Remove add-on items whose ticket prerequisite is no longer satisfied.

    After removing a ticket from the cart, any add-ons that required that
    ticket type are checked. If no other ticket type in the cart satisfies
    the prerequisite, those add-on items are deleted.
    """
    remaining_ticket_ids = set(
        cart.items.filter(
            ticket_type__isnull=False,
        )
        .exclude(
            ticket_type_id=removing_ticket_type_id,
        )
        .values_list("ticket_type_id", flat=True)
    )

    addon_items = cart.items.filter(addon__isnull=False).select_related("addon")
    for addon_item in addon_items:
        required_ids = set(addon_item.addon.requires_ticket_types.values_list("pk", flat=True))
        if not required_ids:
            continue
        if not required_ids & remaining_ticket_ids:
            addon_item.delete()


def _item_is_voucher_applicable(
    item: CartItem,
    applicable_ticket_ids: set[int] | None,
    applicable_addon_ids: set[int] | None,
) -> bool:
    """Check whether a cart item qualifies for voucher discount.

    A ``None`` applicable set means "all items of that type qualify".
    """
    if item.ticket_type_id is not None:
        if applicable_ticket_ids is None:
            return True
        return item.ticket_type_id in applicable_ticket_ids

    if item.addon_id is not None:
        if applicable_addon_ids is None:
            return True
        return item.addon_id in applicable_addon_ids

    return False
