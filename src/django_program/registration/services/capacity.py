"""Global ticket capacity enforcement for conferences.

Provides functions to count, check, and validate total ticket sales against
a conference-level capacity limit. Add-ons are excluded from the global count
because they do not consume venue seats.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from django_program.conference.models import Conference
from django_program.registration.models import Order, OrderLineItem


def get_global_sold_count(conference: object) -> int:
    """Return the total number of tickets sold across all ticket types.

    Counts OrderLineItem quantities for ticket-type items (not add-ons) in
    orders that are PAID, PARTIALLY_REFUNDED, or PENDING with an active
    inventory hold.

    Args:
        conference: The conference to count sales for.

    Returns:
        The total number of tickets sold.
    """
    now = timezone.now()
    return (
        OrderLineItem.objects.filter(
            order__conference=conference,
            ticket_type__isnull=False,
        )
        .filter(
            models.Q(order__status__in=[Order.Status.PAID, Order.Status.PARTIALLY_REFUNDED])
            | models.Q(order__status=Order.Status.PENDING, order__hold_expires_at__gt=now),
        )
        .aggregate(total=models.Sum("quantity"))["total"]
        or 0
    )


def get_global_remaining(conference: object) -> int | None:
    """Return the number of tickets still available under the global cap.

    Args:
        conference: The conference to check capacity for.

    Returns:
        The remaining ticket count, or ``None`` if the conference has no
        global capacity limit (``total_capacity == 0``).
    """
    if conference.total_capacity == 0:
        return None
    sold = get_global_sold_count(conference)
    return conference.total_capacity - sold


def validate_global_capacity(conference: object, desired_total: int) -> None:
    """Raise ``ValidationError`` if ``desired_total`` would exceed global capacity.

    Acquires a row-level lock on the conference via ``select_for_update()`` to
    prevent race conditions when multiple concurrent requests validate capacity
    at the same time. The caller **must** already be inside a
    ``transaction.atomic`` block.

    Args:
        conference: The conference to validate against.
        desired_total: The total number of ticket items in the cart
            (across all ticket types, excluding add-ons).

    Raises:
        ValidationError: If the desired total exceeds the conference's
            ``total_capacity``.
    """
    if conference.total_capacity == 0:
        return
    Conference.objects.select_for_update().filter(pk=conference.pk).first()
    remaining = get_global_remaining(conference)
    if remaining is not None and desired_total > remaining:
        raise ValidationError(
            f"Only {remaining} tickets remaining for this conference (venue capacity: {conference.total_capacity})."
        )
