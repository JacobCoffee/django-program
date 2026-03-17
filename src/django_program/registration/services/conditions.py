"""Condition evaluator service for the discount and condition engine.

Orchestrates evaluation of all active conditions for a user/cart context and
returns applicable discounts as structured data for cart pricing integration.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from django_program.registration.conditions import (
    ConditionBase,
    DiscountForCategory,
    DiscountForProduct,
    GroupMemberCondition,
    IncludedProductCondition,
    SpeakerCondition,
    TimeOrStockLimitCondition,
)
from django_program.registration.models import AddOn, Cart, CartItem, TicketType

if TYPE_CHECKING:
    from django.db.models import QuerySet


@dataclass
class CartItemDiscount:
    """A discount applied to a single cart item by a condition."""

    cart_item_id: int
    condition_name: str
    condition_type: str
    discount_amount: Decimal
    original_price: Decimal


# All concrete condition types that use DiscountEffect (ConditionBase + DiscountEffect).
_CONDITION_TYPES: list[type[ConditionBase]] = [
    TimeOrStockLimitCondition,
    SpeakerCondition,
    GroupMemberCondition,
    IncludedProductCondition,
    DiscountForProduct,
]


def _item_matches_discount_scope(
    item: CartItem,
    applicable_ticket_ids: set[int],
    applicable_addon_ids: set[int],
) -> bool:
    """Check whether a cart item falls within a condition's applicable scope.

    Args:
        item: The cart item to check.
        applicable_ticket_ids: Set of ticket type PKs (empty means all tickets).
        applicable_addon_ids: Set of add-on PKs (empty means all add-ons).

    Returns:
        True if the item is covered by the discount scope.
    """
    if item.ticket_type_id is not None:
        if not applicable_ticket_ids:
            return True
        return item.ticket_type_id in applicable_ticket_ids
    if item.addon_id is not None:
        if not applicable_addon_ids:
            return True
        return item.addon_id in applicable_addon_ids
    return False


def _item_matches_category_scope(item: CartItem, condition: DiscountForCategory) -> bool:
    """Check whether a cart item falls within a category discount's scope.

    Args:
        item: The cart item to check.
        condition: The category discount to check against.

    Returns:
        True if the item's type matches the category scope.
    """
    if item.ticket_type_id is not None:
        return condition.apply_to_tickets
    if item.addon_id is not None:
        return condition.apply_to_addons
    return False


def _apply_discount_effect_conditions(
    items: list[CartItem],
    user: object,
    conference: object,
    discounted_item_ids: set[int],
    results: list[CartItemDiscount],
) -> None:
    """Evaluate all DiscountEffect-based conditions and collect discounts.

    Args:
        items: Cart items to evaluate against.
        user: The cart owner.
        conference: The conference context.
        discounted_item_ids: Already-discounted item PKs (mutated in place).
        results: Discount results list (mutated in place).
    """
    for condition_cls in _CONDITION_TYPES:
        conditions = condition_cls.objects.filter(
            conference=conference,
            is_active=True,
        ).order_by("priority", "name")

        for condition in conditions:
            if not condition.evaluate(user, conference):
                continue

            applicable_ticket_ids = set(condition.applicable_ticket_types.values_list("pk", flat=True))
            applicable_addon_ids = set(condition.applicable_addons.values_list("pk", flat=True))

            for item in items:
                if item.pk in discounted_item_ids:
                    continue
                if not _item_matches_discount_scope(item, applicable_ticket_ids, applicable_addon_ids):
                    continue

                discount_amount = condition.calculate_discount(item.unit_price, item.quantity)
                if discount_amount > Decimal("0.00"):
                    results.append(
                        CartItemDiscount(
                            cart_item_id=item.pk,
                            condition_name=str(condition.name),
                            condition_type=condition_cls.__name__,
                            discount_amount=discount_amount,
                            original_price=item.line_total,
                        )
                    )
                    discounted_item_ids.add(item.pk)


def _apply_category_conditions(
    items: list[CartItem],
    user: object,
    conference: object,
    discounted_item_ids: set[int],
    results: list[CartItemDiscount],
) -> None:
    """Evaluate category discount conditions and collect discounts.

    Args:
        items: Cart items to evaluate against.
        user: The cart owner.
        conference: The conference context.
        discounted_item_ids: Already-discounted item PKs (mutated in place).
        results: Discount results list (mutated in place).
    """
    category_conditions = DiscountForCategory.objects.filter(
        conference=conference,
        is_active=True,
    ).order_by("priority", "name")

    for condition in category_conditions:
        if not condition.evaluate(user, conference):
            continue

        for item in items:
            if item.pk in discounted_item_ids:
                continue
            if not _item_matches_category_scope(item, condition):
                continue

            discount_amount = condition.calculate_discount(item.unit_price, item.quantity)
            if discount_amount > Decimal("0.00"):
                results.append(
                    CartItemDiscount(
                        cart_item_id=item.pk,
                        condition_name=str(condition.name),
                        condition_type="DiscountForCategory",
                        discount_amount=discount_amount,
                        original_price=item.line_total,
                    )
                )
                discounted_item_ids.add(item.pk)


def evaluate_for_cart(cart: Cart) -> list[CartItemDiscount]:
    """Evaluate all conditions and return applicable discounts for each cart item.

    Queries all active conditions for the cart's conference, evaluates each
    against the cart's user, and calculates discounts for matching cart items.
    First match by priority wins per item (no stacking).

    Args:
        cart: The cart to evaluate conditions for.

    Returns:
        A list of CartItemDiscount entries, one per discounted cart item.
    """
    items = list(cart.items.select_related("ticket_type", "addon"))
    if not items:
        return []

    user = cart.user
    conference = cart.conference
    discounted_item_ids: set[int] = set()
    results: list[CartItemDiscount] = []

    _apply_discount_effect_conditions(items, user, conference, discounted_item_ids, results)
    _apply_category_conditions(items, user, conference, discounted_item_ids, results)

    return results


def get_eligible_discounts(user: object, conference: object) -> list[ConditionBase]:
    """Return all conditions the user currently qualifies for.

    Args:
        user: The authenticated user.
        conference: The conference to check conditions for.

    Returns:
        A list of condition instances the user qualifies for.
    """
    eligible: list[ConditionBase] = []

    all_types = [*_CONDITION_TYPES, DiscountForCategory]
    for condition_cls in all_types:
        conditions = condition_cls.objects.filter(
            conference=conference,
            is_active=True,
        ).order_by("priority", "name")
        eligible.extend(c for c in conditions if c.evaluate(user, conference))

    return eligible


def get_visible_products(user: object, conference: object) -> tuple[QuerySet, QuerySet]:  # noqa: ARG001
    """Return ticket types and add-ons visible to this user.

    Currently returns all active products for the conference. Future work
    can add flag-based visibility gating here.

    Args:
        user: The authenticated user.
        conference: The conference to retrieve products for.

    Returns:
        A tuple of (ticket_types_queryset, addons_queryset).
    """
    ticket_types = TicketType.objects.filter(conference=conference, is_active=True)
    addons = AddOn.objects.filter(conference=conference, is_active=True)
    return ticket_types, addons
