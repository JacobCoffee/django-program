"""Built-in management navigation for django-program.

Registers every stock sidebar section and item (the same tree the manage
dashboard has always shown).  Host projects trim or extend this tree
through ``DJANGO_PROGRAM["manage"]`` (``builtin_nav``, ``hide_nav``,
``nav``) instead of editing this module; see
:mod:`django_program.manage.nav` for the registry API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Count
from django.urls import NoReverseMatch, reverse
from django.utils.text import slugify

from django_program.manage.nav import NavContext, NavItem, NavRegistry, has_full_manage_access, manage_perm

if TYPE_CHECKING:
    from collections.abc import Iterable


def _conference_label(ctx: NavContext) -> str:
    """Return the conference name for the "Conference" section title."""
    return str(ctx.conference.name) if ctx.conference is not None else "Conference"


def _talk_type_children(ctx: NavContext) -> Iterable[NavItem]:
    """Build one child nav item per talk submission type, with counts."""
    from django_program.pretalx.models import Talk  # noqa: PLC0415

    if ctx.conference is None:
        return []
    types = (
        Talk.objects.filter(conference=ctx.conference)
        .exclude(submission_type="")
        .values("submission_type")
        .annotate(count=Count("id"))
        .order_by("submission_type")
    )
    children: list[NavItem] = []
    for row in types:
        slug = slugify(row["submission_type"])
        try:
            url = reverse(
                "manage:talk-list-by-type",
                kwargs={"conference_slug": ctx.conference.slug, "type_slug": slug},
            )
        except NoReverseMatch:
            continue
        children.append(
            NavItem(
                key=f"talks-type-{slug}",
                label=f"{row['submission_type']} ({row['count']})",
                url=url,
                active=("talks",),
            )
        )
    return children


def _override_children(ctx: NavContext) -> Iterable[NavItem]:  # noqa: ARG001
    """Build the Pretalx override sub-tabs (speakers, rooms, sponsors, type defaults)."""
    return [
        NavItem(
            key="overrides-speakers",
            label="Speakers",
            url="manage:speaker-override-list",
            conference_url=True,
            permission=manage_perm("view_overrides"),
            active=("overrides",),
        ),
        NavItem(
            key="overrides-rooms",
            label="Rooms",
            url="manage:room-override-list",
            conference_url=True,
            permission=manage_perm("view_overrides"),
            active=("overrides",),
        ),
        NavItem(
            key="overrides-sponsors",
            label="Sponsors",
            url="manage:sponsor-override-list",
            conference_url=True,
            permission=manage_perm("view_overrides"),
            feature="sponsors",
            active=("overrides",),
        ),
        NavItem(
            key="overrides-type-defaults",
            label="Type Defaults",
            url="manage:type-default-list",
            conference_url=True,
            permission=manage_perm("view_overrides"),
            active=("overrides",),
        ),
    ]


def register_builtin_nav(registry: NavRegistry) -> None:
    """Register django-program's built-in sidebar sections and items.

    Called once by :func:`django_program.manage.nav.get_registry`, before
    ``builtin_nav``/``hide_nav`` filtering and host ``nav`` hooks run.

    Args:
        registry: The registry to populate.
    """
    registry.section("conference", _conference_label, order=0)
    registry.add(
        "conference",
        NavItem(
            key="dashboard",
            label="Dashboard",
            url="manage:dashboard",
            icon="dashboard",
            conference_url=True,
            permission=manage_perm("view_dashboard"),
            order=0,
        ),
        NavItem(
            key="conference-edit",
            label="Settings",
            url="manage:conference-edit",
            icon="settings",
            conference_url=True,
            permission=manage_perm("manage_conference_settings"),
            order=10,
        ),
    )

    registry.section("program", "Program", order=10)
    registry.add(
        "program",
        NavItem(
            key="sections",
            label="Sections",
            url="manage:section-list",
            icon="sections",
            conference_url=True,
            permission=manage_perm("view_program"),
            order=0,
        ),
        NavItem(
            key="rooms",
            label="Rooms",
            url="manage:room-list",
            icon="rooms",
            conference_url=True,
            permission=manage_perm("view_program"),
            order=10,
        ),
        NavItem(
            key="speakers",
            label="Speakers",
            url="manage:speaker-list",
            icon="speakers",
            conference_url=True,
            permission=manage_perm("view_program"),
            order=20,
        ),
        NavItem(
            key="talks",
            label="Talks",
            url="manage:talk-list",
            icon="talks",
            conference_url=True,
            permission=manage_perm("view_program"),
            children=_talk_type_children,
            order=30,
        ),
        NavItem(
            key="schedule",
            label="Schedule",
            url="manage:schedule-list",
            icon="schedule",
            conference_url=True,
            permission=manage_perm("view_program"),
            order=40,
        ),
        NavItem(
            key="activities",
            label="Activities",
            url="manage:activity-list",
            icon="activities",
            conference_url=True,
            permission=manage_perm("program_programs.view_activity"),
            feature="programs",
            order=50,
        ),
        NavItem(
            key="travel-grants",
            label="Travel Grants",
            url="manage:travel-grant-list",
            icon="travel-grants",
            conference_url=True,
            permission=manage_perm("program_programs.view_travel_grant"),
            feature="travel_grants",
            order=60,
        ),
    )

    registry.section("registration", "Registration", order=20)
    registry.add(
        "registration",
        NavItem(
            key="attendees",
            label="Attendees",
            url="manage:attendee-list",
            icon="attendees",
            conference_url=True,
            permission=manage_perm("view_registration"),
            feature="registration",
            group="People",
            order=0,
        ),
        NavItem(
            key="orders",
            label="Orders",
            url="manage:order-list",
            icon="orders",
            conference_url=True,
            permission=manage_perm("view_registration"),
            feature="registration",
            group="People",
            order=10,
        ),
        NavItem(
            key="letters",
            label="Visa Letters",
            url="manage:letter-list",
            icon="letters",
            conference_url=True,
            permission=manage_perm("view_registration"),
            feature="visa_letters",
            group="People",
            order=20,
        ),
        NavItem(
            key="badges",
            label="Badges",
            url="manage:badge-list",
            icon="badges",
            conference_url=True,
            permission=manage_perm("view_badges"),
            feature="registration",
            group="People",
            order=30,
        ),
        NavItem(
            key="ticket-types",
            label="Ticket Types",
            url="manage:ticket-type-list",
            icon="ticket-types",
            conference_url=True,
            permission=manage_perm("view_commerce"),
            feature="registration",
            group="Commerce",
            order=40,
        ),
        NavItem(
            key="addons",
            label="Add-ons",
            url="manage:addon-list",
            icon="addons",
            conference_url=True,
            permission=manage_perm("view_commerce"),
            feature="registration",
            group="Commerce",
            order=50,
        ),
        NavItem(
            key="vouchers",
            label="Vouchers",
            url="manage:voucher-list",
            icon="vouchers",
            conference_url=True,
            permission=manage_perm("view_commerce"),
            feature="registration",
            group="Commerce",
            order=60,
        ),
        NavItem(
            key="conditions",
            label="Conditions",
            url="manage:condition-list",
            icon="conditions",
            conference_url=True,
            permission=manage_perm("view_commerce"),
            feature="registration",
            group="Commerce",
            order=70,
        ),
        NavItem(
            key="bulk-purchases",
            label="Bulk Purchases",
            url="manage:bulk-purchase-list",
            icon="bulk-purchases",
            conference_url=True,
            permission=manage_perm("view_bulk_purchases"),
            feature="registration",
            group="Commerce",
            order=80,
        ),
    )

    registry.section("sponsors", "Sponsors", order=30, feature="sponsors")
    registry.add(
        "sponsors",
        NavItem(
            key="sponsor-levels",
            label="Levels",
            url="manage:sponsor-level-list",
            icon="sponsor-levels",
            conference_url=True,
            permission=manage_perm("view_sponsors"),
            order=0,
        ),
        NavItem(
            key="sponsor-list",
            active=("sponsors",),
            label="Sponsors",
            url="manage:sponsor-manage-list",
            icon="sponsors",
            conference_url=True,
            permission=manage_perm("view_sponsors"),
            order=10,
        ),
    )

    registry.section("onsite", "On-site", order=40, feature="registration")
    registry.add(
        "onsite",
        NavItem(
            key="checkin",
            label="Check-in",
            url="manage:checkin-dashboard",
            icon="checkin",
            conference_url=True,
            permission=manage_perm("view_checkin"),
            order=0,
        ),
        NavItem(
            key="terminal",
            label="Terminal POS",
            url="manage:terminal-pos",
            icon="terminal",
            conference_url=True,
            permission=manage_perm("use_terminal"),
            order=10,
        ),
    )

    registry.section("finance", "Finance & Insights", order=50)
    registry.add(
        "finance",
        NavItem(
            key="financial",
            label="Financial",
            url="manage:financial-dashboard",
            icon="financial",
            conference_url=True,
            permission=manage_perm("view_finance"),
            feature="registration",
            order=0,
        ),
        NavItem(
            key="purchase-orders",
            label="Purchase Orders",
            url="manage:purchase-order-list",
            icon="purchase-orders",
            conference_url=True,
            permission=has_full_manage_access,
            feature="registration",
            order=10,
        ),
        NavItem(
            key="expenses",
            label="Expenses",
            url="manage:expense-list",
            icon="expenses",
            conference_url=True,
            permission=manage_perm("view_finance"),
            order=20,
        ),
        NavItem(
            key="analytics",
            label="Analytics",
            url="manage:analytics-dashboard",
            icon="analytics",
            conference_url=True,
            permission=manage_perm("view_reports"),
            order=30,
        ),
        NavItem(
            key="reports",
            label="Reports",
            url="manage:reports-dashboard",
            icon="reports",
            conference_url=True,
            permission=manage_perm("view_reports"),
            order=40,
        ),
    )

    registry.section("sync-overrides", "Sync & Overrides", order=100, utility=True)
    registry.add(
        "sync-overrides",
        NavItem(
            key="overrides",
            label="Overrides",
            url="manage:override-list",
            icon="overrides",
            conference_url=True,
            permission=manage_perm("view_overrides"),
            children=_override_children,
            order=0,
        ),
    )
