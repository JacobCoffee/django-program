"""Management command to bootstrap a conference from a TOML configuration file."""

import datetime
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from django_program.conference.models import Conference, Section
from django_program.config_loader import load_conference_config

# Keys that exist in the TOML spec but are handled by other apps in later phases.
_DEFERRED_KEYS: dict[str, str] = {
    "tickets": "registration",
    "addons": "registration",
    "sponsor_levels": "sponsors",
}

# Mapping from TOML short field names to Django model field names.
_CONFERENCE_FIELD_MAP: dict[str, str] = {
    "name": "name",
    "slug": "slug",
    "start": "start_date",
    "end": "end_date",
    "timezone": "timezone",
    "venue": "venue",
    "website_url": "website_url",
    "pretalx_event_slug": "pretalx_event_slug",
}

_SECTION_FIELD_MAP: dict[str, str] = {
    "name": "name",
    "slug": "slug",
    "start": "start_date",
    "end": "end_date",
}


def _map_fields(data: dict[str, Any], field_map: dict[str, str]) -> dict[str, Any]:
    """Map TOML config keys to Django model field names.

    Args:
        data: Raw config data with short field names.
        field_map: Mapping of config key -> model field name.

    Returns:
        Dict with model field names as keys.
    """
    result: dict[str, Any] = {}
    for config_key, model_field in field_map.items():
        if config_key in data:
            value = data[config_key]
            if isinstance(value, datetime.date):
                value = str(value)
            result[model_field] = value
    return result


class Command(BaseCommand):
    """Bootstrap a conference and its sections from a TOML configuration file.

    Parses the given TOML file, validates its structure, and creates (or
    updates) the corresponding ``Conference`` and ``Section`` database records.

    Usage::

        manage.py bootstrap --config conference.toml
        manage.py bootstrap --config conference.toml --update
        manage.py bootstrap --config conference.toml --dry-run
    """

    help = "Create or update a conference and its sections from a TOML config file."

    def add_arguments(self, parser: CommandParser) -> None:
        """Define the command-line arguments accepted by this command.

        Args:
            parser: The argument parser to configure.
        """
        parser.add_argument(
            "--config",
            required=True,
            help="Path to the conference TOML configuration file.",
        )
        parser.add_argument(
            "--update",
            action="store_true",
            default=False,
            help="Update an existing conference instead of failing on duplicate slug.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Validate the config and print what would be created without saving.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Execute the bootstrap command.

        Args:
            *args: Positional arguments (unused).
            **options: Parsed command-line options.
        """
        config_path: str = options["config"]
        update: bool = options["update"]
        dry_run: bool = options["dry_run"]
        verbosity: int = options["verbosity"]

        try:
            conf = load_conference_config(config_path)
        except (FileNotFoundError, TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        self._warn_deferred_keys(conf)
        sections_data: list[dict[str, Any]] = conf["sections"]
        if dry_run:
            self._print_dry_run(conf, sections_data)
            return

        with transaction.atomic():
            conference = self._bootstrap_conference(conf, update=update)
            created_sections, updated_sections = self._bootstrap_sections(conference, sections_data, update=update)

        self._print_summary(conference, created_sections, updated_sections, verbosity)

    def _warn_deferred_keys(self, conf: dict[str, Any]) -> None:
        """Print info messages for config keys that are not handled in this phase.

        Args:
            conf: The parsed conference configuration.
        """
        for key, app_name in _DEFERRED_KEYS.items():
            if key in conf:
                self.stdout.write(self.style.NOTICE(f"  Skipping '{key}' -- will be handled by the {app_name} app."))

    def _bootstrap_conference(self, conf: dict[str, Any], *, update: bool) -> Conference:
        """Create or update a Conference record from the parsed config.

        Args:
            conf: The ``conference`` table from the TOML file.
            update: When ``True``, update the existing conference matched by
                slug instead of raising an error on duplicates.

        Returns:
            The created or updated ``Conference`` instance.

        Raises:
            CommandError: If a conference with the same slug already exists and
                ``update`` is ``False``.
        """
        slug = conf["slug"]
        fields = _map_fields(conf, _CONFERENCE_FIELD_MAP)
        fields.pop("slug", None)

        existing = Conference.objects.filter(slug=slug).first()
        if existing and not update:
            raise CommandError(f"Conference with slug '{slug}' already exists. Use --update to update it.")

        if existing and update:
            for attr, value in fields.items():
                setattr(existing, attr, value)
            existing.save()
            self.stdout.write(self.style.SUCCESS(f"  Updated conference: {existing.name}"))
            return existing

        conference = Conference.objects.create(slug=slug, **fields)
        self.stdout.write(self.style.SUCCESS(f"  Created conference: {conference.name}"))
        return conference

    def _bootstrap_sections(
        self,
        conference: Conference,
        sections_data: list[dict[str, Any]],
        *,
        update: bool,
    ) -> tuple[list[Section], list[Section]]:
        """Create or update Section records for a conference.

        Args:
            conference: The parent ``Conference`` instance.
            sections_data: List of section mappings from the config file.
            update: When ``True``, update existing sections matched by
                conference + slug instead of creating duplicates.

        Returns:
            A tuple of (created_sections, updated_sections).
        """
        created: list[Section] = []
        updated: list[Section] = []

        for position, section_data in enumerate(sections_data):
            slug = section_data["slug"]
            fields = _map_fields(section_data, _SECTION_FIELD_MAP)
            fields.pop("slug", None)

            if "order" not in fields:
                fields["order"] = position

            existing = Section.objects.filter(conference=conference, slug=slug).first()
            if existing and update:
                for attr, value in fields.items():
                    setattr(existing, attr, value)
                existing.save()
                self.stdout.write(self.style.SUCCESS(f"  Updated section: {existing.name}"))
                updated.append(existing)
            elif existing:
                self.stdout.write(
                    self.style.WARNING(f"  Section '{slug}' already exists for this conference, skipping.")
                )
            else:
                section = Section.objects.create(conference=conference, slug=slug, **fields)
                self.stdout.write(self.style.SUCCESS(f"  Created section: {section.name}"))
                created.append(section)

        return created, updated

    def _print_dry_run(self, conf: dict[str, Any], sections_data: list[dict[str, Any]]) -> None:
        """Print a preview of what would be created without touching the database.

        Args:
            conf: The ``conference`` table from the TOML file.
            sections_data: List of section mappings from the config file.
        """
        self.stdout.write(self.style.MIGRATE_HEADING("\n[DRY RUN] No database changes will be made.\n"))
        self.stdout.write(self.style.MIGRATE_HEADING("Conference:"))
        self.stdout.write(f"  Name:       {conf['name']}")
        self.stdout.write(f"  Slug:       {conf['slug']}")
        self.stdout.write(f"  Dates:      {conf['start']} -- {conf['end']}")
        self.stdout.write(f"  Timezone:   {conf['timezone']}")

        if conf.get("venue"):
            self.stdout.write(f"  Venue:      {conf['venue']}")
        if conf.get("website_url"):
            self.stdout.write(f"  Website:    {conf['website_url']}")

        self.stdout.write(self.style.MIGRATE_HEADING(f"\nSections ({len(sections_data)}):"))
        for idx, section in enumerate(sections_data):
            self.stdout.write(f"  [{idx}] {section['name']} ({section['slug']}) {section['start']} -- {section['end']}")

        self.stdout.write("")

    def _print_summary(
        self,
        conference: Conference,
        created_sections: list[Section],
        updated_sections: list[Section],
        verbosity: int,
    ) -> None:
        """Print a summary of all bootstrap operations performed.

        Args:
            conference: The bootstrapped ``Conference`` instance.
            created_sections: Sections that were newly created.
            updated_sections: Sections that were updated.
            verbosity: The verbosity level from the command options.
        """
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Bootstrap summary:"))
        self.stdout.write(f"  Conference:        {conference.name} ({conference.slug})")
        self.stdout.write(f"  Sections created:  {len(created_sections)}")
        self.stdout.write(f"  Sections updated:  {len(updated_sections)}")

        if verbosity >= 2:
            for section in created_sections:
                self.stdout.write(f"    + {section.name} ({section.slug})")
            for section in updated_sections:
                self.stdout.write(f"    ~ {section.name} ({section.slug})")

        self.stdout.write(self.style.SUCCESS("\nDone."))
