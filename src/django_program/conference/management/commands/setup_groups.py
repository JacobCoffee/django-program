"""Management command to create default permission groups for conference staff."""

from typing import Any

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

# All custom Conference permissions for granting to the organizer group.
_ALL_CONFERENCE_PERMS = [
    "view_dashboard",
    "manage_conference_settings",
    "view_program",
    "change_program",
    "view_registration",
    "change_registration",
    "view_commerce",
    "change_commerce",
    "view_badges",
    "change_badges",
    "view_sponsors",
    "change_sponsors",
    "view_bulk_purchases",
    "change_bulk_purchases",
    "view_finance",
    "change_finance",
    "view_reports",
    "export_reports",
    "view_checkin",
    "use_terminal",
    "view_overrides",
    "change_overrides",
]

_ALL_VIEW_CONFERENCE_PERMS = [
    p for p in _ALL_CONFERENCE_PERMS if (p.startswith("view_") or p == "export_reports") and p != "view_checkin"
]

# Mapping of group name -> list of (app_label, codename) permissions.
_GROUP_PERMISSIONS: dict[str, list[tuple[str, str]]] = {
    "Conference Organizer": [
        # Django CRUD on Conference model
        ("program_conference", "add_conference"),
        ("program_conference", "change_conference"),
        ("program_conference", "delete_conference"),
        ("program_conference", "view_conference"),
        # All custom Conference permissions
        *[("program_conference", p) for p in _ALL_CONFERENCE_PERMS],
        # Programs app
        ("program_programs", "view_activity"),
        ("program_programs", "manage_activity"),
        ("program_programs", "view_travel_grant"),
        ("program_programs", "review_travel_grant"),
        ("program_programs", "disburse_travel_grant"),
        ("program_programs", "review_receipt"),
    ],
    "Program Committee": [
        ("program_conference", "view_conference"),
        ("program_conference", "view_dashboard"),
        ("program_conference", "view_program"),
        ("program_conference", "change_program"),
        ("program_conference", "view_overrides"),
        ("program_conference", "change_overrides"),
    ],
    "Registration Manager": [
        ("program_conference", "view_conference"),
        ("program_conference", "view_dashboard"),
        ("program_conference", "view_registration"),
        ("program_conference", "change_registration"),
        ("program_conference", "view_commerce"),
        ("program_conference", "change_commerce"),
        ("program_conference", "view_badges"),
        ("program_conference", "change_badges"),
        ("program_conference", "view_checkin"),
        ("program_conference", "use_terminal"),
        ("program_conference", "view_bulk_purchases"),
        ("program_conference", "change_bulk_purchases"),
    ],
    "Finance Team": [
        ("program_conference", "view_conference"),
        ("program_conference", "view_dashboard"),
        ("program_conference", "view_finance"),
        ("program_conference", "change_finance"),
        ("program_conference", "view_reports"),
        ("program_conference", "export_reports"),
        ("program_conference", "view_registration"),
        ("program_conference", "view_commerce"),
    ],
    "Travel Grant Reviewer": [
        ("program_conference", "view_conference"),
        ("program_conference", "view_dashboard"),
        ("program_programs", "view_travel_grant"),
        ("program_programs", "review_travel_grant"),
        ("program_programs", "review_receipt"),
    ],
    "Sponsor Manager": [
        ("program_conference", "view_conference"),
        ("program_conference", "view_dashboard"),
        ("program_conference", "view_sponsors"),
        ("program_conference", "change_sponsors"),
        ("program_conference", "view_bulk_purchases"),
        ("program_conference", "change_bulk_purchases"),
    ],
    "Check-in Staff": [
        ("program_conference", "view_conference"),
        ("program_conference", "view_dashboard"),
        ("program_conference", "view_checkin"),
    ],
    "Activity Organizer": [
        ("program_conference", "view_conference"),
        ("program_conference", "view_dashboard"),
        ("program_programs", "view_activity"),
        ("program_programs", "manage_activity"),
    ],
    "Reports Viewer": [
        ("program_conference", "view_conference"),
        ("program_conference", "view_dashboard"),
        ("program_conference", "view_reports"),
    ],
    "Read-Only Staff": [
        ("program_conference", "view_conference"),
        *[("program_conference", p) for p in _ALL_VIEW_CONFERENCE_PERMS],
        ("program_programs", "view_activity"),
        ("program_programs", "view_travel_grant"),
    ],
}


class Command(BaseCommand):
    """Create default permission groups for conference staff roles.

    Creates ten groups with granular permissions:

    * **Conference Organizer** -- full access to all conference management
    * **Program Committee** -- program content and Pretalx overrides
    * **Registration Manager** -- attendees, orders, commerce, badges, check-in
    * **Finance Team** -- financial dashboard, expenses, reports, read-only commerce
    * **Travel Grant Reviewer** -- travel grant review and receipt approval
    * **Sponsor Manager** -- sponsor and bulk purchase management
    * **Check-in Staff** -- check-in dashboard access only
    * **Activity Organizer** -- activity and signup management
    * **Reports Viewer** -- read-only access to reports dashboard
    * **Read-Only Staff** -- view-only access to all sections

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
        verbosity = options.get("verbosity", 1)

        for group_name, perm_specs in _GROUP_PERMISSIONS.items():
            group, created = Group.objects.get_or_create(name=group_name)
            verb = "Created" if created else "Updated"

            perm_set = set(perm_specs)
            app_labels = {app for app, _ in perm_set}
            permissions = Permission.objects.filter(
                content_type__app_label__in=app_labels,
            )
            matched = [p for p in permissions if (p.content_type.app_label, p.codename) in perm_set]
            group.permissions.set(matched)

            if verbosity > 0:
                self.stdout.write(self.style.SUCCESS(f"  {verb} group '{group_name}' with {len(matched)} permissions"))

        if verbosity > 0:
            self.stdout.write(self.style.SUCCESS("\nDone."))
