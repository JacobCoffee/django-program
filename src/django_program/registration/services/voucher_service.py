"""Voucher bulk generation service.

Provides functions for generating batches of unique, cryptographically
random voucher codes within a single database transaction.
"""

import secrets
import string
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from django.db import transaction

from django_program.registration.models import Voucher

if TYPE_CHECKING:
    import datetime
    from decimal import Decimal

    from django.db.models import QuerySet

    from django_program.conference.models import Conference
    from django_program.registration.models import AddOn, TicketType

_CODE_ALPHABET = string.ascii_uppercase + string.digits
_CODE_LENGTH = 8
_MAX_COUNT = 500


@dataclass
class VoucherBulkConfig:
    """Configuration for a bulk voucher generation request.

    Bundles all parameters needed to generate a batch of voucher codes
    into a single value object.

    Attributes:
        conference: The conference to create vouchers for.
        prefix: Fixed string prepended to each generated code.
        count: Number of voucher codes to generate (1-500).
        voucher_type: One of the ``Voucher.VoucherType`` values.
        discount_value: Percentage (0-100) or fixed amount depending on type.
        max_uses: Maximum number of times each voucher can be redeemed.
        valid_from: Optional start of the validity window.
        valid_until: Optional end of the validity window.
        unlocks_hidden_tickets: Whether the vouchers reveal hidden ticket types.
        applicable_ticket_types: Optional queryset of ticket types to restrict to.
        applicable_addons: Optional queryset of add-ons to restrict to.
    """

    conference: Conference
    prefix: str
    count: int
    voucher_type: str
    discount_value: Decimal
    max_uses: int = 1
    valid_from: datetime.datetime | None = None
    valid_until: datetime.datetime | None = None
    unlocks_hidden_tickets: bool = field(default=False)
    applicable_ticket_types: QuerySet[TicketType] | None = None
    applicable_addons: QuerySet[AddOn] | None = None


def _generate_unique_code(prefix: str, existing_codes: set[str]) -> str:
    """Generate a single voucher code that does not collide with existing ones.

    Produces codes in the format ``{prefix}{8_random_chars}`` where the random
    portion uses uppercase alphanumeric characters (A-Z, 0-9) for readability.
    Retries up to 100 times if a collision is detected.

    Args:
        prefix: The fixed prefix prepended to each code.
        existing_codes: Set of codes that already exist for uniqueness checks.

    Returns:
        A unique voucher code string.

    Raises:
        RuntimeError: If a unique code cannot be generated after 100 attempts.
    """
    for _ in range(100):
        random_part = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
        code = f"{prefix}{random_part}"
        if code not in existing_codes:
            return code
    msg = f"Failed to generate a unique voucher code with prefix '{prefix}' after 100 attempts"
    raise RuntimeError(msg)


def generate_voucher_codes(config: VoucherBulkConfig) -> list[Voucher]:
    """Generate a batch of unique voucher codes for a conference.

    Creates ``config.count`` vouchers with cryptographically random codes,
    all sharing the same configuration (type, discount, validity window, etc.).
    The vouchers are inserted in a single ``bulk_create`` call wrapped in a
    transaction for atomicity. M2M relations are set via a single
    ``bulk_create`` on the through tables to avoid N+1 queries.

    Args:
        config: Bulk generation configuration specifying the conference, prefix,
            count, discount parameters, and optional constraints.

    Returns:
        List of newly created ``Voucher`` instances.

    Raises:
        ValueError: If ``config.count`` is less than 1 or greater than 500.
        RuntimeError: If unique code generation fails after retries.
        IntegrityError: If a code collision occurs at the database level despite
            the in-memory uniqueness check (race condition safeguard).
    """
    if config.count < 1 or config.count > _MAX_COUNT:
        msg = f"count must be between 1 and {_MAX_COUNT}, got {config.count}"
        raise ValueError(msg)

    qs = Voucher.objects.filter(conference=config.conference)
    if config.prefix:
        qs = qs.filter(code__startswith=config.prefix)
    existing_codes: set[str] = set(qs.values_list("code", flat=True))

    vouchers_to_create: list[Voucher] = []
    for _ in range(config.count):
        code = _generate_unique_code(config.prefix, existing_codes)
        existing_codes.add(code)
        vouchers_to_create.append(
            Voucher(
                conference=config.conference,
                code=code,
                voucher_type=config.voucher_type,
                discount_value=config.discount_value,
                max_uses=config.max_uses,
                valid_from=config.valid_from,
                valid_until=config.valid_until,
                unlocks_hidden_tickets=config.unlocks_hidden_tickets,
            )
        )

    with transaction.atomic():
        created = Voucher.objects.bulk_create(vouchers_to_create)

        if config.applicable_ticket_types is not None and config.applicable_ticket_types.exists():
            ticket_type_ids = list(config.applicable_ticket_types.values_list("pk", flat=True))
            ThroughModel = Voucher.applicable_ticket_types.through  # noqa: N806
            through_objects = [
                ThroughModel(voucher_id=voucher.pk, tickettype_id=tt_id)
                for voucher in created
                for tt_id in ticket_type_ids
            ]
            ThroughModel.objects.bulk_create(through_objects)

        if config.applicable_addons is not None and config.applicable_addons.exists():
            addon_ids = list(config.applicable_addons.values_list("pk", flat=True))
            ThroughModel = Voucher.applicable_addons.through  # noqa: N806
            through_objects = [
                ThroughModel(voucher_id=voucher.pk, addon_id=addon_id) for voucher in created for addon_id in addon_ids
            ]
            ThroughModel.objects.bulk_create(through_objects)

    return created
