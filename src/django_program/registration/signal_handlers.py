"""Signal handlers for the registration app."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser

    from django_program.registration.models import Order


def create_attendee_on_order_paid(
    sender: type,  # noqa: ARG001
    *,
    order: Order,
    user: AbstractUser,
    **kwargs: object,  # noqa: ARG001
) -> None:
    """Auto-create or update an Attendee when an order is paid.

    If an attendee already exists for the (user, conference) pair, the order
    link is updated and registration is marked complete. Otherwise a new
    attendee record is created.

    Args:
        sender: The signal sender (Order class).
        order: The order that was paid.
        user: The user who owns the order.
        **kwargs: Additional signal keyword arguments (ignored).
    """
    from django_program.registration.attendee import Attendee  # noqa: PLC0415

    attendee, _created = Attendee.objects.get_or_create(
        user=user,
        conference=order.conference,
    )
    attendee.order = order
    attendee.completed_registration = True
    attendee.save(update_fields=["order", "completed_registration", "updated_at"])
