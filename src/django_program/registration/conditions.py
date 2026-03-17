"""Discount and condition engine for conference registration.

Architecture
------------
This module implements a composable condition/discount system that controls
product eligibility and automatic price reductions. It replaces symposion's
InheritanceManager-based approach with a cleaner abstract-base + concrete-model
pattern.

Design decisions:

1. **Abstract bases, concrete conditions.** ``ConditionBase`` and ``DiscountEffect``
   are abstract Django models. Each concrete condition (e.g. ``SpeakerCondition``)
   inherits both and lives in its own database table. No InheritanceManager, no
   polymorphic queries on a shared table.

2. **Evaluation via ``ConditionEvaluator`` service.** The evaluator queries each
   concrete condition table in priority order, checks ``evaluate()`` against the
   current user/conference context, then calls ``calculate_discount()`` for
   matching items. This keeps model code thin and orchestration testable.

3. **Priority-based, first-match-per-item.** Conditions are ordered by
   ``priority`` (lower = first). For each cart item, the first matching condition
   wins unless the engine is explicitly configured for stacking (future work).

4. **Condition discounts apply before voucher discounts.** The cart pricing
   pipeline applies condition-based discounts first, then voucher discounts on
   the remainder.

5. **Admin-friendly.** Each condition type has its own ModelAdmin with relevant
   filters and M2M widgets.

Condition types
~~~~~~~~~~~~~~~
- ``TimeOrStockLimitCondition`` -- active within a time window and/or stock cap.
- ``SpeakerCondition`` -- auto-applies to users linked to a Pretalx Speaker.
- ``GroupMemberCondition`` -- applies to members of specified Django auth groups.
- ``IncludedProductCondition`` -- unlocks when user has purchased enabling products.
- ``DiscountForProduct`` -- direct discount on specific products (time/stock limited).
- ``DiscountForCategory`` -- percentage discount on ticket types and/or add-ons.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from django.contrib.auth.models import Group

if TYPE_CHECKING:
    from django.conf import settings
from django.db import models
from django.utils import timezone


class ConditionBase(models.Model):
    """Abstract base for all conditions that gate product eligibility or discounts.

    Subclasses implement ``evaluate()`` to determine whether the condition is met
    for a given user in a conference context.
    """

    conference = models.ForeignKey(
        "program_conference.Conference",
        on_delete=models.CASCADE,
        related_name="%(class)s_conditions",
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(
        default=0,
        help_text="Lower values are evaluated first.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["priority", "name"]

    def __str__(self) -> str:
        return self.name

    def evaluate(self, user: settings.AUTH_USER_MODEL, conference: object) -> bool:
        """Return True if this condition is met for the given user.

        Args:
            user: The authenticated user to evaluate against.
            conference: The conference context.

        Raises:
            NotImplementedError: Subclasses must override this method.
        """
        raise NotImplementedError


def _validate_discount_value(value: Decimal) -> None:
    """Validate that discount_value is non-negative."""
    if value < 0:
        from django.core.exceptions import ValidationError  # noqa: PLC0415

        raise ValidationError("Discount value cannot be negative.")


class DiscountEffect(models.Model):
    """Abstract base for discount effects that reduce price.

    Provides the discount calculation logic shared by all condition types that
    can produce a price reduction.
    """

    class DiscountType(models.TextChoices):
        """The type of discount to apply."""

        PERCENTAGE = "percentage", "Percentage"
        FIXED_AMOUNT = "fixed_amount", "Fixed Amount"

    discount_type = models.CharField(
        max_length=20,
        choices=DiscountType.choices,
        default=DiscountType.PERCENTAGE,
    )
    discount_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Percentage (0-100) or fixed amount depending on discount_type.",
        validators=[_validate_discount_value],
    )
    max_quantity = models.PositiveIntegerField(
        default=0,
        help_text="Maximum items this discount applies to. 0 means unlimited.",
    )
    applicable_ticket_types = models.ManyToManyField(
        "program_registration.TicketType",
        blank=True,
        related_name="%(class)s_discounts",
        help_text="Ticket types this discount applies to. Empty means all.",
    )
    applicable_addons = models.ManyToManyField(
        "program_registration.AddOn",
        blank=True,
        related_name="%(class)s_discounts",
        help_text="Add-ons this discount applies to. Empty means all.",
    )

    class Meta:
        abstract = True

    def calculate_discount(self, unit_price: Decimal, quantity: int) -> Decimal:
        """Calculate the discount amount for the given price and quantity.

        Args:
            unit_price: The per-unit price of the item.
            quantity: The number of items.

        Returns:
            The total discount amount (always non-negative).
        """
        effective_qty = quantity
        if self.max_quantity > 0:
            effective_qty = min(quantity, self.max_quantity)

        line_total = unit_price * effective_qty

        if self.discount_type == self.DiscountType.PERCENTAGE:
            clamped = min(self.discount_value, Decimal(100))
            pct = clamped / Decimal(100)
            return (line_total * pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if self.discount_type == self.DiscountType.FIXED_AMOUNT:
            return min(self.discount_value * effective_qty, line_total)

        return Decimal("0.00")


def _check_time_and_stock(
    start_time: object,
    end_time: object,
    limit: int,
    times_used: int,
) -> bool:
    """Shared evaluation logic for time-window and stock-limited conditions.

    Args:
        start_time: Optional start of the validity window.
        end_time: Optional end of the validity window.
        limit: Maximum uses (0 = unlimited).
        times_used: Current usage count.

    Returns:
        True if the current time is within the window and stock remains.
    """
    now = timezone.now()
    if start_time and now < start_time:
        return False
    if end_time and now > end_time:
        return False
    return not (limit > 0 and times_used >= limit)


class TimeOrStockLimitCondition(ConditionBase, DiscountEffect):
    """Condition met when within a time window and/or stock limit.

    Use this for early-bird discounts, flash sales, or any promotion with a
    defined start/end time and optional usage cap.
    """

    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    limit = models.PositiveIntegerField(
        default=0,
        help_text="Maximum number of times this condition can be used. 0 means unlimited.",
    )
    times_used = models.PositiveIntegerField(default=0)

    class Meta(ConditionBase.Meta):
        verbose_name = "time/stock limit condition"
        verbose_name_plural = "time/stock limit conditions"

    def evaluate(self, user: settings.AUTH_USER_MODEL, conference: object) -> bool:  # noqa: ARG002
        """Return True if within the time window and stock has not been exhausted.

        Args:
            user: The authenticated user (unused for this condition type).
            conference: The conference context (unused, already filtered by FK).
        """
        return _check_time_and_stock(self.start_time, self.end_time, self.limit, self.times_used)


class SpeakerCondition(ConditionBase, DiscountEffect):
    """Auto-applies to users linked to a Pretalx Speaker.

    Checks whether the user has a Speaker record in the pretalx app for the
    same conference, optionally filtering by presenter/copresenter role.
    """

    is_presenter = models.BooleanField(
        default=True,
        help_text="Apply to primary speakers (those listed as speaker on a talk).",
    )
    is_copresenter = models.BooleanField(
        default=False,
        help_text="Apply to additional speakers / copresenters.",
    )

    class Meta(ConditionBase.Meta):
        verbose_name = "speaker condition"
        verbose_name_plural = "speaker conditions"

    def evaluate(self, user: settings.AUTH_USER_MODEL, conference: object) -> bool:  # noqa: ARG002
        """Return True if the user is linked to a Speaker for this conference.

        Pretalx has no explicit primary/copresenter role, so any linked
        speaker qualifies when either flag is set. When both flags are
        True, any speaker qualifies. When only ``is_presenter`` is True,
        any speaker on at least one talk qualifies. When only
        ``is_copresenter`` is True, the speaker must appear on a talk
        with at least one other speaker.

        Args:
            user: The authenticated user to check.
            conference: The conference context.
        """
        from django_program.pretalx.models import Speaker  # noqa: PLC0415

        speakers = Speaker.objects.filter(conference=self.conference, user=user)
        if not speakers.exists():
            return False

        if self.is_presenter:
            return True

        if self.is_copresenter:
            for speaker in speakers:
                for talk in speaker.talks.filter(conference=self.conference):
                    if talk.speakers.count() > 1:
                        return True
            return False

        return False


class GroupMemberCondition(ConditionBase, DiscountEffect):
    """Applies to members of specific Django auth groups.

    Useful for staff discounts, volunteer pricing, or any role-based
    discount controlled via Django's built-in group system.
    """

    groups = models.ManyToManyField(
        Group,
        related_name="condition_discounts",
        help_text="User must be a member of at least one of these groups.",
    )

    class Meta(ConditionBase.Meta):
        verbose_name = "group member condition"
        verbose_name_plural = "group member conditions"

    def evaluate(self, user: settings.AUTH_USER_MODEL, conference: object) -> bool:  # noqa: ARG002
        """Return True if the user belongs to at least one of the configured groups.

        Args:
            user: The authenticated user to check.
            conference: The conference context (unused, already filtered by FK).
        """
        group_ids = set(self.groups.values_list("pk", flat=True))
        if not group_ids:
            return False
        user_group_ids = set(user.groups.values_list("pk", flat=True))
        return bool(group_ids & user_group_ids)


class IncludedProductCondition(ConditionBase, DiscountEffect):
    """Unlocks discount on target products when user has purchased enabling products.

    For example, purchasing a "Tutorial" ticket could unlock a discount on
    the "Tutorial Lunch" add-on.
    """

    enabling_ticket_types = models.ManyToManyField(
        "program_registration.TicketType",
        related_name="enabling_conditions",
        help_text="User must have a paid order containing one of these ticket types.",
    )

    class Meta(ConditionBase.Meta):
        verbose_name = "included product condition"
        verbose_name_plural = "included product conditions"

    def evaluate(self, user: settings.AUTH_USER_MODEL, conference: object) -> bool:  # noqa: ARG002
        """Return True if the user has purchased at least one enabling ticket type.

        Args:
            user: The authenticated user to check.
            conference: The conference context.
        """
        enabling_ids = set(self.enabling_ticket_types.values_list("pk", flat=True))
        if not enabling_ids:
            return False

        from django_program.registration.models import Order, OrderLineItem  # noqa: PLC0415

        return OrderLineItem.objects.filter(
            order__user=user,
            order__conference=self.conference,
            order__status__in=[Order.Status.PAID, Order.Status.PARTIALLY_REFUNDED],
            ticket_type_id__in=enabling_ids,
        ).exists()


class DiscountForProduct(ConditionBase, DiscountEffect):
    """Direct discount on specific products, optionally time/stock limited.

    Unlike other conditions, this evaluates to True for all users as long as
    the time window and stock limit are satisfied. Use ``applicable_ticket_types``
    and ``applicable_addons`` to control which products receive the discount.
    """

    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    limit = models.PositiveIntegerField(
        default=0,
        help_text="Maximum number of times this discount can be used. 0 means unlimited.",
    )
    times_used = models.PositiveIntegerField(default=0)

    class Meta(ConditionBase.Meta):
        verbose_name = "product discount"
        verbose_name_plural = "product discounts"

    def evaluate(self, user: settings.AUTH_USER_MODEL, conference: object) -> bool:  # noqa: ARG002
        """Return True if within the time window and stock has not been exhausted.

        Args:
            user: The authenticated user (unused for product discounts).
            conference: The conference context (unused, already filtered by FK).
        """
        return _check_time_and_stock(self.start_time, self.end_time, self.limit, self.times_used)


class DiscountForCategory(ConditionBase):
    """Percentage discount on all products in specified categories.

    Applies a flat percentage reduction to ticket types and/or add-ons for
    the conference. Does not use ``DiscountEffect`` because it uses its own
    simplified percentage-only calculation with category-level targeting.
    """

    percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Percentage discount to apply (0-100).",
    )
    apply_to_tickets = models.BooleanField(
        default=True,
        help_text="Apply this discount to all ticket types.",
    )
    apply_to_addons = models.BooleanField(
        default=True,
        help_text="Apply this discount to all add-ons.",
    )
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    limit = models.PositiveIntegerField(
        default=0,
        help_text="Maximum number of times this discount can be used. 0 means unlimited.",
    )
    times_used = models.PositiveIntegerField(default=0)

    class Meta(ConditionBase.Meta):
        verbose_name = "category discount"
        verbose_name_plural = "category discounts"

    def evaluate(self, user: settings.AUTH_USER_MODEL, conference: object) -> bool:  # noqa: ARG002
        """Return True if within the time window and stock has not been exhausted.

        Args:
            user: The authenticated user (unused for category discounts).
            conference: The conference context (unused, already filtered by FK).
        """
        return _check_time_and_stock(self.start_time, self.end_time, self.limit, self.times_used)

    def calculate_discount(self, unit_price: Decimal, quantity: int) -> Decimal:
        """Calculate the percentage discount for the given price and quantity.

        Args:
            unit_price: The per-unit price of the item.
            quantity: The number of items.

        Returns:
            The total discount amount.
        """
        line_total = unit_price * quantity
        pct = self.percentage / Decimal(100)
        return (line_total * pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
