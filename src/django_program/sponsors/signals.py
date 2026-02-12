"""Auto-voucher generation signal for the sponsors app."""

from django.db.models.signals import post_save

from django_program.registration.models import Voucher
from django_program.sponsors.models import Sponsor


def generate_comp_vouchers(sender: object, instance: Sponsor, created: bool, **kwargs: object) -> None:  # noqa: ARG001, FBT001
    """Create complimentary vouchers when a new sponsor is saved.

    Generates one ``Voucher`` per complimentary ticket defined on the
    sponsor's level.  Each voucher is a single-use, 100 % comp code that
    also unlocks hidden ticket types.  ``bulk_create`` with
    ``ignore_conflicts=True`` makes the operation idempotent.

    Args:
        sender: The model class that sent the signal.
        instance: The ``Sponsor`` instance that was saved.
        created: ``True`` when the instance was just inserted.
        **kwargs: Additional keyword arguments passed by the signal.
    """
    if not created:
        return

    comp_ticket_count: int = instance.level.comp_ticket_count
    if comp_ticket_count <= 0:
        return

    vouchers = [
        Voucher(
            conference=instance.conference,
            code=f"SPONSOR-{instance.slug.upper()}-{i + 1}",
            voucher_type=Voucher.VoucherType.COMP,
            discount_value=0,
            max_uses=1,
            unlocks_hidden_tickets=True,
            is_active=True,
        )
        for i in range(comp_ticket_count)
    ]

    Voucher.objects.bulk_create(vouchers, ignore_conflicts=True)


post_save.connect(generate_comp_vouchers, sender=Sponsor)
