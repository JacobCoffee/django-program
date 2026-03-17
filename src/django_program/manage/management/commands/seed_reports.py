"""Management command to seed the database with sample data for testing admin reports."""

import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from django_program.conference.models import Conference
from django_program.registration.conditions import (
    DiscountForProduct,
    TimeOrStockLimitCondition,
)
from django_program.registration.models import (
    AddOn,
    Attendee,
    Order,
    OrderLineItem,
    Payment,
    TicketType,
    Voucher,
)

User = get_user_model()

FAKE_USERS = [
    ("alice", "Alice", "Johnson", "alice.johnson@example.com"),
    ("bob", "Bob", "Williams", "bob.williams@example.com"),
    ("carol", "Carol", "Martinez", "carol.martinez@example.com"),
    ("dan", "Dan", "Thompson", "dan.thompson@example.com"),
    ("eva", "Eva", "Nakamura", "eva.nakamura@example.com"),
    ("frank", "Frank", "Okafor", "frank.okafor@example.com"),
    ("grace", "Grace", "Chen", "grace.chen@example.com"),
    ("hank", "Hank", "Petrov", "hank.petrov@example.com"),
    ("iris", "Iris", "Dubois", "iris.dubois@example.com"),
    ("jake", "Jake", "Fernandez", "jake.fernandez@example.com"),
    ("kira", "Kira", "Svensson", "kira.svensson@example.com"),
    ("leo", "Leo", "Gupta", "leo.gupta@example.com"),
]

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
    ("SPEAKER2027", "comp", Decimal(0), 30, 8),
    ("EARLY20", "percentage", Decimal(20), 50, 23),
    ("SPONSOR50", "fixed_amount", Decimal(50), 20, 5),
    ("VOLUNTEER", "comp", Decimal(0), 15, 12),
    ("STUDENT10", "percentage", Decimal(10), 100, 41),
    ("FLASH25", "fixed_amount", Decimal(25), 10, 10),
]


class Command(BaseCommand):
    """Seed database with sample data for testing admin reports."""

    help = "Seed database with sample data for testing admin reports"

    def handle(self, *args: object, **kwargs: object) -> None:
        """Create conferences, tickets, orders, attendees, and discount conditions."""
        self.stdout.write("Seeding report test data...")

        self._create_superuser()
        conference = self._create_conference()
        ticket_types = self._create_ticket_types(conference)
        addons = self._create_addons(conference)
        vouchers = self._create_vouchers(conference)
        users = self._create_users()
        self._create_orders(conference, users, ticket_types, addons, vouchers)
        self._create_discount_conditions(conference, ticket_types)

        self.stdout.write(self.style.SUCCESS(f"Seeded data for {conference.name}:"))
        self.stdout.write("  Admin user: admin / admin")
        self.stdout.write(f"  Conference: {conference.slug}")
        self.stdout.write(f"  Ticket types: {len(ticket_types)}")
        self.stdout.write(f"  Add-ons: {len(addons)}")
        self.stdout.write(f"  Vouchers: {len(vouchers)}")
        self.stdout.write(f"  Users: {len(users)} + 1 admin")
        self.stdout.write("  Orders, attendees, and conditions created.")

    def _create_superuser(self) -> object:
        """Create the admin superuser if it does not exist."""
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
            self.stdout.write("  Created superuser: admin / admin")
        else:
            self.stdout.write("  Superuser 'admin' already exists")
        return admin

    def _create_conference(self) -> Conference:
        """Create or get the PyCon 2027 conference."""
        conference, created = Conference.objects.get_or_create(
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
        if created:
            self.stdout.write("  Created conference: PyCon US 2027")
        else:
            self.stdout.write("  Conference 'pycon-2027' already exists")
        return conference

    def _create_ticket_types(self, conference: Conference) -> list[TicketType]:
        """Create ticket types for the conference."""
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
        self.stdout.write(f"  Ticket types: {len(result)}")
        return result

    def _create_addons(self, conference: Conference) -> list[AddOn]:
        """Create add-on products for the conference."""
        result = []
        for idx, (name, slug, price) in enumerate(ADDONS):
            addon, _ = AddOn.objects.get_or_create(
                conference=conference,
                slug=slug,
                defaults={
                    "name": name,
                    "price": price,
                    "order": idx,
                    "is_active": True,
                },
            )
            result.append(addon)
        self.stdout.write(f"  Add-ons: {len(result)}")
        return result

    def _create_vouchers(self, conference: Conference) -> list[Voucher]:
        """Create voucher codes with varying types and usage counts."""
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
        self.stdout.write(f"  Vouchers: {len(result)}")
        return result

    def _create_users(self) -> list[object]:
        """Create fake attendee users."""
        result = []
        for username, first, last, email in FAKE_USERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": email,
                    "first_name": first,
                    "last_name": last,
                },
            )
            if created:
                user.set_password("testpass123")
                user.save()
            result.append(user)
        self.stdout.write(f"  Users: {len(result)}")
        return result

    def _create_orders(
        self,
        conference: Conference,
        users: list[object],
        ticket_types: list[TicketType],
        addons: list[AddOn],
        vouchers: list[Voucher],
    ) -> None:
        """Create orders with line items, payments, and attendee records."""
        now = timezone.now()
        order_configs = [
            # (user_idx, ref, status, ticket_idx, addon_indices, voucher_idx, days_ago)
            (0, "ORD-SEED-001", "paid", 0, [0, 2], None, 30),
            (1, "ORD-SEED-002", "paid", 1, [1], None, 25),
            (2, "ORD-SEED-003", "paid", 2, [2], 4, 22),
            (3, "ORD-SEED-004", "paid", 3, [0, 1, 2], None, 20),
            (4, "ORD-SEED-005", "paid", 4, [], 0, 18),
            (5, "ORD-SEED-006", "pending", 1, [1, 2], None, 5),
            (6, "ORD-SEED-007", "cancelled", 0, [0], None, 15),
            (7, "ORD-SEED-008", "paid", 1, [2, 3], None, 12),
            (8, "ORD-SEED-009", "paid", 2, [], 4, 10),
            (9, "ORD-SEED-010", "pending", 3, [0, 1], None, 3),
            (10, "ORD-SEED-011", "paid", 0, [1, 2, 3], 1, 8),
            (11, "ORD-SEED-012", "cancelled", 1, [], None, 7),
            (0, "ORD-SEED-013", "paid", 1, [3], None, 2),
            (3, "ORD-SEED-014", "paid", 2, [1], 4, 1),
        ]

        checked_in_refs = {"ORD-SEED-001", "ORD-SEED-002", "ORD-SEED-004", "ORD-SEED-008", "ORD-SEED-011"}

        for user_idx, ref, status, tt_idx, addon_idxs, voucher_idx, days_ago in order_configs:
            user = users[user_idx]
            ticket = ticket_types[tt_idx]
            created_at = now - datetime.timedelta(days=days_ago)

            subtotal = ticket.price
            for ai in addon_idxs:
                subtotal += addons[ai].price

            discount = Decimal("0.00")
            voucher_code = ""
            if voucher_idx is not None:
                v = vouchers[voucher_idx]
                voucher_code = v.code
                if v.voucher_type == "comp":
                    discount = subtotal
                elif v.voucher_type == "percentage":
                    discount = (subtotal * v.discount_value / Decimal(100)).quantize(Decimal("0.01"))
                elif v.voucher_type == "fixed_amount":
                    discount = min(v.discount_value, subtotal)

            total = max(subtotal - discount, Decimal("0.00"))

            order, created = Order.objects.get_or_create(
                reference=ref,
                defaults={
                    "conference": conference,
                    "user": user,
                    "status": status,
                    "subtotal": subtotal,
                    "discount_amount": discount,
                    "total": total,
                    "voucher_code": voucher_code,
                    "billing_name": f"{user.first_name} {user.last_name}",
                    "billing_email": user.email,
                },
            )
            if not created:
                continue

            OrderLineItem.objects.create(
                order=order,
                description=ticket.name,
                quantity=1,
                unit_price=ticket.price,
                line_total=ticket.price,
                ticket_type=ticket,
            )
            for ai in addon_idxs:
                addon = addons[ai]
                OrderLineItem.objects.create(
                    order=order,
                    description=addon.name,
                    quantity=1,
                    unit_price=addon.price,
                    line_total=addon.price,
                    addon=addon,
                )

            if status == "paid":
                self._create_payment(order, ref, total)
                self._create_attendee(user, conference, order, ref, created_at, checked_in_refs)

        self.stdout.write(f"  Orders: {len(order_configs)}")

    def _create_payment(self, order: Order, ref: str, total: Decimal) -> None:
        """Create a payment record for a paid order."""
        method = Payment.Method.COMP if total == 0 else Payment.Method.STRIPE
        pi_id = f"pi_seed_{ref.lower().replace('-', '_')}" if method == Payment.Method.STRIPE else ""
        Payment.objects.create(
            order=order,
            method=method,
            status=Payment.Status.SUCCEEDED,
            amount=total,
            stripe_payment_intent_id=pi_id,
        )

    def _create_attendee(  # noqa: PLR0913
        self,
        user: object,
        conference: Conference,
        order: Order,
        ref: str,
        created_at: datetime.datetime,
        checked_in_refs: set[str],
    ) -> None:
        """Create an attendee record and optionally check them in."""
        attendee, _ = Attendee.objects.get_or_create(
            user=user,
            conference=conference,
            defaults={"order": order},
        )

        if ref in checked_in_refs:
            attendee.checked_in_at = created_at + datetime.timedelta(hours=9)
            attendee.save(update_fields=["checked_in_at"])

    def _create_discount_conditions(self, conference: Conference, ticket_types: list[TicketType]) -> None:
        """Create time/stock and product discount conditions."""
        now = timezone.now()

        early_bird, created = TimeOrStockLimitCondition.objects.get_or_create(
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
            early_bird.applicable_ticket_types.set([tt for tt in ticket_types if tt.slug in ("regular", "early-bird")])

        product_discount, created = DiscountForProduct.objects.get_or_create(
            conference=conference,
            name="Tutorial Bundle Savings",
            defaults={
                "description": "$25 off when purchasing a tutorial add-on with any ticket",
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
            product_discount.applicable_ticket_types.set(ticket_types)

        self.stdout.write("  Discount conditions: 2")
