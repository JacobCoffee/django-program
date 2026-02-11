"""Management command to bootstrap a conference from a TOML configuration file."""

import secrets
import string
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from django_program.conference.models import Conference, Section
from django_program.config_loader import load_conference_config
from django_program.registration.models import (
    AddOn,
    Cart,
    CartItem,
    Credit,
    Order,
    OrderLineItem,
    Payment,
    TicketType,
    Voucher,
)

# Keys that exist in the TOML spec but are handled by other apps in later phases.
_DEFERRED_KEYS: dict[str, str] = {
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
    "order": "order",
}

_TICKET_FIELD_MAP: dict[str, str] = {
    "name": "name",
    "slug": "slug",
    "price": "price",
    "quantity": "total_quantity",
    "per_user": "limit_per_user",
    "voucher_required": "requires_voucher",
}

_ADDON_FIELD_MAP: dict[str, str] = {
    "name": "name",
    "slug": "slug",
    "price": "price",
    "quantity": "total_quantity",
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
            result[model_field] = data[config_key]
    return result


def _parse_availability(data: dict[str, Any], tz_name: str) -> dict[str, datetime | None]:
    """Extract available_from/available_until from a TOML ``available`` sub-table.

    Args:
        data: A single ticket/addon mapping from the TOML config.
        tz_name: The conference timezone name for making datetimes aware.

    Returns:
        Dict with ``available_from`` and ``available_until`` keys (or empty).
    """
    avail = data.get("available")
    if not avail or not isinstance(avail, dict):
        return {}
    tz = ZoneInfo(tz_name)
    result: dict[str, datetime | None] = {}
    if "opens" in avail:
        result["available_from"] = datetime.combine(avail["opens"], datetime.min.time(), tzinfo=tz)
    if "closes" in avail:
        result["available_until"] = datetime.combine(
            avail["closes"], datetime.max.time().replace(microsecond=0), tzinfo=tz
        )
    return result


class Command(BaseCommand):
    """Bootstrap a conference from a TOML configuration file.

    Parses the given TOML file, validates its structure, and creates (or
    updates) the corresponding ``Conference``, ``Section``, ``TicketType``,
    and ``AddOn`` database records.

    Usage::

        manage.py bootstrap_conference --config conference.toml
        manage.py bootstrap_conference --config conference.toml --update
        manage.py bootstrap_conference --config conference.toml --dry-run
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
        parser.add_argument(
            "--seed-demo",
            action="store_true",
            default=False,
            help="Generate sample vouchers, demo users, carts, orders, payments, and credits.",
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
        seed_demo: bool = options["seed_demo"]
        verbosity: int = options["verbosity"]

        try:
            conf = load_conference_config(config_path)
        except (FileNotFoundError, TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        self._warn_deferred_keys(conf)
        sections_data: list[dict[str, Any]] = conf["sections"]
        tickets_data: list[dict[str, Any]] = conf.get("tickets", [])
        addons_data: list[dict[str, Any]] = conf.get("addons", [])

        if dry_run:
            self._print_dry_run(conf, sections_data, tickets_data, addons_data)
            return

        with transaction.atomic():
            conference = self._bootstrap_conference(conf, update=update)
            created_sections, updated_sections = self._bootstrap_sections(conference, sections_data, update=update)
            created_tickets, updated_tickets = self._bootstrap_tickets(
                conference,
                tickets_data,
                conf.get("timezone", "UTC"),
                update=update,
            )
            created_addons, updated_addons = self._bootstrap_addons(
                conference,
                addons_data,
                conf.get("timezone", "UTC"),
                update=update,
            )

        results = {
            "sections": (created_sections, updated_sections),
            "tickets": (created_tickets, updated_tickets),
            "addons": (created_addons, updated_addons),
        }
        self._print_summary(conference, results, verbosity)

        if seed_demo:
            self._seed_demo_data(conference)

    def _warn_deferred_keys(self, conf: dict[str, Any]) -> None:
        """Print info messages for config keys that are not handled yet.

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

    def _bootstrap_tickets(
        self,
        conference: Conference,
        tickets_data: list[dict[str, Any]],
        tz_name: str,
        *,
        update: bool,
    ) -> tuple[list[TicketType], list[TicketType]]:
        """Create or update TicketType records for a conference.

        Args:
            conference: The parent ``Conference`` instance.
            tickets_data: List of ticket mappings from the config file.
            tz_name: Conference timezone for date-to-datetime conversion.
            update: When ``True``, update existing tickets matched by
                conference + slug instead of creating duplicates.

        Returns:
            A tuple of (created_tickets, updated_tickets).
        """
        created: list[TicketType] = []
        updated_list: list[TicketType] = []

        for position, ticket_data in enumerate(tickets_data):
            slug = ticket_data["slug"]
            fields = _map_fields(ticket_data, _TICKET_FIELD_MAP)
            fields.pop("slug", None)
            fields["order"] = position
            fields.update(_parse_availability(ticket_data, tz_name))

            existing = TicketType.objects.filter(conference=conference, slug=slug).first()
            if existing and update:
                for attr, value in fields.items():
                    setattr(existing, attr, value)
                existing.save()
                self.stdout.write(self.style.SUCCESS(f"  Updated ticket: {existing.name}"))
                updated_list.append(existing)
            elif existing:
                self.stdout.write(
                    self.style.WARNING(f"  Ticket '{slug}' already exists for this conference, skipping.")
                )
            else:
                ticket = TicketType.objects.create(conference=conference, slug=slug, **fields)
                self.stdout.write(self.style.SUCCESS(f"  Created ticket: {ticket.name}"))
                created.append(ticket)

        return created, updated_list

    def _bootstrap_addons(
        self,
        conference: Conference,
        addons_data: list[dict[str, Any]],
        tz_name: str,
        *,
        update: bool,
    ) -> tuple[list[AddOn], list[AddOn]]:
        """Create or update AddOn records for a conference.

        Args:
            conference: The parent ``Conference`` instance.
            addons_data: List of add-on mappings from the config file.
            tz_name: Conference timezone for date-to-datetime conversion.
            update: When ``True``, update existing add-ons matched by
                conference + slug instead of creating duplicates.

        Returns:
            A tuple of (created_addons, updated_addons).
        """
        created: list[AddOn] = []
        updated_list: list[AddOn] = []

        for position, addon_data in enumerate(addons_data):
            slug = addon_data["slug"]
            fields = _map_fields(addon_data, _ADDON_FIELD_MAP)
            fields.pop("slug", None)
            fields["order"] = position
            fields.update(_parse_availability(addon_data, tz_name))

            existing = AddOn.objects.filter(conference=conference, slug=slug).first()
            if existing and update:
                for attr, value in fields.items():
                    setattr(existing, attr, value)
                existing.save()
                self.stdout.write(self.style.SUCCESS(f"  Updated add-on: {existing.name}"))
                updated_list.append(existing)
            elif existing:
                self.stdout.write(
                    self.style.WARNING(f"  Add-on '{slug}' already exists for this conference, skipping.")
                )
            else:
                addon = AddOn.objects.create(conference=conference, slug=slug, **fields)
                self.stdout.write(self.style.SUCCESS(f"  Created add-on: {addon.name}"))
                created.append(addon)

            # Wire up the requires_ticket_types M2M from the "requires" list of slugs
            requires_slugs = addon_data.get("requires")
            if requires_slugs is not None:
                target = existing if existing and update else (addon if not existing else None)
                if target:
                    found_ticket_types = TicketType.objects.filter(conference=conference, slug__in=requires_slugs)
                    found_slugs = set(found_ticket_types.values_list("slug", flat=True))
                    missing_slugs = sorted(set(requires_slugs) - found_slugs)
                    if missing_slugs:
                        missing = ", ".join(missing_slugs)
                        msg = f"Add-on '{slug}' references unknown required ticket slug(s): {missing}"
                        raise CommandError(msg)
                    target.requires_ticket_types.set(found_ticket_types)

        return created, updated_list

    def _print_dry_run(
        self,
        conf: dict[str, Any],
        sections_data: list[dict[str, Any]],
        tickets_data: list[dict[str, Any]],
        addons_data: list[dict[str, Any]],
    ) -> None:
        """Print a preview of what would be created without touching the database.

        Args:
            conf: The ``conference`` table from the TOML file.
            sections_data: List of section mappings from the config file.
            tickets_data: List of ticket mappings from the config file.
            addons_data: List of add-on mappings from the config file.
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

        if tickets_data:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\nTickets ({len(tickets_data)}):"))
            for idx, ticket in enumerate(tickets_data):
                self.stdout.write(f"  [{idx}] {ticket['name']} ({ticket['slug']}) ${ticket['price']}")

        if addons_data:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\nAdd-ons ({len(addons_data)}):"))
            for idx, addon in enumerate(addons_data):
                self.stdout.write(f"  [{idx}] {addon['name']} ({addon['slug']}) ${addon['price']}")

        self.stdout.write("")

    def _print_summary(
        self,
        conference: Conference,
        results: dict[str, tuple[list[Any], list[Any]]],
        verbosity: int,
    ) -> None:
        """Print a summary of all bootstrap operations performed.

        Args:
            conference: The bootstrapped ``Conference`` instance.
            results: Mapping of category name to (created, updated) lists.
            verbosity: The verbosity level from the command options.
        """
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Bootstrap summary:"))
        self.stdout.write(f"  Conference:        {conference.name} ({conference.slug})")
        for label, (created, updated) in results.items():
            self.stdout.write(f"  {label.capitalize()} created:  {len(created)}")
            self.stdout.write(f"  {label.capitalize()} updated:  {len(updated)}")

        if verbosity >= 2:
            for created, updated in results.values():
                for item in created:
                    self.stdout.write(f"    + {item.name} ({item.slug})")
                for item in updated:
                    self.stdout.write(f"    ~ {item.name} ({item.slug})")

        self.stdout.write(self.style.SUCCESS("\nDone."))

    # ------------------------------------------------------------------
    # --seed-demo: generate vouchers, demo users, and transactional data
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_voucher_code(prefix: str = "", length: int = 8) -> str:
        """Generate a random voucher code.

        Args:
            prefix: Optional prefix (e.g. ``"SPKR-"``).
            length: Number of random alphanumeric characters.

        Returns:
            A code like ``"SPKR-A3K9M2X1"``.
        """
        chars = string.ascii_uppercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(length))
        return f"{prefix}{random_part}" if prefix else random_part

    def _seed_demo_data(self, conference: Conference) -> None:
        """Create sample vouchers, demo users, and transactional records.

        Args:
            conference: The conference to seed data for.
        """
        self.stdout.write(self.style.MIGRATE_HEADING("\nSeeding demo data..."))

        ticket_types = {tt.slug: tt for tt in TicketType.objects.filter(conference=conference)}
        addons = {a.slug: a for a in AddOn.objects.filter(conference=conference)}
        individual = ticket_types.get("individual")
        corporate = ticket_types.get("corporate")
        tshirt = addons.get("pycon-t-shirt")

        # -- Vouchers --
        vouchers = self._seed_vouchers(conference, ticket_types)

        # -- Demo users --
        demo_users = self._seed_demo_users()

        # -- Orders (paid) --
        if individual and demo_users:
            self._seed_orders(conference, demo_users, individual, corporate, tshirt)

        # -- Active cart --
        if individual and demo_users:
            self._seed_carts(conference, demo_users, individual, tshirt)

        # -- Credits --
        if demo_users:
            self._seed_credits(conference, demo_users)

        self.stdout.write(self.style.SUCCESS("\nDemo data seeded."))

        # Print voucher codes so the dev can use them
        if vouchers:
            self.stdout.write(self.style.MIGRATE_HEADING("\nGenerated voucher codes:"))
            for v in vouchers:
                self.stdout.write(f"  {v.code:<20} {v.get_voucher_type_display():<30} (max uses: {v.max_uses})")

    def _seed_vouchers(
        self,
        conference: Conference,
        ticket_types: dict[str, TicketType],
    ) -> list[Voucher]:
        """Create sample vouchers with random codes.

        Args:
            conference: The conference to create vouchers for.
            ticket_types: Mapping of slug to TicketType for M2M wiring.

        Returns:
            List of created Voucher instances.
        """
        if Voucher.objects.filter(conference=conference).exists():
            self.stdout.write(self.style.WARNING("  Vouchers already exist, skipping."))
            return []

        speaker_tt = ticket_types.get("speaker")
        student_tt = ticket_types.get("student")

        voucher_specs: list[dict[str, Any]] = [
            {
                "code": self._generate_voucher_code("SPKR-"),
                "voucher_type": Voucher.VoucherType.COMP,
                "discount_value": Decimal(0),
                "max_uses": 200,
                "unlocks_hidden_tickets": True,
                "applicable_tickets": [speaker_tt] if speaker_tt else [],
            },
            {
                "code": self._generate_voucher_code("STU-"),
                "voucher_type": Voucher.VoucherType.COMP,
                "discount_value": Decimal(0),
                "max_uses": 500,
                "unlocks_hidden_tickets": True,
                "applicable_tickets": [student_tt] if student_tt else [],
            },
            {
                "code": self._generate_voucher_code("EARLY-"),
                "voucher_type": Voucher.VoucherType.PERCENTAGE,
                "discount_value": Decimal(20),
                "max_uses": 100,
                "unlocks_hidden_tickets": False,
                "applicable_tickets": [],
            },
            {
                "code": self._generate_voucher_code("SAVE25-"),
                "voucher_type": Voucher.VoucherType.FIXED_AMOUNT,
                "discount_value": Decimal(25),
                "max_uses": 50,
                "unlocks_hidden_tickets": False,
                "applicable_tickets": [],
            },
        ]

        created: list[Voucher] = []
        for spec in voucher_specs:
            applicable = spec.pop("applicable_tickets")
            voucher = Voucher.objects.create(conference=conference, **spec)
            if applicable:
                voucher.applicable_ticket_types.set(applicable)
            self.stdout.write(self.style.SUCCESS(f"  Created voucher: {voucher.code}"))
            created.append(voucher)

        return created

    def _seed_demo_users(self) -> list[Any]:
        """Create demo users for transactional data.

        Returns:
            List of created/existing User instances.
        """
        User = get_user_model()
        demo_specs = [
            {"username": "attendee_alice", "email": "alice@example.com", "first_name": "Alice", "last_name": "Smith"},
            {"username": "attendee_bob", "email": "bob@example.com", "first_name": "Bob", "last_name": "Jones"},
            {"username": "speaker_carol", "email": "carol@example.com", "first_name": "Carol", "last_name": "Chen"},
        ]
        users = []
        for spec in demo_specs:
            user, created = User.objects.get_or_create(username=spec["username"], defaults=spec)
            if created:
                user.set_password("demo")
                user.is_staff = True
                user.save()
                self.stdout.write(self.style.SUCCESS(f"  Created user: {user.username}"))
            users.append(user)
        return users

    def _seed_orders(
        self,
        conference: Conference,
        users: list[Any],
        individual: TicketType,
        corporate: TicketType | None,
        tshirt: AddOn | None,
    ) -> None:
        """Create sample orders with line items and payments.

        Args:
            conference: The conference for the orders.
            users: Demo users to create orders for.
            individual: The individual ticket type.
            corporate: The corporate ticket type (optional).
            tshirt: The t-shirt add-on (optional).
        """
        if Order.objects.filter(conference=conference).exists():
            self.stdout.write(self.style.WARNING("  Orders already exist, skipping."))
            return

        alice, bob, carol = users[0], users[1], users[2]

        # Alice: paid individual + t-shirt
        alice_total = individual.price + (tshirt.price if tshirt else Decimal(0))
        order1 = Order.objects.create(
            conference=conference,
            user=alice,
            status=Order.Status.PAID,
            subtotal=alice_total,
            total=alice_total,
            billing_name="Alice Smith",
            billing_email="alice@example.com",
            reference=f"ORD-{self._generate_voucher_code(length=6)}",
        )
        OrderLineItem.objects.create(
            order=order1,
            description=f"Ticket: {individual.name}",
            quantity=1,
            unit_price=individual.price,
            line_total=individual.price,
            ticket_type=individual,
        )
        if tshirt:
            OrderLineItem.objects.create(
                order=order1,
                description=f"Add-on: {tshirt.name}",
                quantity=1,
                unit_price=tshirt.price,
                line_total=tshirt.price,
                addon=tshirt,
            )
        Payment.objects.create(
            order=order1,
            method=Payment.Method.STRIPE,
            amount=alice_total,
            stripe_payment_intent_id=f"pi_demo_{secrets.token_hex(8)}",
            reference=f"ch_demo_{secrets.token_hex(8)}",
        )
        self.stdout.write(self.style.SUCCESS(f"  Created order: {order1.reference} (Alice, paid)"))

        # Bob: paid corporate ticket
        if corporate:
            order2 = Order.objects.create(
                conference=conference,
                user=bob,
                status=Order.Status.PAID,
                subtotal=corporate.price,
                total=corporate.price,
                billing_name="Bob Jones",
                billing_email="bob@example.com",
                billing_company="Acme Corp",
                reference=f"ORD-{self._generate_voucher_code(length=6)}",
            )
            OrderLineItem.objects.create(
                order=order2,
                description=f"Ticket: {corporate.name}",
                quantity=1,
                unit_price=corporate.price,
                line_total=corporate.price,
                ticket_type=corporate,
            )
            Payment.objects.create(
                order=order2,
                method=Payment.Method.STRIPE,
                amount=corporate.price,
                stripe_payment_intent_id=f"pi_demo_{secrets.token_hex(8)}",
                reference=f"ch_demo_{secrets.token_hex(8)}",
            )
            self.stdout.write(self.style.SUCCESS(f"  Created order: {order2.reference} (Bob, paid)"))

        # Carol: comp speaker ticket (pending)
        order3 = Order.objects.create(
            conference=conference,
            user=carol,
            status=Order.Status.PAID,
            subtotal=Decimal(0),
            total=Decimal(0),
            billing_name="Carol Chen",
            billing_email="carol@example.com",
            reference=f"ORD-{self._generate_voucher_code(length=6)}",
        )
        speaker = TicketType.objects.filter(conference=conference, slug="speaker").first()
        if speaker:
            OrderLineItem.objects.create(
                order=order3,
                description=f"Ticket: {speaker.name}",
                quantity=1,
                unit_price=Decimal(0),
                line_total=Decimal(0),
                ticket_type=speaker,
            )
        Payment.objects.create(
            order=order3,
            method=Payment.Method.COMP,
            amount=Decimal(0),
            reference="Speaker comp",
        )
        self.stdout.write(self.style.SUCCESS(f"  Created order: {order3.reference} (Carol, speaker comp)"))

    def _seed_carts(
        self,
        conference: Conference,
        users: list[Any],
        individual: TicketType,
        tshirt: AddOn | None,
    ) -> None:
        """Create a sample open cart.

        Args:
            conference: The conference for the cart.
            users: Demo users.
            individual: A ticket type to add to the cart.
            tshirt: An add-on to add to the cart (optional).
        """
        if Cart.objects.filter(conference=conference).exists():
            self.stdout.write(self.style.WARNING("  Carts already exist, skipping."))
            return

        bob = users[1]
        cart = Cart.objects.create(user=bob, conference=conference, status=Cart.Status.OPEN)
        CartItem.objects.create(cart=cart, ticket_type=individual, quantity=1)
        if tshirt:
            CartItem.objects.create(cart=cart, addon=tshirt, quantity=2)
        self.stdout.write(self.style.SUCCESS(f"  Created open cart for {bob.username}"))

    def _seed_credits(self, conference: Conference, users: list[Any]) -> None:
        """Create a sample store credit.

        Args:
            conference: The conference for the credit.
            users: Demo users.
        """
        if Credit.objects.filter(conference=conference).exists():
            self.stdout.write(self.style.WARNING("  Credits already exist, skipping."))
            return

        alice = users[0]
        Credit.objects.create(
            user=alice,
            conference=conference,
            amount=Decimal("25.00"),
            status=Credit.Status.AVAILABLE,
            note="Refund from cancelled tutorial add-on",
        )
        self.stdout.write(self.style.SUCCESS(f"  Created $25 credit for {alice.username}"))
