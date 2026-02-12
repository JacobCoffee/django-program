"""Management command to sync sponsors from the PSF sponsorship API.

Usage::

    # Sync sponsors for a PyCon US conference
    manage.py sync_sponsors --conference pycon-us-2027
"""

from typing import TYPE_CHECKING

from django.core.management.base import BaseCommand, CommandError

from django_program.conference.models import Conference
from django_program.sponsors.sync import SponsorSyncService

if TYPE_CHECKING:
    import argparse


class Command(BaseCommand):
    """Sync sponsors from the PSF sponsorship API."""

    help = "Sync sponsors from the PSF sponsorship API for PyCon US conferences"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Register command-line arguments.

        Args:
            parser: The argument parser to add arguments to.
        """
        parser.add_argument(
            "--conference",
            required=True,
            help="Conference slug to sync sponsors for.",
        )

    def handle(self, **options: object) -> None:
        """Execute the sponsor sync command."""
        conference_slug = str(options["conference"])

        try:
            conference = Conference.objects.get(slug=conference_slug)
        except Conference.DoesNotExist:
            msg = f"Conference with slug '{conference_slug}' not found"
            raise CommandError(msg) from None

        try:
            service = SponsorSyncService(conference)
        except ValueError as exc:
            raise CommandError(str(exc)) from None

        try:
            results = service.sync_all()
        except RuntimeError as exc:
            raise CommandError(str(exc)) from None

        self.stdout.write(self.style.SUCCESS(f"Synced {results['sponsors']} sponsors"))
