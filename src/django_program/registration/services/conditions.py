"""Condition evaluator service for the discount and condition engine.

Orchestrates evaluation of all active conditions for a user/cart context and
returns applicable discounts as structured data for cart pricing integration.

All condition types are merged into a single priority-sorted list before
evaluation so that priority ordering is respected globally across types.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import models

if TYPE_CHECKING:
    from django.db.models import QuerySet

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


@dataclass
class CartItemDiscount:
    """A discount applied to a single cart item by a condition."""

    cart_item_id: int
    condition_name: str
    condition_type: str
    discount_amount: Decimal
    original_price: Decimal
    condition_pk: int = 0
    condition_model: str = ""


# All concrete condition types that use DiscountEffect (ConditionBase + DiscountEffect).
_DISCOUNT_EFFECT_TYPES: list[type[ConditionBase]] = [
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
    """Check whether a cart item falls within a category discount's scope."""
    if item.ticket_type_id is not None:
        return condition.apply_to_tickets
    if item.addon_id is not None:
        return condition.apply_to_addons
    return False


def _gather_all_conditions(conference: object) -> list[ConditionBase]:
    """Fetch all active conditions across all types, sorted globally by priority.

    Returns a single merged list sorted by (priority, name) so that
    evaluation respects priority across different condition types.
    """
    all_conditions: list[ConditionBase] = []

    for condition_cls in _DISCOUNT_EFFECT_TYPES:
        qs = condition_cls.objects.filter(
            conference=conference,
            is_active=True,
        ).prefetch_related("applicable_ticket_types", "applicable_addons")
        all_conditions.extend(qs)

    category_qs = DiscountForCategory.objects.filter(conference=conference, is_active=True)
    all_conditions.extend(category_qs)

    all_conditions.sort(key=lambda c: (c.priority, str(c.name)))
    return all_conditions


def _apply_condition_to_items(
    condition: ConditionBase,
    items: list[CartItem],
    discounted_item_ids: set[int],
    results: list[CartItemDiscount],
) -> None:
    """Apply a single evaluated condition to undiscounted cart items."""
    is_category = isinstance(condition, DiscountForCategory)
    applicable_ticket_ids: set[int] = set()
    applicable_addon_ids: set[int] = set()

    if not is_category:
        applicable_ticket_ids = {t.pk for t in condition.applicable_ticket_types.all()}
        applicable_addon_ids = {a.pk for a in condition.applicable_addons.all()}

    for item in items:
        if item.pk in discounted_item_ids:
            continue

        if is_category:
            if not _item_matches_category_scope(item, condition):
                continue
        elif not _item_matches_discount_scope(item, applicable_ticket_ids, applicable_addon_ids):
            continue

        discount_amount = condition.calculate_discount(item.unit_price, item.quantity)
        if discount_amount <= Decimal("0.00"):
            continue

        results.append(
            CartItemDiscount(
                cart_item_id=item.pk,
                condition_name=str(condition.name),
                condition_type=type(condition).__name__,
                discount_amount=discount_amount,
                original_price=item.line_total,
                condition_pk=condition.pk,
                condition_model=type(condition).__name__,
            )
        )
        discounted_item_ids.add(item.pk)


def evaluate_for_items(
    items: list[CartItem],
    user: object,
    conference: object,
) -> list[CartItemDiscount]:
    """Evaluate all conditions against a list of cart items (side-effect free).

    Gathers all active conditions into a single priority-sorted list,
    evaluates each against the user, and applies the first matching
    discount per item (no stacking). Does NOT mutate the database;
    call ``commit_condition_usage()`` at checkout to persist usage.

    Args:
        items: Pre-fetched cart items to evaluate against.
        user: The cart owner.
        conference: The conference context.

    Returns:
        A list of CartItemDiscount entries, one per discounted cart item.
    """
    if not items:
        return []

    all_conditions = _gather_all_conditions(conference)
    discounted_item_ids: set[int] = set()
    results: list[CartItemDiscount] = []

    for condition in all_conditions:
        if condition.evaluate(user, conference):
            _apply_condition_to_items(condition, items, discounted_item_ids, results)

    return results


def evaluate_for_cart(cart: Cart) -> list[CartItemDiscount]:
    """Evaluate all conditions for a cart.

    Convenience wrapper around ``evaluate_for_items`` that fetches the
    cart's items with related data.

    Args:
        cart: The cart to evaluate conditions for.

    Returns:
        A list of CartItemDiscount entries, one per discounted cart item.
    """
    items = list(cart.items.select_related("ticket_type", "addon"))
    return evaluate_for_items(items, cart.user, cart.conference)


def commit_condition_usage(discounts: list[CartItemDiscount]) -> None:
    """Increment times_used for all stock-limited conditions that were applied.

    Call this at checkout time (not during cart summary viewing) to persist
    usage counts. Evaluation is side-effect free; this is the commit step.

    Groups discounts by condition and increments ``times_used`` by the number
    of items each condition discounted. Uses a conditional UPDATE that only
    increments when ``limit=0 OR times_used + count <= limit`` to prevent
    overshooting the cap under concurrency.

    Args:
        discounts: The discount results from ``evaluate_for_items``.
    """
    model_map: dict[str, type[ConditionBase]] = {
        cls.__name__: cls for cls in [*_DISCOUNT_EFFECT_TYPES, DiscountForCategory]
    }
    usage_counts: dict[tuple[str, int], int] = {}

    for d in discounts:
        if not d.condition_pk or not d.condition_model:
            continue
        key = (d.condition_model, d.condition_pk)
        usage_counts[key] = usage_counts.get(key, 0) + 1

    for (model_name, pk), count in usage_counts.items():
        model_cls = model_map.get(model_name)
        if model_cls and hasattr(model_cls, "times_used"):
            model_cls.objects.filter(
                pk=pk,
            ).filter(
                models.Q(limit=0) | models.Q(times_used__lte=models.F("limit") - count),
            ).update(
                times_used=models.F("times_used") + count,
            )


def get_eligible_discounts(user: object, conference: object) -> list[ConditionBase]:
    """Return all conditions the user currently qualifies for.

    Args:
        user: The authenticated user.
        conference: The conference to check conditions for.

    Returns:
        A list of condition instances the user qualifies for.
    """
    all_conditions = _gather_all_conditions(conference)
    return [c for c in all_conditions if c.evaluate(user, conference)]


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
