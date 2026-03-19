"""Seed the example database with realistic conference demo data.

Run via ``make dev`` or directly::

    DJANGO_SETTINGS_MODULE=settings uv run python examples/seed.py
"""

import datetime
import hashlib
import os
import random
import sys
from decimal import Decimal
from pathlib import Path

# Bootstrap Django before any model imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")

import django

django.setup()

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone

from django_program.conference.models import Conference, Expense, ExpenseCategory
from django_program.pretalx.models import Room, ScheduleSlot, SessionRating, Speaker, Talk, TalkOverride
from django_program.programs.models import Activity, ActivitySignup, Survey, SurveyResponse, TravelGrant
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
    Cart,
    CartItem,
    Credit,
    Order,
    OrderLineItem,
    Payment,
    TicketType,
    Voucher,
)
from django_program.sponsors.models import BulkPurchase, BulkPurchaseVoucher, Sponsor, SponsorBenefit, SponsorLevel

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
    # (name, slug, price, quantity, bulk_enabled, available_from_offset_days, available_until_offset_days)
    ("Early Bird", "early-bird", Decimal("199.00"), 100, False, -90, -14),
    ("Regular", "regular", Decimal("349.00"), 200, True, -14, 60),
    ("Student", "student", Decimal("99.00"), 50, False, -60, 60),
    ("Corporate", "corporate", Decimal("599.00"), 75, True, -30, 45),
    ("Speaker", "speaker", Decimal("0.00"), 30, False, None, None),
]

ADDONS = [
    # (name, slug, price, bulk_enabled)
    ("Tutorial Day Pass", "tutorial", Decimal("150.00"), True),
    ("Conference T-Shirt", "t-shirt", Decimal("35.00"), True),
    ("Catered Lunch (3 days)", "lunch", Decimal("75.00"), False),
    ("Sprints Workshop", "workshop", Decimal("50.00"), True),
]

VOUCHER_DEFS = [
    # (code, type, value, max_uses, times_used, unlocks_hidden, valid_from_offset, valid_until_offset)
    ("SPEAKER2027", "comp", Decimal(0), 30, 18, True, -60, 60),
    ("EARLY20", "percentage", Decimal(20), 50, 37, False, -90, -14),
    ("SPONSOR50", "fixed_amount", Decimal(50), 20, 14, False, -30, 45),
    ("VOLUNTEER", "comp", Decimal(0), 15, 12, True, -30, 60),
    ("STUDENT10", "percentage", Decimal(10), 100, 61, False, -60, 60),
    ("FLASH25", "fixed_amount", Decimal(25), 10, 10, False, -7, 0),
    ("PYLADIES", "comp", Decimal(0), 20, 9, True, -45, 60),
    ("CORP-BULK", "percentage", Decimal(15), 30, 22, False, -30, 30),
    ("TUTORIAL-FREE", "comp", Decimal(0), 10, 7, True, -14, 60),
    ("RETURNING", "fixed_amount", Decimal(75), 40, 28, False, -60, 30),
]


def _seeded_random(seed: str) -> random.Random:
    """Return a seeded Random instance for reproducible data."""
    return random.Random(hashlib.md5(seed.encode()).hexdigest())


class Seeder:
    """Seed the example database with realistic conference demo data."""

    def __init__(self) -> None:
        self.rng = _seeded_random("python-2077-seed")

    def run(self) -> None:
        """Create a full conference with realistic registration data."""
        print("Seeding realistic demo data...")

        self._create_superuser()
        conference = self._create_conference()
        prev_conferences = self._create_previous_conferences()
        ticket_types = self._create_ticket_types(conference)
        addons = self._create_addons(conference)
        vouchers = self._create_vouchers(conference)
        users = self._create_users(80)
        staff = self._create_staff(3)
        speakers = self._create_speakers(conference, users[:25])
        talks = self._create_talks(conference, speakers)
        rooms = self._create_rooms(conference)
        self._create_schedule(conference, talks, rooms)
        sponsors = self._create_sponsors(conference)
        self._create_orders(conference, users, ticket_types, addons, vouchers)
        self._create_carts(conference, users, ticket_types, addons)
        self._create_overrides(conference, talks)
        self._create_discount_conditions(conference, ticket_types)
        self._create_credits(conference, users)

        # Phase 25: Analytics seed data
        self._create_previous_conference_data(prev_conferences, users, speakers)
        self._create_sponsor_benefits(sponsors)
        self._create_activities_and_signups(conference, users, rooms)
        self._create_expenses(conference)
        self._create_session_ratings(conference, talks, users)
        self._create_surveys(conference, users)
        self._create_travel_grants(conference, users)
        self._create_more_carts(conference, users, ticket_types, addons)
        self._create_bulk_purchases(conference, sponsors, ticket_types, addons, users)

        n_attendees = Attendee.objects.filter(conference=conference).count()
        n_orders = Order.objects.filter(conference=conference).count()
        n_speakers = Speaker.objects.filter(conference=conference).count()

        print(f"\nSeeded {conference.name}:")
        print("  Admin: admin / admin")
        print(f"  Staff users: {len(staff)}")
        print(f"  Attendee users: {len(users)}")
        print(f"  Speakers: {n_speakers}")
        print(f"  Talks: {Talk.objects.filter(conference=conference).count()}")
        print(f"  Orders: {n_orders}")
        print(f"  Attendees (registered): {n_attendees}")
        print(f"  Ticket types: {len(ticket_types)}")
        print(f"  Add-ons: {len(addons)}")
        print(f"  Vouchers: {len(vouchers)}")
        print(f"  Credits: {Credit.objects.filter(conference=conference).count()}")
        print(f"  Expenses: {Expense.objects.filter(conference=conference).count()}")
        print(f"  Session ratings: {SessionRating.objects.filter(conference=conference).count()}")
        print(f"  Activities: {Activity.objects.filter(conference=conference).count()}")
        print(f"  Travel grants: {TravelGrant.objects.filter(conference=conference).count()}")
        print(f"  Surveys: {Survey.objects.filter(conference=conference).count()}")
        print(f"  Bulk purchases: {BulkPurchase.objects.filter(conference=conference).count()}")
        for prev_conf in prev_conferences:
            prev_att = Attendee.objects.filter(conference=prev_conf).count()
            prev_talks = Talk.objects.filter(conference=prev_conf).count()
            print(f"  Previous conference: {prev_conf.name} ({prev_att} attendees, {prev_talks} talks)")

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
        """Use the existing bootstrapped conference, or create one."""
        # Use whatever conference bootstrap_conference created
        conference = Conference.objects.first()
        if conference:
            # Ensure budget fields are populated
            if not conference.revenue_budget:
                Conference.objects.filter(pk=conference.pk).update(
                    revenue_budget=Decimal("50000.00"),
                    target_attendance=150,
                    grant_budget=Decimal("15000.00"),
                )
                conference.refresh_from_db()
            return conference
        # Fallback: create one if bootstrap wasn't run
        conference, _ = Conference.objects.get_or_create(
            slug="python-2077",
            defaults={
                "name": "Python 2077",
                "start_date": datetime.date(2027, 5, 14),
                "end_date": datetime.date(2027, 5, 22),
                "timezone": "America/Pittsburgh",
                "venue": "Pittsburgh Convention Center",
                "address": "1000 Fort Duquesne Blvd, Pittsburgh, PA 15222",
                "website_url": "https://python2077.dev/",
                "is_active": True,
                "revenue_budget": Decimal("50000.00"),
                "target_attendance": 150,
                "grant_budget": Decimal("15000.00"),
            },
        )
        return conference

    def _create_ticket_types(self, conference: Conference) -> list[TicketType]:
        """Use existing ticket types from bootstrap, or create defaults."""
        existing = list(TicketType.objects.filter(conference=conference).order_by("order"))
        if existing:
            return existing
        now = timezone.now()
        result = []
        for idx, (name, slug, price, qty, bulk, from_off, until_off) in enumerate(TICKET_TYPES):
            defaults: dict[str, object] = {
                "name": name,
                "price": price,
                "total_quantity": qty,
                "order": idx,
                "is_active": True,
                "requires_voucher": slug == "speaker",
                "bulk_enabled": bulk,
            }
            if from_off is not None:
                defaults["available_from"] = now + datetime.timedelta(days=from_off)
            if until_off is not None:
                defaults["available_until"] = now + datetime.timedelta(days=until_off)
            tt, created = TicketType.objects.get_or_create(
                conference=conference,
                slug=slug,
                defaults=defaults,
            )
            if not created:
                update_fields = []
                if tt.bulk_enabled != bulk:
                    tt.bulk_enabled = bulk
                    update_fields.append("bulk_enabled")
                if not tt.available_from and from_off is not None:
                    tt.available_from = now + datetime.timedelta(days=from_off)
                    update_fields.append("available_from")
                if not tt.available_until and until_off is not None:
                    tt.available_until = now + datetime.timedelta(days=until_off)
                    update_fields.append("available_until")
                if update_fields:
                    tt.save(update_fields=update_fields)
            result.append(tt)
        return result

    def _create_addons(self, conference: Conference) -> list[AddOn]:
        """Use existing add-ons from bootstrap, or create defaults."""
        existing = list(AddOn.objects.filter(conference=conference).order_by("order"))
        if existing:
            return existing
        result = []
        for idx, (name, slug, price, bulk) in enumerate(ADDONS):
            addon, created = AddOn.objects.get_or_create(
                conference=conference,
                slug=slug,
                defaults={"name": name, "price": price, "order": idx, "is_active": True, "bulk_enabled": bulk},
            )
            if not created and addon.bulk_enabled != bulk:
                addon.bulk_enabled = bulk
                addon.save(update_fields=["bulk_enabled"])
            result.append(addon)
        return result

    def _create_vouchers(self, conference: Conference) -> list[Voucher]:
        """Create vouchers with realistic usage counts and validity windows."""
        now = timezone.now()
        result = []
        for code, vtype, value, max_uses, times_used, unlocks, from_off, until_off in VOUCHER_DEFS:
            valid_from = now + datetime.timedelta(days=from_off) if from_off is not None else None
            valid_until = now + datetime.timedelta(days=until_off) if until_off is not None else None
            voucher, created = Voucher.objects.get_or_create(
                conference=conference,
                code=code,
                defaults={
                    "voucher_type": vtype,
                    "discount_value": value,
                    "max_uses": max_uses,
                    "times_used": times_used,
                    "is_active": True,
                    "unlocks_hidden_tickets": unlocks,
                    "valid_from": valid_from,
                    "valid_until": valid_until,
                },
            )
            if not created:
                update_fields = ["times_used"]
                voucher.times_used = times_used
                if not voucher.unlocks_hidden_tickets and unlocks:
                    voucher.unlocks_hidden_tickets = unlocks
                    update_fields.append("unlocks_hidden_tickets")
                if not voucher.valid_from and valid_from:
                    voucher.valid_from = valid_from
                    update_fields.append("valid_from")
                if not voucher.valid_until and valid_until:
                    voucher.valid_until = valid_until
                    update_fields.append("valid_until")
                voucher.save(update_fields=update_fields)
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
                    "email": f"{username}@python2077.dev",
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

    def _create_talks(self, conference: Conference, speakers: list[Speaker]) -> list[Talk]:
        """Create talks and link speakers."""
        result = []
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
                primary = speakers[i % len(speakers)]
                talk.speakers.add(primary)
                if self.rng.random() < 0.3 and len(speakers) > 1:
                    co = speakers[(i + 7) % len(speakers)]
                    if co != primary:
                        talk.speakers.add(co)
            result.append(talk)
        return result

    def _create_rooms(self, conference: Conference) -> list[Room]:
        """Create conference rooms."""
        room_defs = [
            ("Hall A", 500),
            ("Hall B", 300),
            ("Room 301", 80),
            ("Room 302", 80),
            ("Room 303", 50),
            ("Tutorial Room 1", 40),
            ("Tutorial Room 2", 40),
            ("Open Space", 100),
        ]
        result = []
        for i, (name, capacity) in enumerate(room_defs):
            room, _ = Room.objects.get_or_create(
                conference=conference,
                name=name,
                defaults={"pretalx_id": 1000 + i, "capacity": capacity, "synced_at": timezone.now()},
            )
            result.append(room)
        return result

    def _create_schedule(self, conference: Conference, talks: list[Talk], rooms: list[Room]) -> None:
        """Schedule most talks and add breaks/socials. Leave ~5 unscheduled."""
        conf_start = datetime.datetime(2027, 5, 15, 9, 0, tzinfo=datetime.UTC)

        # Schedule 25 of 30 talks (leave 5 unscheduled)
        scheduled_talks = talks[:25]
        talk_queue = list(scheduled_talks)

        for day_offset in range(3):
            day_start = conf_start + datetime.timedelta(days=day_offset)

            # Morning break
            self._slot(conference, "Registration & Coffee", rooms[0], day_start, 30, ScheduleSlot.SlotType.BREAK)

            # Morning talks — 3 parallel tracks
            morning = day_start + datetime.timedelta(minutes=30)
            for track in range(min(3, len(talk_queue))):
                talk = talk_queue.pop(0) if talk_queue else None
                if talk:
                    self._talk_slot(conference, talk, rooms[track], morning, talk.duration or 30)

            # Lunch
            lunch = day_start + datetime.timedelta(hours=3, minutes=30)
            self._slot(
                conference, "Lunch", rooms[7] if len(rooms) > 7 else rooms[0], lunch, 60, ScheduleSlot.SlotType.BREAK
            )

            # Afternoon talks — up to 5 parallel
            afternoon = day_start + datetime.timedelta(hours=4, minutes=30)
            for track in range(min(5, len(talk_queue))):
                talk = talk_queue.pop(0) if talk_queue else None
                if talk:
                    room = rooms[min(track, len(rooms) - 1)]
                    self._talk_slot(conference, talk, room, afternoon, talk.duration or 30)

            # Evening social
            if day_offset < 2:
                evening = day_start + datetime.timedelta(hours=9)
                title = "Welcome Reception" if day_offset == 0 else "Conference Dinner"
                self._slot(conference, title, rooms[0], evening, 120, ScheduleSlot.SlotType.SOCIAL)

    def _slot(
        self, conference: Conference, title: str, room: Room, start: datetime.datetime, minutes: int, slot_type: str
    ) -> None:
        """Create a non-talk schedule slot."""
        end = start + datetime.timedelta(minutes=minutes)
        ScheduleSlot.objects.get_or_create(
            conference=conference,
            start=start,
            room=room,
            defaults={"title": title, "end": end, "slot_type": slot_type, "synced_at": timezone.now()},
        )

    def _talk_slot(
        self, conference: Conference, talk: Talk, room: Room, start: datetime.datetime, minutes: int
    ) -> None:
        """Create a talk schedule slot and update the talk's scheduling fields."""
        end = start + datetime.timedelta(minutes=minutes)
        _, created = ScheduleSlot.objects.get_or_create(
            conference=conference,
            start=start,
            room=room,
            defaults={"talk": talk, "end": end, "slot_type": ScheduleSlot.SlotType.TALK, "synced_at": timezone.now()},
        )
        if created:
            Talk.objects.filter(pk=talk.pk).update(slot_start=start, slot_end=end, room=room)

    def _create_sponsors(self, conference: Conference) -> list[Sponsor]:
        """Create sponsor levels and sponsors."""
        result: list[Sponsor] = []
        levels = [
            ("Diamond", 50000, 0),
            ("Platinum", 25000, 1),
            ("Gold", 10000, 2),
            ("Silver", 5000, 3),
            ("Community", 0, 4),
        ]
        sponsor_names = [
            ("Diamond", ["MegaCorp AI", "CloudScale Inc"]),
            ("Platinum", ["DataFlow Systems", "PyStack Technologies", "DevOps Pro"]),
            ("Gold", ["CodeCraft Labs", "API Gateway Co", "TestRunner.io", "SecureAuth"]),
            ("Silver", ["Open Source Foundation", "Py Publishing", "WebFrame Tools"]),
            ("Community", ["Local Python User Group", "Django Girls", "PyLadies Pittsburgh"]),
        ]

        for level_name, cost, order in levels:
            level, _ = SponsorLevel.objects.get_or_create(
                conference=conference,
                slug=level_name.lower(),
                defaults={"name": level_name, "cost": cost, "order": order},
            )
            for name_list in sponsor_names:
                if name_list[0] == level_name:
                    for sponsor_name in name_list[1]:
                        from django.utils.text import slugify as _slugify

                        sponsor, _ = Sponsor.objects.get_or_create(
                            conference=conference,
                            slug=_slugify(sponsor_name),
                            defaults={
                                "name": sponsor_name,
                                "level": level,
                                "description": f"{sponsor_name} is a proud {level_name} sponsor.",
                                "is_active": True,
                            },
                        )
                        result.append(sponsor)
        return result

    def _create_carts(self, conference: Conference, users: list, ticket_types: list, addons: list) -> None:
        """Create some active and abandoned carts."""
        now = timezone.now()
        cart_defs = [
            (60, Cart.Status.OPEN, now + datetime.timedelta(hours=2)),
            (61, Cart.Status.OPEN, now + datetime.timedelta(hours=4)),
            (62, Cart.Status.OPEN, None),
            (63, Cart.Status.ABANDONED, now - datetime.timedelta(hours=12)),
            (64, Cart.Status.EXPIRED, now - datetime.timedelta(days=2)),
        ]
        for user_idx, status, expires in cart_defs:
            if user_idx >= len(users):
                continue
            cart, created = Cart.objects.get_or_create(
                user=users[user_idx],
                conference=conference,
                status=status,
                defaults={"expires_at": expires},
            )
            if created and ticket_types:
                CartItem.objects.create(cart=cart, ticket_type=ticket_types[0], quantity=1)
                if addons:
                    CartItem.objects.create(cart=cart, addon=addons[0], quantity=1)

    def _create_overrides(self, conference: Conference, talks: list) -> None:
        """Create some talk overrides for demo."""
        override_data = [
            (0, {"override_title": "Building Async APIs with Python 3.14 (Updated!)"}),
            (3, {"override_abstract": "This talk has been revised with new benchmark data."}),
            (
                7,
                {
                    "override_title": "Testing Microservices — Extended Edition",
                    "override_abstract": "Now includes live demo section with real service mesh.",
                },
            ),
        ]
        for talk_idx, fields in override_data:
            if talk_idx < len(talks):
                TalkOverride.objects.get_or_create(
                    conference=conference,
                    talk=talks[talk_idx],
                    defaults=fields,
                )

    def _create_orders(
        self,
        conference: Conference,
        users: list[object],
        ticket_types: list[TicketType],
        addons: list[AddOn],
        vouchers: list[Voucher],
    ) -> None:
        """Create ~100 orders spread across 45 days with realistic distribution."""
        now = timezone.now()
        # Weight first tickets higher; dynamically sized to match actual count
        n_types = len(ticket_types)
        ticket_weights = [40] + [max(5, 30 - i * 8) for i in range(1, n_types)] if n_types > 1 else [1]
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
                    hold_expires = created_at + datetime.timedelta(hours=24)

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

        print(f"  Orders: {order_num}")

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

    # ------------------------------------------------------------------
    # Phase 25: Analytics seed data
    # ------------------------------------------------------------------

    def _create_previous_conferences(self) -> list[Conference]:
        """Create two previous conferences for richer YoY trend data.

        Returns:
            A list of created/existing Conference instances (oldest first),
            or an empty list if both already existed with no new creation.
        """
        confs: list[Conference] = []

        conf_2075, created_2075 = Conference.objects.get_or_create(
            slug="python-2075",
            defaults={
                "name": "Python 2075",
                "start_date": datetime.date(2025, 5, 14),
                "end_date": datetime.date(2025, 5, 22),
                "timezone": "America/New_York",
                "venue": "Pittsburgh Convention Center",
                "is_active": False,
                "revenue_budget": Decimal("60000.00"),
                "target_attendance": 200,
                "grant_budget": Decimal("20000.00"),
            },
        )
        confs.append(conf_2075)
        if created_2075:
            print("  Created previous conference: Python 2075")

        conf_2076, created_2076 = Conference.objects.get_or_create(
            slug="python-2076",
            defaults={
                "name": "Python 2076",
                "start_date": datetime.date(2026, 5, 14),
                "end_date": datetime.date(2026, 5, 22),
                "timezone": "America/New_York",
                "venue": "Pittsburgh Convention Center",
                "is_active": False,
                "revenue_budget": Decimal("40000.00"),
                "target_attendance": 120,
                "grant_budget": Decimal("10000.00"),
            },
        )
        confs.append(conf_2076)
        if created_2076:
            print("  Created previous conference: Python 2076")

        return confs

    def _create_previous_conference_data(
        self, prev_conferences: list[Conference], users: list, speakers: list[Speaker]
    ) -> None:
        """Seed previous conferences with attendees, orders, sponsors, speakers, and talks.

        Args:
            prev_conferences: List of previous Conference instances (oldest first).
            users: Pool of user instances to draw attendees from.
            speakers: Pool of Speaker instances for speaker return-rate data.
        """
        if not prev_conferences:
            return

        from django.utils.text import slugify as _slugify

        # Per-conference configuration: (attendee_count, speaker_count, sponsors, prices, talk_count)
        conf_configs: list[dict[str, object]] = [
            {
                "attendee_count": 55,
                "speaker_count": 15,
                "sponsors": [
                    "MegaCorp AI",
                    "CloudScale Inc",
                    "DataFlow Systems",
                    "CodeCraft Labs",
                    "Open Source Foundation",
                    "PyStack Technologies",
                ],
                "prices": [299, 499, 599],
                "talk_count": 25,
                "ref_prefix": "PREV75",
            },
            {
                "attendee_count": 40,
                "speaker_count": 12,
                "sponsors": [
                    "MegaCorp AI",
                    "DataFlow Systems",
                    "CodeCraft Labs",
                    "Open Source Foundation",
                ],
                "prices": [99, 199, 349],
                "talk_count": 20,
                "ref_prefix": "PREV76",
            },
        ]

        for idx, prev_conference in enumerate(prev_conferences):
            if idx >= len(conf_configs):
                break
            cfg = conf_configs[idx]
            attendee_count: int = cfg["attendee_count"]  # type: ignore[assignment]
            speaker_count: int = cfg["speaker_count"]  # type: ignore[assignment]
            sponsor_names: list[str] = cfg["sponsors"]  # type: ignore[assignment]
            prices: list[int] = cfg["prices"]  # type: ignore[assignment]
            talk_count: int = cfg["talk_count"]  # type: ignore[assignment]
            ref_prefix: str = cfg["ref_prefix"]  # type: ignore[assignment]

            # Attendees and orders
            prev_users = users[:attendee_count]
            for i, user in enumerate(prev_users):
                att, created = Attendee.objects.get_or_create(
                    user=user, conference=prev_conference, defaults={"completed_registration": True}
                )
                if created:
                    ref = f"{ref_prefix}-{i + 1:04d}"
                    if not Order.objects.filter(reference=ref).exists():
                        total = Decimal(str(self.rng.choice(prices)))
                        order = Order.objects.create(
                            conference=prev_conference,
                            user=user,
                            status=Order.Status.PAID,
                            subtotal=total,
                            total=total,
                            reference=ref,
                            billing_name=f"{user.first_name} {user.last_name}",
                            billing_email=user.email,
                        )
                        att.order = order
                        att.save(update_fields=["order"])

            # Speakers for return-rate tracking
            for i, speaker in enumerate(speakers[:speaker_count]):
                Speaker.objects.get_or_create(
                    conference=prev_conference,
                    pretalx_code=f"{ref_prefix}-SPKR{i + 1:03d}",
                    defaults={
                        "name": str(speaker.name),
                        "email": speaker.email,
                        "user": speaker.user,
                        "synced_at": timezone.now(),
                    },
                )

            # Sponsors for renewal-rate tracking
            prev_level, _ = SponsorLevel.objects.get_or_create(
                conference=prev_conference, slug="gold", defaults={"name": "Gold", "cost": 8000, "order": 0}
            )
            for name in sponsor_names:
                Sponsor.objects.get_or_create(
                    conference=prev_conference,
                    slug=_slugify(name),
                    defaults={"name": name, "level": prev_level, "is_active": True},
                )

            # Talks for content-volume tracking
            prev_speakers = list(Speaker.objects.filter(conference=prev_conference))
            for t_idx in range(talk_count):
                talk_title = TALK_TITLES[t_idx % len(TALK_TITLES)]
                talk, talk_created = Talk.objects.get_or_create(
                    conference=prev_conference,
                    pretalx_code=f"{ref_prefix}-TALK{t_idx + 1:03d}",
                    defaults={
                        "title": talk_title,
                        "track": self.rng.choice(["Web", "Data", "DevOps", "Core"]),
                        "duration": self.rng.choice([30, 45]),
                        "synced_at": timezone.now(),
                    },
                )
                if talk_created and prev_speakers:
                    talk.speakers.add(prev_speakers[t_idx % len(prev_speakers)])

            print(
                f"  {prev_conference.name}: {attendee_count} attendees, "
                f"{speaker_count} speakers, {len(sponsor_names)} sponsors, {talk_count} talks"
            )

    def _create_sponsor_benefits(self, sponsors: list[Sponsor]) -> None:
        """Create sponsor benefits with varying fulfillment status."""
        benefit_templates = [
            ("Logo on website", True),
            ("Booth at conference", True),
            ("Talk slot", False),
            ("Social media mentions", True),
            ("Recruiting table", False),
            ("Newsletter feature", True),
            ("Swag bag insert", True),
            ("Attendee email list", False),
        ]
        count = 0
        for sponsor in sponsors:
            # Higher-tier sponsors get more benefits
            n_benefits = min(len(benefit_templates), 3 + self.rng.randint(0, 5))
            for name, default_complete in benefit_templates[:n_benefits]:
                # ~70% completion rate
                is_complete = default_complete if self.rng.random() < 0.7 else not default_complete
                _, created = SponsorBenefit.objects.get_or_create(
                    sponsor=sponsor,
                    name=name,
                    defaults={"is_complete": is_complete},
                )
                if created:
                    count += 1
        print(f"  Sponsor benefits: {count}")

    def _create_activities_and_signups(self, conference: Conference, users: list, rooms: list[Room]) -> None:
        """Create activities with signups including waitlisted users."""
        activity_defs = [
            ("Sprint: Core Python", "sprint-core", Activity.ActivityType.SPRINT, 25),
            ("Sprint: Django", "sprint-django", Activity.ActivityType.SPRINT, 20),
            ("Workshop: Testing 101", "workshop-testing", Activity.ActivityType.WORKSHOP, 30),
            ("Workshop: Docker Deep Dive", "workshop-docker", Activity.ActivityType.WORKSHOP, 15),
            ("Tutorial: ML Basics", "tutorial-ml", Activity.ActivityType.TUTORIAL, 40),
            ("PyLadies Lunch", "pyladies-lunch", Activity.ActivityType.SOCIAL, 50),
            ("Open Space: Async Python", "open-async", Activity.ActivityType.OPEN_SPACE, None),
            ("Lightning Talks", "lightning", Activity.ActivityType.LIGHTNING_TALK, None),
        ]
        signup_count = 0
        for name, slug, atype, max_p in activity_defs:
            room = self.rng.choice(rooms) if rooms else None
            activity, _ = Activity.objects.get_or_create(
                conference=conference,
                slug=slug,
                defaults={
                    "name": name,
                    "activity_type": atype,
                    "max_participants": max_p,
                    "room": room,
                    "is_active": True,
                    "start_time": timezone.now() + datetime.timedelta(days=self.rng.randint(1, 7)),
                },
            )

            # Create signups: fill to ~80% capacity, some waitlisted
            if max_p:
                n_confirmed = int(max_p * 0.8)
                n_waitlisted = self.rng.randint(2, 8)
            else:
                n_confirmed = self.rng.randint(5, 20)
                n_waitlisted = 0

            shuffled = list(users)
            self.rng.shuffle(shuffled)
            for j, user in enumerate(shuffled[: n_confirmed + n_waitlisted]):
                status = (
                    ActivitySignup.SignupStatus.CONFIRMED if j < n_confirmed else ActivitySignup.SignupStatus.WAITLISTED
                )
                _, created = ActivitySignup.objects.get_or_create(
                    activity=activity,
                    user=user,
                    defaults={"status": status},
                )
                if created:
                    signup_count += 1

        print(f"  Activity signups: {signup_count}")

    def _create_expenses(self, conference: Conference) -> None:
        """Create expense categories and expenses."""
        admin = User.objects.filter(is_superuser=True).first()
        categories = [
            ("Venue & Facilities", "venue", Decimal("18000.00")),
            ("Food & Beverage", "food", Decimal("12000.00")),
            ("Audio/Visual", "av", Decimal("5000.00")),
            ("Marketing", "marketing", Decimal("3000.00")),
            ("Travel & Accommodation", "travel", Decimal("8000.00")),
            ("Swag & Printing", "swag", Decimal("2500.00")),
            ("Miscellaneous", "misc", Decimal("1500.00")),
        ]
        expense_data = {
            "venue": [
                ("Convention center rental (3 days)", Decimal("12000.00"), "Pittsburgh CC", "INV-2027-001"),
                ("Room setup and teardown", Decimal("2500.00"), "EventPro Services", "INV-2027-002"),
                ("Wi-Fi and networking infrastructure", Decimal("1800.00"), "NetConnect", "INV-2027-015"),
            ],
            "food": [
                ("Catered lunch Day 1 (250 pax)", Decimal("3750.00"), "Catering Co", "INV-2027-003"),
                ("Catered lunch Day 2 (230 pax)", Decimal("3450.00"), "Catering Co", "INV-2027-004"),
                ("Catered lunch Day 3 (200 pax)", Decimal("3000.00"), "Catering Co", "INV-2027-005"),
                ("Coffee and snacks (3 days)", Decimal("1200.00"), "Brew Masters", "INV-2027-006"),
                ("Welcome reception appetizers", Decimal("800.00"), "Catering Co", "INV-2027-007"),
            ],
            "av": [
                ("Projector rental (8 rooms)", Decimal("2400.00"), "AV Solutions", "INV-2027-008"),
                ("Live streaming setup", Decimal("1500.00"), "StreamTech", "INV-2027-009"),
                ("Microphones and PA", Decimal("800.00"), "AV Solutions", "INV-2027-010"),
            ],
            "marketing": [
                ("Social media advertising", Decimal("1200.00"), "Meta Ads", ""),
                ("Email marketing platform", Decimal("350.00"), "Mailgun", "INV-2027-011"),
                ("Conference website hosting", Decimal("180.00"), "Vercel", ""),
                ("Printed banners and signage", Decimal("650.00"), "PrintShop", "INV-2027-012"),
            ],
            "travel": [
                ("Keynote speaker travel", Decimal("2800.00"), "Delta Airlines", ""),
                ("Keynote speaker hotel (4 nights)", Decimal("1600.00"), "Marriott Pittsburgh", ""),
                ("Volunteer coordinator travel", Decimal("450.00"), "Southwest Airlines", ""),
            ],
            "swag": [
                ("Conference t-shirts (300 units)", Decimal("1500.00"), "TeeSpring", "INV-2027-013"),
                ("Lanyards and badge holders", Decimal("250.00"), "Badge Co", "INV-2027-014"),
                ("Stickers and swag bags", Decimal("400.00"), "StickerMule", ""),
            ],
            "misc": [
                ("Event insurance", Decimal("800.00"), "EventSure", ""),
                ("Photography", Decimal("500.00"), "Jane Doe Photography", ""),
            ],
        }

        for cat_name, slug, budget in categories:
            cat, _ = ExpenseCategory.objects.get_or_create(
                conference=conference,
                slug=slug,
                defaults={
                    "name": cat_name,
                    "budget_amount": budget,
                    "order": categories.index((cat_name, slug, budget)),
                },
            )
            if slug in expense_data:
                for desc, amount, vendor, receipt_ref in expense_data[slug]:
                    Expense.objects.get_or_create(
                        conference=conference,
                        category=cat,
                        description=desc,
                        defaults={
                            "amount": amount,
                            "vendor": vendor,
                            "date": datetime.date(2027, 4, self.rng.randint(1, 28)),
                            "receipt_reference": receipt_ref,
                            "created_by": admin,
                        },
                    )

    def _create_session_ratings(self, conference: Conference, talks: list[Talk], users: list) -> None:
        """Create session ratings from attendees for talks."""
        count = 0
        for talk in talks[:20]:
            # 5-15 ratings per talk
            n_ratings = self.rng.randint(5, 15)
            shuffled = list(users)
            self.rng.shuffle(shuffled)
            for user in shuffled[:n_ratings]:
                # Bell curve around 3.5-4.0
                score = max(1, min(5, int(self.rng.gauss(3.8, 0.9))))
                _, created = SessionRating.objects.get_or_create(
                    conference=conference,
                    talk=talk,
                    user=user,
                    defaults={"score": score, "comment": "" if self.rng.random() < 0.6 else "Great talk!"},
                )
                if created:
                    count += 1
        print(f"  Session ratings: {count}")

    def _create_surveys(self, conference: Conference, users: list) -> None:
        """Create NPS and satisfaction surveys with responses."""
        # NPS survey
        nps, _ = Survey.objects.get_or_create(
            conference=conference,
            slug="post-event-nps",
            defaults={
                "name": "Post-Event NPS Survey",
                "survey_type": Survey.SurveyType.NPS,
                "is_active": True,
            },
        )
        # Satisfaction survey
        sat, _ = Survey.objects.get_or_create(
            conference=conference,
            slug="overall-satisfaction",
            defaults={
                "name": "Overall Satisfaction",
                "survey_type": Survey.SurveyType.SATISFACTION,
                "is_active": True,
            },
        )

        nps_count = 0
        sat_count = 0
        shuffled = list(users)
        self.rng.shuffle(shuffled)

        # ~40 NPS responses (score 0-10)
        for user in shuffled[:40]:
            score = max(0, min(10, int(self.rng.gauss(7.5, 2.0))))
            _, created = SurveyResponse.objects.get_or_create(survey=nps, user=user, defaults={"score": score})
            if created:
                nps_count += 1

        # ~35 satisfaction responses (score 1-5)
        for user in shuffled[:35]:
            score = max(1, min(5, int(self.rng.gauss(3.8, 0.8))))
            _, created = SurveyResponse.objects.get_or_create(survey=sat, user=user, defaults={"score": score})
            if created:
                sat_count += 1

        print(f"  Survey responses: {nps_count} NPS, {sat_count} satisfaction")

    def _create_travel_grants(self, conference: Conference, users: list) -> None:
        """Create travel grant applications if none exist."""
        if TravelGrant.objects.filter(conference=conference).exists():
            return
        statuses = [
            TravelGrant.GrantStatus.SUBMITTED,
            TravelGrant.GrantStatus.OFFERED,
            TravelGrant.GrantStatus.ACCEPTED,
            TravelGrant.GrantStatus.REJECTED,
            TravelGrant.GrantStatus.DISBURSED,
        ]
        app_types = list(TravelGrant.ApplicationType)
        for i in range(10):
            user = users[50 + i] if 50 + i < len(users) else users[i]
            status = statuses[i % len(statuses)]
            requested = Decimal(str(self.rng.choice([500, 1000, 1500, 2000, 2500])))
            approved = (
                requested * Decimal("0.7")
                if status
                in (
                    TravelGrant.GrantStatus.OFFERED,
                    TravelGrant.GrantStatus.ACCEPTED,
                    TravelGrant.GrantStatus.DISBURSED,
                )
                else None
            )
            disbursed = approved if status == TravelGrant.GrantStatus.DISBURSED else None
            TravelGrant.objects.create(
                conference=conference,
                user=user,
                status=status,
                application_type=app_types[i % len(app_types)],
                requested_amount=requested,
                approved_amount=approved,
                disbursed_amount=disbursed,
                travel_from=self.rng.choice(["New York", "London", "Tokyo", "Berlin", "São Paulo", "Lagos"]),
                international=i % 3 != 0,
                first_time=i % 4 == 0,
            )

    def _create_more_carts(self, conference: Conference, users: list, ticket_types: list, addons: list) -> None:
        """Create more carts for better cart funnel data."""
        now = timezone.now()
        extra_carts = [
            (30, Cart.Status.CHECKED_OUT, None),
            (31, Cart.Status.CHECKED_OUT, None),
            (32, Cart.Status.CHECKED_OUT, None),
            (33, Cart.Status.ABANDONED, now - datetime.timedelta(hours=6)),
            (34, Cart.Status.ABANDONED, now - datetime.timedelta(days=1)),
            (35, Cart.Status.ABANDONED, now - datetime.timedelta(days=3)),
            (36, Cart.Status.EXPIRED, now - datetime.timedelta(days=5)),
            (37, Cart.Status.EXPIRED, now - datetime.timedelta(days=4)),
            (38, Cart.Status.OPEN, now + datetime.timedelta(hours=1)),
            (39, Cart.Status.OPEN, now + datetime.timedelta(hours=3)),
            (40, Cart.Status.CHECKED_OUT, None),
            (41, Cart.Status.CHECKED_OUT, None),
            (42, Cart.Status.ABANDONED, now - datetime.timedelta(hours=18)),
            (43, Cart.Status.EXPIRED, now - datetime.timedelta(days=2)),
            (44, Cart.Status.CHECKED_OUT, None),
        ]
        for user_idx, status, expires in extra_carts:
            if user_idx >= len(users):
                continue
            cart, created = Cart.objects.get_or_create(
                user=users[user_idx],
                conference=conference,
                status=status,
                defaults={"expires_at": expires},
            )
            if created and ticket_types:
                CartItem.objects.create(cart=cart, ticket_type=self.rng.choice(ticket_types), quantity=1)
                if addons and self.rng.random() < 0.4:
                    CartItem.objects.create(cart=cart, addon=self.rng.choice(addons), quantity=1)


    def _create_bulk_purchases(
        self,
        conference: Conference,
        sponsors: list[Sponsor],
        ticket_types: list[TicketType],
        addons: list[AddOn],
        users: list,
    ) -> None:
        """Create bulk purchase deals in various states."""
        from django_program.registration.services.voucher_service import VoucherBulkConfig, generate_voucher_codes

        admin = User.objects.filter(is_superuser=True).first()
        bulk_tickets = [t for t in ticket_types if t.bulk_enabled]
        bulk_addons = [a for a in addons if a.bulk_enabled]

        if not bulk_tickets and not bulk_addons:
            return

        # 1. Fulfilled sponsor deal — 20 corporate tickets at 15% off (PAID + vouchers generated)
        if sponsors and bulk_tickets:
            bp1, created = BulkPurchase.objects.get_or_create(
                conference=conference,
                product_description="MegaCorp Employee Tickets",
                defaults={
                    "sponsor": sponsors[0],
                    "ticket_type": bulk_tickets[0],
                    "quantity": 20,
                    "unit_price": bulk_tickets[0].price,
                    "total_amount": bulk_tickets[0].price * 20,
                    "payment_status": BulkPurchase.PaymentStatus.PAID,
                    "requested_by": admin,
                    "approved_by": admin,
                    "voucher_config": {
                        "voucher_type": "percentage",
                        "discount_value": "15",
                        "max_uses": 1,
                    },
                },
            )
            if created:
                config = VoucherBulkConfig(
                    conference=conference,
                    prefix="MEGA-CORP-",
                    count=20,
                    voucher_type="percentage",
                    discount_value=Decimal("15"),
                    max_uses=1,
                )
                vouchers = generate_voucher_codes(config)
                for v in vouchers:
                    BulkPurchaseVoucher.objects.get_or_create(bulk_purchase=bp1, voucher=v)
                # Mark some as used
                for v in vouchers[:12]:
                    v.times_used = 1
                    v.save(update_fields=["times_used"])

        # 2. T-shirt bulk deal — no sponsor, 50 shirts at $5 off (PAID + fulfilled)
        tshirt = next((a for a in bulk_addons if a.slug == "t-shirt"), None)
        if tshirt:
            bp2, created = BulkPurchase.objects.get_or_create(
                conference=conference,
                product_description="Staff T-Shirt Pack",
                defaults={
                    "addon": tshirt,
                    "quantity": 50,
                    "unit_price": tshirt.price,
                    "total_amount": tshirt.price * 50,
                    "payment_status": BulkPurchase.PaymentStatus.PAID,
                    "requested_by": admin,
                    "approved_by": admin,
                    "voucher_config": {
                        "voucher_type": "fixed_amount",
                        "discount_value": "5",
                        "max_uses": 1,
                    },
                },
            )
            if created:
                config = VoucherBulkConfig(
                    conference=conference,
                    prefix="TSHIRT-",
                    count=50,
                    voucher_type="fixed_amount",
                    discount_value=Decimal("5"),
                    max_uses=1,
                )
                vouchers = generate_voucher_codes(config)
                for v in vouchers:
                    BulkPurchaseVoucher.objects.get_or_create(bulk_purchase=bp2, voucher=v)

        # 3. Tutorial bundle — sponsor deal, pending approval
        tutorial = next((a for a in bulk_addons if a.slug == "tutorial"), None)
        if sponsors and tutorial:
            BulkPurchase.objects.get_or_create(
                conference=conference,
                product_description="DataFlow Tutorial Bundle",
                defaults={
                    "sponsor": sponsors[2] if len(sponsors) > 2 else sponsors[0],
                    "addon": tutorial,
                    "quantity": 10,
                    "unit_price": tutorial.price,
                    "total_amount": tutorial.price * 10,
                    "payment_status": BulkPurchase.PaymentStatus.PENDING,
                    "requested_by": users[5] if len(users) > 5 else None,
                    "voucher_config": {
                        "voucher_type": "comp",
                        "discount_value": "0",
                        "max_uses": 1,
                    },
                },
            )

        # 4. Approved but not yet fulfilled — workshop bulk
        workshop = next((a for a in bulk_addons if a.slug == "workshop"), None)
        if workshop:
            BulkPurchase.objects.get_or_create(
                conference=conference,
                product_description="Community Sprint Passes",
                defaults={
                    "addon": workshop,
                    "quantity": 15,
                    "unit_price": Decimal("0.00"),
                    "total_amount": Decimal("0.00"),
                    "payment_status": BulkPurchase.PaymentStatus.APPROVED,
                    "requested_by": admin,
                    "approved_by": admin,
                    "voucher_config": {
                        "voucher_type": "comp",
                        "discount_value": "0",
                        "max_uses": 1,
                    },
                },
            )

        # 5. Corporate ticket comp — 5 free tickets for a platinum sponsor
        if len(sponsors) > 3 and bulk_tickets:
            BulkPurchase.objects.get_or_create(
                conference=conference,
                product_description="PyStack Comp Tickets",
                defaults={
                    "sponsor": sponsors[3],
                    "ticket_type": bulk_tickets[0],
                    "quantity": 5,
                    "unit_price": Decimal("0.00"),
                    "total_amount": Decimal("0.00"),
                    "payment_status": BulkPurchase.PaymentStatus.PAID,
                    "requested_by": admin,
                    "approved_by": admin,
                    "voucher_config": {
                        "voucher_type": "comp",
                        "discount_value": "0",
                        "max_uses": 1,
                    },
                },
            )

        print(f"  Bulk purchases: {BulkPurchase.objects.filter(conference=conference).count()}")


if __name__ == "__main__":
    Seeder().run()
