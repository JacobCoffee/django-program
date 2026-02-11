"""Integration tests for bootstrap_conference ticket/addon/voucher/demo seeding."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command

from django_program.conference.models import Conference, Section
from django_program.registration.models import (
    AddOn,
    Cart,
    Credit,
    Order,
    Payment,
    TicketType,
    Voucher,
)

User = get_user_model()

_FULL_CONFIG = """\
[conference]
name = "TestCon"
start = 2027-06-01
end = 2027-06-05
timezone = "UTC"

[[conference.sections]]
name = "Talks"
start = 2027-06-01
end = 2027-06-03

[[conference.sections]]
name = "Sprints"
start = 2027-06-04
end = 2027-06-05

[[conference.tickets]]
name = "Individual"
price = 100.00
quantity = 500
per_user = 1
available = { opens = 2027-01-01, closes = 2027-05-31 }

[[conference.tickets]]
name = "Corporate"
price = 350.00
quantity = 200
per_user = 1

[[conference.tickets]]
name = "Speaker"
price = 0.00
quantity = 50
per_user = 1
voucher_required = true

[[conference.addons]]
name = "Workshop"
price = 75.00
quantity = 40
requires = ["individual", "corporate"]

[[conference.addons]]
name = "PyCon T-Shirt"
price = 25.00
quantity = 1000
"""


def _write_config(tmp_path, contents=_FULL_CONFIG):
    path = tmp_path / "conf.toml"
    path.write_text(contents)
    return str(path)


# ---------------------------------------------------------------
# Bootstrap: tickets & addons
# ---------------------------------------------------------------


@pytest.mark.django_db
class TestBootstrapRegistration:
    def test_creates_ticket_types(self, tmp_path):
        call_command("bootstrap_conference", config=_write_config(tmp_path))

        conf = Conference.objects.get(slug="testcon")
        tickets = list(TicketType.objects.filter(conference=conf).order_by("order"))

        assert len(tickets) == 3
        assert tickets[0].name == "Individual"
        assert tickets[0].price == Decimal("100.00")
        assert tickets[0].total_quantity == 500
        assert tickets[0].limit_per_user == 1
        assert tickets[0].available_from is not None
        assert tickets[0].available_until is not None

        assert tickets[2].name == "Speaker"
        assert tickets[2].requires_voucher is True
        assert tickets[2].price == Decimal("0.00")

    def test_creates_addons_with_m2m(self, tmp_path):
        call_command("bootstrap_conference", config=_write_config(tmp_path))

        conf = Conference.objects.get(slug="testcon")
        workshop = AddOn.objects.get(conference=conf, slug="workshop")
        tshirt = AddOn.objects.get(conference=conf, slug="pycon-t-shirt")

        assert workshop.price == Decimal("75.00")
        assert workshop.total_quantity == 40
        required_slugs = set(workshop.requires_ticket_types.values_list("slug", flat=True))
        assert required_slugs == {"individual", "corporate"}

        assert tshirt.requires_ticket_types.count() == 0

    def test_update_is_idempotent(self, tmp_path):
        config = _write_config(tmp_path)
        call_command("bootstrap_conference", config=config)
        call_command("bootstrap_conference", config=config, update=True)

        conf = Conference.objects.get(slug="testcon")
        assert TicketType.objects.filter(conference=conf).count() == 3
        assert AddOn.objects.filter(conference=conf).count() == 2
        assert Section.objects.filter(conference=conf).count() == 2

    def test_dry_run_creates_nothing(self, tmp_path):
        call_command("bootstrap_conference", config=_write_config(tmp_path), dry_run=True)

        assert Conference.objects.count() == 0
        assert TicketType.objects.count() == 0
        assert AddOn.objects.count() == 0


# ---------------------------------------------------------------
# --seed-demo
# ---------------------------------------------------------------


@pytest.mark.django_db
class TestSeedDemo:
    def _bootstrap_with_demo(self, tmp_path):
        call_command("bootstrap_conference", config=_write_config(tmp_path), seed_demo=True)
        return Conference.objects.get(slug="testcon")

    def test_creates_vouchers(self, tmp_path):
        conf = self._bootstrap_with_demo(tmp_path)
        vouchers = Voucher.objects.filter(conference=conf)

        assert vouchers.count() == 4
        codes = [v.code for v in vouchers]
        assert any(c.startswith("SPKR-") for c in codes)
        assert any(c.startswith("STU-") for c in codes)
        assert any(c.startswith("EARLY-") for c in codes)
        assert any(c.startswith("SAVE25-") for c in codes)

        speaker_voucher = vouchers.get(code__startswith="SPKR-")
        assert speaker_voucher.voucher_type == Voucher.VoucherType.COMP
        assert speaker_voucher.unlocks_hidden_tickets is True
        assert speaker_voucher.max_uses == 200

        early_voucher = vouchers.get(code__startswith="EARLY-")
        assert early_voucher.voucher_type == Voucher.VoucherType.PERCENTAGE
        assert early_voucher.discount_value == Decimal(20)

    def test_creates_demo_users(self, tmp_path):
        self._bootstrap_with_demo(tmp_path)

        assert User.objects.filter(username="attendee_alice").exists()
        assert User.objects.filter(username="attendee_bob").exists()
        assert User.objects.filter(username="speaker_carol").exists()

        alice = User.objects.get(username="attendee_alice")
        assert alice.is_staff is True
        assert alice.check_password("demo")

    def test_creates_orders_with_line_items_and_payments(self, tmp_path):
        conf = self._bootstrap_with_demo(tmp_path)
        orders = Order.objects.filter(conference=conf)

        assert orders.count() == 3

        alice_order = orders.get(user__username="attendee_alice")
        assert alice_order.status == Order.Status.PAID
        assert alice_order.total > Decimal(0)
        assert alice_order.line_items.count() >= 1
        assert alice_order.payments.count() == 1
        assert alice_order.payments.first().method == Payment.Method.STRIPE

        carol_order = orders.get(user__username="speaker_carol")
        assert carol_order.total == Decimal(0)
        assert carol_order.payments.first().method == Payment.Method.COMP

    def test_creates_open_cart(self, tmp_path):
        conf = self._bootstrap_with_demo(tmp_path)

        cart = Cart.objects.get(conference=conf, user__username="attendee_bob")
        assert cart.status == Cart.Status.OPEN
        assert cart.items.count() >= 1

        ticket_item = cart.items.filter(ticket_type__isnull=False).first()
        assert ticket_item is not None
        assert ticket_item.quantity == 1

    def test_creates_credit(self, tmp_path):
        conf = self._bootstrap_with_demo(tmp_path)

        credit = Credit.objects.get(conference=conf, user__username="attendee_alice")
        assert credit.amount == Decimal("25.00")
        assert credit.status == Credit.Status.AVAILABLE

    def test_seed_demo_is_idempotent(self, tmp_path):
        config = _write_config(tmp_path)
        call_command("bootstrap_conference", config=config, seed_demo=True)
        call_command("bootstrap_conference", config=config, update=True, seed_demo=True)

        conf = Conference.objects.get(slug="testcon")
        assert Voucher.objects.filter(conference=conf).count() == 4
        assert Order.objects.filter(conference=conf).count() == 3
        assert Cart.objects.filter(conference=conf).count() == 1
        assert Credit.objects.filter(conference=conf).count() == 1


# ---------------------------------------------------------------
# setup_groups
# ---------------------------------------------------------------


@pytest.mark.django_db
class TestSetupGroups:
    def test_creates_all_groups(self):
        call_command("setup_groups")

        expected = [
            "Program: Conference Organizers",
            "Program: Registration & Ticket Support",
            "Program: Finance & Accounting",
            "Program: Read-Only Staff",
        ]
        for name in expected:
            assert Group.objects.filter(name=name).exists(), f"Group '{name}' not created"

    def test_groups_have_permissions(self):
        call_command("setup_groups")

        organizers = Group.objects.get(name="Program: Conference Organizers")
        assert organizers.permissions.count() > 0

        readonly = Group.objects.get(name="Program: Read-Only Staff")
        codenames = set(readonly.permissions.values_list("codename", flat=True))
        assert all(c.startswith("view_") for c in codenames)

    def test_idempotent(self):
        call_command("setup_groups")
        call_command("setup_groups")

        assert Group.objects.filter(name__startswith="Program:").count() == 4


# ---------------------------------------------------------------
# Encrypted fields
# ---------------------------------------------------------------


@pytest.mark.django_db
class TestEncryptedFields:
    def test_stripe_keys_round_trip(self):
        conf = Conference.objects.create(
            name="Encrypt Test",
            slug="encrypt-test",
            start_date="2027-01-01",
            end_date="2027-01-02",
            stripe_secret_key="sk_test_abc123",
            stripe_publishable_key="pk_test_xyz789",
            stripe_webhook_secret="whsec_secret456",
        )

        reloaded = Conference.objects.get(pk=conf.pk)
        assert reloaded.stripe_secret_key == "sk_test_abc123"
        assert reloaded.stripe_publishable_key == "pk_test_xyz789"
        assert reloaded.stripe_webhook_secret == "whsec_secret456"

    def test_empty_encrypted_fields_are_none(self):
        conf = Conference.objects.create(
            name="No Stripe",
            slug="no-stripe",
            start_date="2027-01-01",
            end_date="2027-01-02",
        )

        reloaded = Conference.objects.get(pk=conf.pk)
        assert reloaded.stripe_secret_key is None
        assert reloaded.stripe_publishable_key is None
        assert reloaded.stripe_webhook_secret is None


# ---------------------------------------------------------------
# Admin smoke tests
# ---------------------------------------------------------------


@pytest.mark.django_db
class TestAdminLoads:
    @pytest.fixture
    def admin_client(self, client):
        user = User.objects.create_superuser("testadmin", "admin@test.com", "testpass")
        client.force_login(user)
        return client

    @pytest.fixture
    def conference(self, tmp_path):
        call_command("bootstrap_conference", config=_write_config(tmp_path), seed_demo=True)
        return Conference.objects.get(slug="testcon")

    ADMIN_LIST_URLS = [
        "/admin/program_conference/conference/",
        "/admin/program_conference/section/",
        "/admin/program_registration/tickettype/",
        "/admin/program_registration/addon/",
        "/admin/program_registration/voucher/",
        "/admin/program_registration/cart/",
        "/admin/program_registration/order/",
        "/admin/program_registration/credit/",
    ]

    @pytest.mark.parametrize("url", ADMIN_LIST_URLS)
    def test_admin_changelist_loads(self, admin_client, conference, url):
        response = admin_client.get(url)
        assert response.status_code == 200

    def test_admin_conference_change_loads(self, admin_client, conference):
        response = admin_client.get(f"/admin/program_conference/conference/{conference.pk}/change/")
        assert response.status_code == 200
        content = response.content.decode()
        assert 'type="password"' in content
