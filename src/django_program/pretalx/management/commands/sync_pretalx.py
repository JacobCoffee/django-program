"""Management command to sync speakers, talks, and schedule from Pretalx.

Usage::

    # Sync everything for a conference
    manage.py sync_pretalx --conference pycon-us-2026

    # Sync only speakers
    manage.py sync_pretalx --conference pycon-us-2026 --speakers

    # Sync talks and schedule
    manage.py sync_pretalx --conference pycon-us-2026 --talks --schedule
"""

from typing import TYPE_CHECKING

from django.core.management.base import BaseCommand, CommandError

from django_program.conference.models import Conference
from django_program.pretalx.sync import PretalxSyncService

if TYPE_CHECKING:
    import argparse


class Command(BaseCommand):
    """Sync speakers, talks, and schedule from Pretalx API."""

    help = "Sync speakers, talks, and schedule from Pretalx API"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Register command-line arguments.

        Args:
            parser: The argument parser to add arguments to.
        """
        parser.add_argument(
            "--conference",
            required=True,
            help="Conference slug to sync.",
        )
        parser.add_argument(
            "--rooms",
            action="store_true",
            default=False,
            help="Sync rooms only.",
        )
        parser.add_argument(
            "--speakers",
            action="store_true",
            default=False,
            help="Sync speakers only.",
        )
        parser.add_argument(
            "--talks",
            action="store_true",
            default=False,
            help="Sync talks only.",
        )
        parser.add_argument(
            "--schedule",
            action="store_true",
            default=False,
            help="Sync schedule only.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            default=False,
            dest="sync_all",
            help="Sync everything (default if no specific flag given).",
        )
        parser.add_argument(
            "--allow-large-schedule-drop",
            action="store_true",
            default=False,
            help=(
                "Allow schedule sync to remove a large fraction of existing "
                "slots. Use only when a major schedule reduction is intentional."
            ),
        )

    def handle(self, **options: object) -> None:
        """Execute the sync command.

        Looks up the conference, validates its Pretalx configuration, and runs
        the requested sync operations.  When no specific flags are given,
        defaults to syncing everything.
        """
        conference_slug: str = str(options["conference"])

        try:
            conference = Conference.objects.get(slug=conference_slug)
        except Conference.DoesNotExist:
            msg = f"Conference with slug '{conference_slug}' not found"
            raise CommandError(msg) from None

        if not conference.pretalx_event_slug:
            msg = f"Conference '{conference_slug}' has no pretalx_event_slug configured"
            raise CommandError(msg)

        service = PretalxSyncService(conference)

        sync_rooms: bool = bool(options["rooms"])
        sync_speakers: bool = bool(options["speakers"])
        sync_talks: bool = bool(options["talks"])
        sync_schedule: bool = bool(options["schedule"])
        sync_all: bool = bool(options["sync_all"])
        allow_large_schedule_drop: bool = bool(options["allow_large_schedule_drop"])
        no_specific_flag = not (sync_rooms or sync_speakers or sync_talks or sync_schedule)

        if sync_all or no_specific_flag:
            results = service.sync_all(allow_large_deletions=allow_large_schedule_drop)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Synced {results['rooms']} rooms, "
                    f"{results['speakers']} speakers, "
                    f"{results['talks']} talks, "
                    f"{results['schedule_slots']} schedule slots"
                )
            )
            return

        if sync_rooms:
            count = service.sync_rooms()
            self.stdout.write(self.style.SUCCESS(f"Synced {count} rooms"))

        if sync_speakers:
            count = service.sync_speakers()
            self.stdout.write(self.style.SUCCESS(f"Synced {count} speakers"))

        if sync_talks:
            count = service.sync_talks()
            self.stdout.write(self.style.SUCCESS(f"Synced {count} talks"))

        if sync_schedule:
            count, unscheduled = service.sync_schedule(allow_large_deletions=allow_large_schedule_drop)
            msg = f"Synced {count} schedule slots"
            if unscheduled:
                msg += f" ({unscheduled} unscheduled)"
            self.stdout.write(self.style.SUCCESS(msg))
