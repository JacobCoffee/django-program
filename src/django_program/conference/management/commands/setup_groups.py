"""Management command to create default permission groups for conference staff."""

from typing import Any

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

# Mapping of group name -> list of (app_label, codename) permissions.
# Uses the app labels defined in each app's AppConfig (program_conference, etc.).
_GROUP_PERMISSIONS: dict[str, list[tuple[str, str]]] = {
    "Program: Conference Organizers": [
        # Full access to conference and section management
        ("program_conference", "add_conference"),
        ("program_conference", "change_conference"),
        ("program_conference", "delete_conference"),
        ("program_conference", "view_conference"),
        ("program_conference", "add_section"),
        ("program_conference", "change_section"),
        ("program_conference", "delete_section"),
        ("program_conference", "view_section"),
        # Full access to ticket types and add-ons
        ("program_registration", "add_tickettype"),
        ("program_registration", "change_tickettype"),
        ("program_registration", "delete_tickettype"),
        ("program_registration", "view_tickettype"),
        ("program_registration", "add_addon"),
        ("program_registration", "change_addon"),
        ("program_registration", "delete_addon"),
        ("program_registration", "view_addon"),
        # Voucher management
        ("program_registration", "add_voucher"),
        ("program_registration", "change_voucher"),
        ("program_registration", "delete_voucher"),
        ("program_registration", "view_voucher"),
        # View orders and carts (read-only for operational awareness)
        ("program_registration", "view_order"),
        ("program_registration", "view_orderlineitem"),
        ("program_registration", "view_cart"),
        ("program_registration", "view_cartitem"),
        ("program_registration", "view_payment"),
        ("program_registration", "view_credit"),
        # Activity signup management
        ("program_programs", "manage_activity"),
    ],
    "Program: Registration & Ticket Support": [
        # View conference context
        ("program_conference", "view_conference"),
        ("program_conference", "view_section"),
        # View and manage tickets/add-ons
        ("program_registration", "view_tickettype"),
        ("program_registration", "change_tickettype"),
        ("program_registration", "view_addon"),
        ("program_registration", "change_addon"),
        # Voucher management (issue comps, apply discounts)
        ("program_registration", "add_voucher"),
        ("program_registration", "change_voucher"),
        ("program_registration", "view_voucher"),
        # Cart and order support
        ("program_registration", "view_cart"),
        ("program_registration", "view_cartitem"),
        ("program_registration", "view_order"),
        ("program_registration", "change_order"),
        ("program_registration", "view_orderlineitem"),
        ("program_registration", "view_payment"),
        ("program_registration", "view_credit"),
    ],
    "Program: Finance & Accounting": [
        # Read-only conference context
        ("program_conference", "view_conference"),
        # Full access to financial records
        ("program_registration", "view_order"),
        ("program_registration", "change_order"),
        ("program_registration", "view_orderlineitem"),
        ("program_registration", "view_payment"),
        ("program_registration", "add_payment"),
        ("program_registration", "change_payment"),
        ("program_registration", "view_credit"),
        ("program_registration", "add_credit"),
        ("program_registration", "change_credit"),
        # View vouchers for audit trail
        ("program_registration", "view_voucher"),
        # View tickets for revenue reporting
        ("program_registration", "view_tickettype"),
        ("program_registration", "view_addon"),
    ],
    "Program: Activity Organizers": [
        ("program_conference", "view_conference"),
        ("program_programs", "manage_activity"),
        ("program_programs", "view_activity"),
        ("program_programs", "view_activitysignup"),
    ],
    "Program: Read-Only Staff": [
        ("program_conference", "view_conference"),
        ("program_conference", "view_section"),
        ("program_registration", "view_tickettype"),
        ("program_registration", "view_addon"),
        ("program_registration", "view_voucher"),
        ("program_registration", "view_cart"),
        ("program_registration", "view_cartitem"),
        ("program_registration", "view_order"),
        ("program_registration", "view_orderlineitem"),
        ("program_registration", "view_payment"),
        ("program_registration", "view_credit"),
    ],
}


class Command(BaseCommand):
    """Create default permission groups for conference staff roles.

    Creates five groups with appropriate permissions:

    * **Conference Organizers** -- full conference, ticket, voucher, and activity management
    * **Registration & Ticket Support** -- ticket ops, voucher issuing, order support
    * **Finance & Accounting** -- orders, payments, credits, and revenue visibility
    * **Activity Organizers** -- per-activity signup management
    * **Read-Only Staff** -- view-only access to all registration models

    Safe to run multiple times; existing groups are updated with the defined
    permission set.
    """

    help = "Create default permission groups for conference staff roles."

    def handle(self, *args: Any, **options: Any) -> None:
        """Execute the setup_groups command.

        Args:
            *args: Positional arguments (unused).
            **options: Parsed command-line options.
        """
        for group_name, perm_specs in _GROUP_PERMISSIONS.items():
            group, created = Group.objects.get_or_create(name=group_name)
            verb = "Created" if created else "Updated"

            permissions = Permission.objects.filter(
                content_type__app_label__in={app for app, _ in perm_specs},
            )
            matched = [p for p in permissions if (p.content_type.app_label, p.codename) in perm_specs]
            group.permissions.set(matched)

            self.stdout.write(self.style.SUCCESS(f"  {verb} group '{group_name}' with {len(matched)} permissions"))

        self.stdout.write(self.style.SUCCESS("\nDone."))
