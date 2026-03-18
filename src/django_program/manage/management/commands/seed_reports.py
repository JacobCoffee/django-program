"""Management command to seed the database with realistic demo data for admin reports."""

import datetime
import hashlib
import random
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.utils import timezone

from django_program.conference.models import Conference
from django_program.pretalx.models import Speaker, Talk
from django_program.registration.conditions import (
    DiscountForCategory,
    DiscountForProduct,
    GroupMemberCondition,
    SpeakerCondition,
    TimeOrStockLimitCondition,
)
from django_program.registration.models import (
    AddOn,
    Attendee,
    Credit,
    Order,
    OrderLineItem,
    Payment,
    TicketType,
    Voucher,
)

User = get_user_model()

# fmt: off
FIRST_NAMES = [
    "Alice", "Bob", "Carol", "Dan", "Eva", "Frank", "Grace", "Hank", "Iris", "Jake",
    "Kira", "Leo", "Maya", "Noah", "Olivia", "Pete", "Quinn", "Rosa", "Sam", "Tara",
    "Uma", "Victor", "Wendy", "Xavier", "Yara", "Zane", "Amara", "Brian", "Cleo",
    "Derek", "Elena", "Felix", "Gina", "Hugo", "Isla", "Jorge", "Keiko", "Liam",
    "Mira", "Nadia", "Oscar", "Priya", "Ravi", "Sofia", "Tomás", "Ursula", "Vikram",
    "Wren", "Xander", "Yuki", "Zara", "Aiden", "Bianca", "Caleb", "Diana", "Elias",
    "Freya", "Gavin", "Helena", "Ivan", "Julia", "Kai", "Luna", "Marco", "Nina",
    "Omar", "Petra", "Reed", "Sana", "Theo", "Uma", "Vera", "Wesley", "Ximena",
    "Yasmin", "Zeke", "Aria", "Beckett", "Celeste", "Dario",
]
LAST_NAMES = [
    "Johnson", "Williams", "Martinez", "Thompson", "Nakamura", "Okafor", "Chen",
    "Petrov", "Dubois", "Fernandez", "Svensson", "Gupta", "Kim", "Müller", "Santos",
    "Patel", "O'Brien", "Rossi", "Tanaka", "Johansson", "Kowalski", "Singh", "Lee",
    "Davis", "Anderson", "Garcia", "Brown", "Taylor", "Wilson", "Moore", "Clark",
    "Wright", "Lopez", "Adams", "Baker", "Rivera", "Reed", "Flores", "Park",
    "Schmidt", "Moreno", "Chung", "Novak", "Berg", "Shah", "Costa", "Ito",
]
TALK_TITLES = [
    "Building Async APIs with Python 3.14", "Type Safety Beyond mypy",
    "Django at Scale: Lessons from Production", "ML Pipelines That Don't Suck",
    "WebAssembly Meets Python", "The Future of Packaging with uv",
    "Postgres Performance Deep Dive", "Testing Microservices in CI",
    "Writing Your First CPython Extension", "Observability for Python Apps",
    "GraphQL vs REST: A Measured Take", "Sustainable Open Source Maintenance",
    "Real-time Data with Django Channels", "Security Hardening for Web Apps",
    "Python in Scientific Computing", "Building CLI Tools with Rich",
    "Distributed Tracing with OpenTelemetry", "Event-Driven Architecture Patterns",
    "Containerizing Python: Beyond Basics", "Intro to Rust for Pythonistas",
    "Data Validation with Pydantic v3", "FastAPI to Litestar Migration Guide",
    "Teaching Python to Beginners", "Accessibility in Python Web Apps",
    "AI-Assisted Code Review", "GPU Programming with Python",
    "State Machines in Production", "Refactoring Legacy Django Apps",
    "Python Memory Management Internals", "Building Browser Extensions with Pyodide",
]
BIOS = [
    "Senior software engineer with 10+ years in Python.",
    "Open-source maintainer and conference organizer.",
    "Data scientist specializing in NLP and ML pipelines.",
    "Backend architect focused on distributed systems.",
    "DevOps engineer passionate about CI/CD and observability.",
    "Full-stack developer and educator.",
    "Security researcher and Python core contributor.",
    "PhD in computer science, currently at a startup.",
    "Community organizer and diversity advocate in tech.",
    "Staff engineer at a Fortune 500 company.",
]
# fmt: on

TICKET_TYPES = [
    ("Early Bird", "early-bird", Decimal("199.00"), 100),
    ("Regular", "regular", Decimal("349.00"), 200),
    ("Student", "student", Decimal("99.00"), 50),
    ("Corporate", "corporate", Decimal("599.00"), 75),
    ("Speaker", "speaker", Decimal("0.00"), 30),
]

ADDONS = [
    ("Tutorial Day Pass", "tutorial", Decimal("150.00")),
    ("Conference T-Shirt", "t-shirt", Decimal("35.00")),
    ("Catered Lunch (3 days)", "lunch", Decimal("75.00")),
    ("Sprints Workshop", "workshop", Decimal("50.00")),
]

VOUCHER_DEFS = [
    ("SPEAKER2027", "comp", Decimal(0), 30, 18),
    ("EARLY20", "percentage", Decimal(20), 50, 37),
    ("SPONSOR50", "fixed_amount", Decimal(50), 20, 14),
    ("VOLUNTEER", "comp", Decimal(0), 15, 12),
    ("STUDENT10", "percentage", Decimal(10), 100, 61),
    ("FLASH25", "fixed_amount", Decimal(25), 10, 10),
    ("PYLADIES", "comp", Decimal(0), 20, 9),
    ("CORP-BULK", "percentage", Decimal(15), 30, 22),
    ("TUTORIAL-FREE", "comp", Decimal(0), 10, 7),
    ("RETURNING", "fixed_amount", Decimal(75), 40, 28),
]


def _seeded_random(seed: str) -> random.Random:
    """Return a seeded Random instance for reproducible data."""
    return random.Random(hashlib.md5(seed.encode()).hexdigest())  # noqa: S324, S311


class Command(BaseCommand):
    """Seed database with realistic demo data for testing admin reports."""

    help = "Seed database with realistic conference demo data (~80 attendees, 20 speakers, 100+ orders)"

    def handle(self, *args: object, **kwargs: object) -> None:
        """Create a full conference with realistic registration data."""
        self.rng = _seeded_random("pycon-2027-seed")
        self.stdout.write("Seeding realistic demo data...")

        self._create_superuser()
        conference = self._create_conference()
        ticket_types = self._create_ticket_types(conference)
        addons = self._create_addons(conference)
        vouchers = self._create_vouchers(conference)
        users = self._create_users(80)
        staff = self._create_staff(3)
        speakers = self._create_speakers(conference, users[:25])
        self._create_talks(conference, speakers)
        self._create_orders(conference, users, ticket_types, addons, vouchers)
        self._create_discount_conditions(conference, ticket_types)
        self._create_credits(conference, users)

        n_attendees = Attendee.objects.filter(conference=conference).count()
        n_orders = Order.objects.filter(conference=conference).count()
        n_speakers = Speaker.objects.filter(conference=conference).count()

        self.stdout.write(self.style.SUCCESS(f"\nSeeded {conference.name}:"))
        self.stdout.write("  Admin: admin / admin")
        self.stdout.write(f"  Staff users: {len(staff)}")
        self.stdout.write(f"  Attendee users: {len(users)}")
        self.stdout.write(f"  Speakers: {n_speakers}")
        self.stdout.write(f"  Talks: {Talk.objects.filter(conference=conference).count()}")
        self.stdout.write(f"  Orders: {n_orders}")
        self.stdout.write(f"  Attendees (registered): {n_attendees}")
        self.stdout.write(f"  Ticket types: {len(ticket_types)}")
        self.stdout.write(f"  Add-ons: {len(addons)}")
        self.stdout.write(f"  Vouchers: {len(vouchers)}")
        self.stdout.write(f"  Credits: {Credit.objects.filter(conference=conference).count()}")

    def _create_superuser(self) -> object:
        """Create the admin superuser."""
        admin, created = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@example.com",
                "first_name": "Admin",
                "last_name": "User",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created:
            admin.set_password("admin")
            admin.save()
        return admin

    def _create_conference(self) -> Conference:
        """Create the PyCon 2027 conference."""
        conference, _ = Conference.objects.get_or_create(
            slug="pycon-2027",
            defaults={
                "name": "PyCon US 2027",
                "start_date": datetime.date(2027, 5, 14),
                "end_date": datetime.date(2027, 5, 22),
                "timezone": "America/Pittsburgh",
                "venue": "David L. Lawrence Convention Center",
                "address": "1000 Fort Duquesne Blvd, Pittsburgh, PA 15222",
                "website_url": "https://us.pycon.org/2027/",
                "is_active": True,
            },
        )
        return conference

    def _create_ticket_types(self, conference: Conference) -> list[TicketType]:
        """Create ticket types."""
        result = []
        for idx, (name, slug, price, qty) in enumerate(TICKET_TYPES):
            tt, _ = TicketType.objects.get_or_create(
                conference=conference,
                slug=slug,
                defaults={
                    "name": name,
                    "price": price,
                    "total_quantity": qty,
                    "order": idx,
                    "is_active": True,
                    "requires_voucher": slug == "speaker",
                },
            )
            result.append(tt)
        return result

    def _create_addons(self, conference: Conference) -> list[AddOn]:
        """Create add-on products."""
        result = []
        for idx, (name, slug, price) in enumerate(ADDONS):
            addon, _ = AddOn.objects.get_or_create(
                conference=conference,
                slug=slug,
                defaults={"name": name, "price": price, "order": idx, "is_active": True},
            )
            result.append(addon)
        return result

    def _create_vouchers(self, conference: Conference) -> list[Voucher]:
        """Create vouchers with realistic usage counts."""
        result = []
        for code, vtype, value, max_uses, times_used in VOUCHER_DEFS:
            voucher, created = Voucher.objects.get_or_create(
                conference=conference,
                code=code,
                defaults={
                    "voucher_type": vtype,
                    "discount_value": value,
                    "max_uses": max_uses,
                    "times_used": times_used,
                    "is_active": True,
                },
            )
            if not created:
                voucher.times_used = times_used
                voucher.save(update_fields=["times_used"])
            result.append(voucher)
        return result

    def _create_users(self, count: int) -> list[object]:
        """Create attendee users with realistic names."""
        result = []
        for i in range(count):
            first = FIRST_NAMES[i % len(FIRST_NAMES)]
            last = LAST_NAMES[i % len(LAST_NAMES)]
            username = f"{first.lower()}.{last.lower()}.{i}"
            email = f"{username}@example.com"
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"email": email, "first_name": first, "last_name": last},
            )
            if created:
                user.set_password("testpass123")
                user.save()
            result.append(user)
        return result

    def _create_staff(self, count: int) -> list[object]:
        """Create staff users with the Reports group."""
        group, _ = Group.objects.get_or_create(name="Program: Reports")
        staff_names = [
            ("sarah.staff", "Sarah", "Staff"),
            ("mike.ops", "Mike", "Operations"),
            ("jen.finance", "Jen", "Finance"),
        ]
        result = []
        for username, first, last in staff_names[:count]:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@pycon.org",
                    "first_name": first,
                    "last_name": last,
                    "is_staff": True,
                },
            )
            if created:
                user.set_password("staffpass")
                user.save()
            user.groups.add(group)
            result.append(user)
        return result

    def _create_speakers(self, conference: Conference, users: list[object]) -> list[Speaker]:
        """Create 20 speakers linked to users."""
        result = []
        for i, user in enumerate(users[:20]):
            speaker, _ = Speaker.objects.get_or_create(
                conference=conference,
                pretalx_code=f"SPKR{i + 1:03d}",
                defaults={
                    "name": f"{user.first_name} {user.last_name}",
                    "email": user.email,
                    "user": user,
                    "biography": BIOS[i % len(BIOS)],
                    "synced_at": timezone.now(),
                },
            )
            result.append(speaker)
        return result

    def _create_talks(self, conference: Conference, speakers: list[Speaker]) -> None:
        """Create talks and link speakers."""
        for i, title in enumerate(TALK_TITLES):
            talk, created = Talk.objects.get_or_create(
                conference=conference,
                pretalx_code=f"TALK{i + 1:03d}",
                defaults={
                    "title": title,
                    "submission_type": self.rng.choice(["Talk", "Talk", "Talk", "Tutorial", "Workshop"]),
                    "track": self.rng.choice(["Web", "Data", "DevOps", "Core Python", "Community", ""]),
                    "duration": self.rng.choice([30, 30, 45, 45, 90]),
                    "synced_at": timezone.now(),
                },
            )
            if created:
                # Assign 1-2 speakers per talk
                primary = speakers[i % len(speakers)]
                talk.speakers.add(primary)
                if self.rng.random() < 0.3 and len(speakers) > 1:
                    co = speakers[(i + 7) % len(speakers)]
                    if co != primary:
                        talk.speakers.add(co)

    def _create_orders(  # noqa: C901, PLR0912, PLR0915
        self,
        conference: Conference,
        users: list[object],
        ticket_types: list[TicketType],
        addons: list[AddOn],
        vouchers: list[Voucher],
    ) -> None:
        """Create ~100 orders spread across 45 days with realistic distribution."""
        now = timezone.now()
        # Weight toward regular and early bird tickets
        ticket_weights = [25, 40, 15, 10, 10]  # early-bird, regular, student, corporate, speaker
        order_num = 0

        for days_ago in range(45, 0, -1):
            # More orders closer to conference, ramp up
            base_rate = 1 + (45 - days_ago) * 0.08
            n_orders = max(0, int(self.rng.gauss(base_rate, 0.8)))
            n_orders = min(n_orders, 5)

            for _ in range(n_orders):
                order_num += 1
                user = users[order_num % len(users)]
                ref = f"ORD-{order_num:04d}"
                created_at = now - datetime.timedelta(days=days_ago, hours=self.rng.randint(0, 23))

                if Order.objects.filter(reference=ref).exists():
                    continue

                # Pick ticket type
                tt_idx = self.rng.choices(range(len(ticket_types)), weights=ticket_weights, k=1)[0]
                ticket = ticket_types[tt_idx]

                # Pick 0-2 addons
                n_addons = self.rng.choices([0, 1, 2, 3], weights=[20, 40, 30, 10], k=1)[0]
                chosen_addons = self.rng.sample(range(len(addons)), min(n_addons, len(addons)))

                # Maybe apply a voucher (~25% of orders)
                voucher_code = ""
                discount = Decimal("0.00")
                if self.rng.random() < 0.25:
                    v = self.rng.choice(vouchers)
                    voucher_code = v.code
                    subtotal = ticket.price + sum(
                        (Decimal(str(addons[ai].price)) for ai in chosen_addons), Decimal("0.00")
                    )
                    if v.voucher_type == Voucher.VoucherType.COMP:
                        discount = subtotal
                    elif v.voucher_type == Voucher.VoucherType.PERCENTAGE:
                        discount = (subtotal * v.discount_value / Decimal(100)).quantize(Decimal("0.01"))
                    elif v.voucher_type == Voucher.VoucherType.FIXED_AMOUNT:
                        discount = min(v.discount_value, subtotal)

                subtotal = ticket.price + sum((Decimal(str(addons[ai].price)) for ai in chosen_addons), Decimal("0.00"))
                total = max(subtotal - discount, Decimal("0.00"))

                # Status distribution: 75% paid, 10% pending, 8% cancelled, 5% refunded, 2% partial
                roll = self.rng.random()
                if roll < 0.75:
                    status = Order.Status.PAID
                elif roll < 0.85:
                    status = Order.Status.PENDING
                elif roll < 0.93:
                    status = Order.Status.CANCELLED
                elif roll < 0.98:
                    status = Order.Status.REFUNDED
                else:
                    status = Order.Status.PARTIALLY_REFUNDED

                hold_expires = None
                if status == Order.Status.PENDING:
                    hold_expires = now + datetime.timedelta(hours=24)

                order = Order.objects.create(
                    conference=conference,
                    user=user,
                    status=status,
                    subtotal=subtotal,
                    discount_amount=discount,
                    total=total,
                    voucher_code=voucher_code,
                    billing_name=f"{user.first_name} {user.last_name}",
                    billing_email=user.email,
                    reference=ref,
                    hold_expires_at=hold_expires,
                )
                Order.objects.filter(pk=order.pk).update(created_at=created_at)

                # Line items
                OrderLineItem.objects.create(
                    order=order,
                    description=ticket.name,
                    quantity=1,
                    unit_price=ticket.price,
                    line_total=ticket.price,
                    ticket_type=ticket,
                )
                for ai in chosen_addons:
                    addon = addons[ai]
                    OrderLineItem.objects.create(
                        order=order,
                        description=addon.name,
                        quantity=1,
                        unit_price=addon.price,
                        line_total=addon.price,
                        addon=addon,
                    )

                # Payment + attendee for paid orders
                if status in (Order.Status.PAID, Order.Status.PARTIALLY_REFUNDED):
                    method = Payment.Method.COMP if total == 0 else Payment.Method.STRIPE
                    if self.rng.random() < 0.05:
                        method = Payment.Method.MANUAL
                    Payment.objects.create(
                        order=order,
                        method=method,
                        status=Payment.Status.SUCCEEDED,
                        amount=total,
                        stripe_payment_intent_id=f"pi_{ref.lower()}" if method == Payment.Method.STRIPE else "",
                    )

                    attendee, att_created = Attendee.objects.get_or_create(
                        user=user,
                        conference=conference,
                        defaults={"order": order},
                    )
                    if att_created:
                        Attendee.objects.filter(pk=attendee.pk).update(created_at=created_at)

                    # ~60% of attendees check in (more likely for older orders)
                    if self.rng.random() < 0.6 and days_ago > 5:
                        checkin_time = created_at + datetime.timedelta(days=self.rng.randint(1, 5), hours=9)
                        attendee.checked_in_at = checkin_time
                        attendee.completed_registration = True
                        attendee.save(update_fields=["checked_in_at", "completed_registration"])

        self.stdout.write(f"  Orders: {order_num}")

    def _create_discount_conditions(self, conference: Conference, ticket_types: list[TicketType]) -> None:
        """Create a variety of discount conditions."""
        now = timezone.now()

        # Early bird
        eb, created = TimeOrStockLimitCondition.objects.get_or_create(
            conference=conference,
            name="Early Bird Discount",
            defaults={
                "description": "15% off for the first 100 registrations",
                "is_active": True,
                "priority": 10,
                "discount_type": "percentage",
                "discount_value": Decimal("15.00"),
                "start_time": now - datetime.timedelta(days=60),
                "end_time": now + datetime.timedelta(days=30),
                "limit": 100,
                "times_used": 47,
            },
        )
        if created:
            eb.applicable_ticket_types.set([t for t in ticket_types if t.slug in ("regular", "early-bird")])

        # Tutorial bundle
        tb, created = DiscountForProduct.objects.get_or_create(
            conference=conference,
            name="Tutorial Bundle Savings",
            defaults={
                "description": "$25 off tutorial day pass with any ticket",
                "is_active": True,
                "priority": 20,
                "discount_type": "fixed_amount",
                "discount_value": Decimal("25.00"),
                "start_time": now - datetime.timedelta(days=30),
                "end_time": now + datetime.timedelta(days=60),
                "limit": 50,
                "times_used": 12,
            },
        )
        if created:
            tb.applicable_ticket_types.set(ticket_types)

        # Speaker comp
        sc, created = SpeakerCondition.objects.get_or_create(
            conference=conference,
            name="Speaker Complimentary",
            defaults={
                "description": "Free registration for accepted speakers",
                "is_active": True,
                "priority": 5,
                "discount_type": "percentage",
                "discount_value": Decimal("100.00"),
                "is_presenter": True,
                "is_copresenter": True,
            },
        )
        if created:
            sc.applicable_ticket_types.set(ticket_types)

        # Staff discount
        staff_group, _ = Group.objects.get_or_create(name="Program: Reports")
        gm, created = GroupMemberCondition.objects.get_or_create(
            conference=conference,
            name="Staff Discount",
            defaults={
                "description": "50% off for staff members",
                "is_active": True,
                "priority": 15,
                "discount_type": "percentage",
                "discount_value": Decimal("50.00"),
            },
        )
        if created:
            gm.groups.add(staff_group)
            gm.applicable_ticket_types.set(ticket_types)

        # Category-wide flash sale
        DiscountForCategory.objects.get_or_create(
            conference=conference,
            name="Flash Sale — All Add-ons",
            defaults={
                "description": "10% off all add-ons this week",
                "is_active": False,
                "priority": 30,
                "percentage": Decimal("10.00"),
                "apply_to_tickets": False,
                "apply_to_addons": True,
                "start_time": now - datetime.timedelta(days=7),
                "end_time": now - datetime.timedelta(days=1),
                "limit": 200,
                "times_used": 34,
            },
        )

    def _create_credits(self, conference: Conference, users: list[object]) -> None:
        """Create realistic credit records."""
        paid_orders = list(
            Order.objects.filter(conference=conference, status=Order.Status.PAID).order_by("created_at")[:10]
        )

        credit_defs = [
            (0, Decimal("50.00"), Decimal("50.00"), Credit.Status.AVAILABLE, "Partial refund — schedule conflict"),
            (1, Decimal("99.00"), Decimal("0.00"), Credit.Status.APPLIED, "Full refund applied to upgrade"),
            (2, Decimal("25.00"), Decimal("25.00"), Credit.Status.EXPIRED, "Promo credit expired"),
            (3, Decimal("349.00"), Decimal("349.00"), Credit.Status.AVAILABLE, "Cancelled corporate registration"),
            (4, Decimal("75.00"), Decimal("0.00"), Credit.Status.APPLIED, "Lunch refund — dietary issue"),
            (5, Decimal("150.00"), Decimal("150.00"), Credit.Status.AVAILABLE, "Tutorial cancellation refund"),
            (6, Decimal("35.00"), Decimal("0.00"), Credit.Status.APPLIED, "T-shirt size unavailable"),
            (7, Decimal("199.00"), Decimal("100.00"), Credit.Status.AVAILABLE, "Partial early-bird refund"),
        ]

        for i, (user_idx, amount, remaining, status, note) in enumerate(credit_defs):
            if user_idx >= len(users):
                continue
            Credit.objects.get_or_create(
                user=users[user_idx],
                conference=conference,
                amount=amount,
                defaults={
                    "remaining_amount": remaining,
                    "status": status,
                    "source_order": paid_orders[i] if i < len(paid_orders) else None,
                    "applied_to_order": (
                        paid_orders[i + 1] if status == Credit.Status.APPLIED and i + 1 < len(paid_orders) else None
                    ),
                    "note": note,
                },
            )
