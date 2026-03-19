"""Check-in and product redemption business logic services.

Provides ``CheckInService`` for attendee check-in operations (lookup, check-in,
badge data, door checks) and ``RedemptionService`` for tracking product
redemption (tutorials, meals, events) against purchased order line items.
"""

import logging
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from django_program.registration.attendee import Attendee
from django_program.registration.checkin import CheckIn, DoorCheck, ProductRedemption
from django_program.registration.models import AddOn, OrderLineItem, TicketType

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser

    from django_program.conference.models import Conference

logger = logging.getLogger(__name__)


class CheckInService:
    """Service for attendee check-in operations at the conference venue."""

    @staticmethod
    def lookup_attendee(*, conference: Conference, access_code: str) -> Attendee:
        """Look up an attendee by access code within a conference.

        Args:
            conference: The conference to search within.
            access_code: The attendee's unique access code (from badge QR/barcode).

        Returns:
            The matched Attendee instance with user and order pre-loaded.

        Raises:
            Attendee.DoesNotExist: If no attendee matches the given code
                within the specified conference.
        """
        return (
            Attendee.objects.select_related("user", "conference", "order")
            .prefetch_related("order__line_items__ticket_type", "order__line_items__addon")
            .get(conference=conference, access_code=access_code)
        )

    @staticmethod
    def check_in(
        *,
        attendee: Attendee,
        checked_in_by: AbstractUser | None = None,
        station: str = "",
    ) -> CheckIn:
        """Record a check-in for an attendee.

        Creates a ``CheckIn`` record and updates the attendee's ``checked_in_at``
        timestamp on first check-in only. Multiple check-ins are allowed to
        support re-entry scenarios.

        Args:
            attendee: The attendee to check in.
            checked_in_by: Staff member performing the check-in.
            station: Identifier for the check-in station (e.g. "Door A").

        Returns:
            The created CheckIn record.
        """
        with transaction.atomic():
            checkin = CheckIn.objects.create(
                attendee=attendee,
                conference=attendee.conference,
                checked_in_by=checked_in_by,
                station=station,
            )
            if attendee.checked_in_at is None:
                attendee.checked_in_at = timezone.now()
                attendee.save(update_fields=["checked_in_at", "updated_at"])

        logger.info(
            "Checked in attendee %s (access_code=%s) at station '%s'",
            attendee.pk,
            attendee.access_code,
            station,
        )
        return checkin

    @staticmethod
    def get_badge_data(attendee: Attendee) -> dict[str, object]:
        """Return badge display data for a checked-in attendee.

        Args:
            attendee: The attendee to get badge data for.

        Returns:
            Dict with keys: ``name``, ``email``, ``access_code``,
            ``ticket_type``, ``checked_in``, ``first_check_in_at``,
            ``check_in_count``, ``products``.
        """
        user = attendee.user
        full_name = f"{user.first_name} {user.last_name}".strip() or str(user.username)

        ticket_type_name = "General Admission"
        products: list[dict[str, object]] = []

        if attendee.order is not None:
            for line_item in attendee.order.line_items.all():
                if line_item.ticket_type is not None:
                    ticket_type_name = str(line_item.ticket_type.name)
                if line_item.addon is not None:
                    products.append(
                        {
                            "id": line_item.addon_id,
                            "name": str(line_item.addon.name),
                            "description": str(line_item.description),
                            "quantity": line_item.quantity,
                        }
                    )

        check_in_count = CheckIn.objects.filter(attendee=attendee).count()

        return {
            "name": full_name,
            "email": str(user.email),
            "access_code": str(attendee.access_code),
            "ticket_type": ticket_type_name,
            "checked_in": attendee.checked_in_at is not None,
            "first_check_in_at": attendee.checked_in_at,
            "check_in_count": check_in_count,
            "products": products,
        }

    @staticmethod
    def record_door_check(
        *,
        attendee: Attendee,
        ticket_type: TicketType | None = None,
        addon: AddOn | None = None,
        checked_by: AbstractUser | None = None,
        station: str = "",
    ) -> DoorCheck:
        """Record a door check for per-product admission.

        Validates that exactly one of ``ticket_type`` or ``addon`` is provided,
        then creates a ``DoorCheck`` record for the sub-event admission.

        Args:
            attendee: The attendee being checked.
            ticket_type: The ticket type being checked (mutually exclusive with addon).
            addon: The add-on being checked (mutually exclusive with ticket_type).
            checked_by: Staff member performing the check.
            station: Identifier for the check station (e.g. "Tutorial Room 1").

        Returns:
            The created DoorCheck record.

        Raises:
            ValueError: If neither or both ``ticket_type`` and ``addon`` are provided.
        """
        if (ticket_type is None) == (addon is None):
            msg = "Exactly one of ticket_type or addon must be provided."
            raise ValueError(msg)

        door_check = DoorCheck.objects.create(
            attendee=attendee,
            conference=attendee.conference,
            ticket_type=ticket_type,
            addon=addon,
            checked_by=checked_by,
            station=station,
        )
        product_label = ticket_type.name if ticket_type else addon.name  # type: ignore[union-attr]
        logger.info(
            "Door check for attendee %s → %s at station '%s'",
            attendee.pk,
            product_label,
            station,
        )
        return door_check


class RedemptionService:
    """Service for product redemption (tutorials, meals, events).

    Tracks which purchased order line items have been redeemed by an attendee,
    preventing double-use of single-use products. Each line item can be redeemed
    up to its purchased ``quantity``.
    """

    @staticmethod
    def get_redeemable_products(attendee: Attendee) -> list[dict[str, object]]:
        """List products the attendee can redeem.

        Examines the attendee's order line items and checks which have not yet
        been fully redeemed based on the ``ProductRedemption`` records.

        Args:
            attendee: The attendee to check.

        Returns:
            List of dicts with keys: ``line_item_id``, ``description``,
            ``quantity``, ``redeemed_count``, ``remaining``,
            ``ticket_type_id``, ``addon_id``.
        """
        if attendee.order is None:
            return []

        line_items = (
            OrderLineItem.objects.filter(order=attendee.order)
            .annotate(
                redeemed_count=Count(
                    "redemptions",
                    filter=Q(redemptions__attendee=attendee),
                ),
            )
            .order_by("id")
        )

        results: list[dict[str, object]] = []
        for item in line_items:
            redeemed = item.redeemed_count  # type: ignore[attr-defined]
            remaining = item.quantity - redeemed
            if remaining > 0:
                results.append(
                    {
                        "line_item_id": item.pk,
                        "description": str(item.description),
                        "quantity": item.quantity,
                        "redeemed_count": redeemed,
                        "remaining": remaining,
                        "ticket_type_id": item.ticket_type_id,
                        "addon_id": item.addon_id,
                    }
                )

        return results

    @staticmethod
    def redeem_product(
        *,
        attendee: Attendee,
        order_line_item: OrderLineItem,
        redeemed_by: AbstractUser | None = None,
    ) -> ProductRedemption:
        """Redeem a purchased product for an attendee.

        Validates that the line item belongs to the attendee's order and has
        not already been fully redeemed before creating the redemption record.

        Args:
            attendee: The attendee redeeming.
            order_line_item: The line item being redeemed.
            redeemed_by: Staff member performing the redemption.

        Returns:
            The created ProductRedemption record.

        Raises:
            ValueError: If the line item does not belong to the attendee's order.
            ValueError: If the product has already been fully redeemed
                (redeemed count >= quantity).
        """
        if attendee.order_id != order_line_item.order_id:
            msg = (
                f"Line item {order_line_item.pk} belongs to order "
                f"{order_line_item.order_id}, not attendee's order "
                f"{attendee.order_id}."
            )
            raise ValueError(msg)

        redeemed_count = ProductRedemption.objects.filter(
            attendee=attendee,
            order_line_item=order_line_item,
        ).count()

        if redeemed_count >= order_line_item.quantity:
            msg = (
                f"Line item {order_line_item.pk} "
                f"('{order_line_item.description}') is fully redeemed "
                f"({redeemed_count}/{order_line_item.quantity})."
            )
            raise ValueError(msg)

        redemption = ProductRedemption.objects.create(
            attendee=attendee,
            order_line_item=order_line_item,
            conference=attendee.conference,
            redeemed_by=redeemed_by,
        )
        logger.info(
            "Redeemed line item %s ('%s') for attendee %s",
            order_line_item.pk,
            order_line_item.description,
            attendee.pk,
        )
        return redemption
