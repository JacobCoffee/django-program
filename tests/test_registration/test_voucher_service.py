"""Tests for voucher bulk generation service."""

import string
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone

from django_program.conference.models import Conference
from django_program.registration.models import AddOn, TicketType, Voucher
from django_program.registration.services.voucher_service import (
    _CODE_LENGTH,
    VoucherBulkConfig,
    _generate_unique_code,
    generate_voucher_codes,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conference(db):
    return Conference.objects.create(
        name="VoucherCon",
        slug="vouchercon",
        start_date=date(2027, 6, 1),
        end_date=date(2027, 6, 3),
        timezone="UTC",
    )


@pytest.fixture
def ticket_type(conference):
    return TicketType.objects.create(
        conference=conference,
        name="General",
        slug="general",
        price=Decimal("100.00"),
    )


@pytest.fixture
def addon(conference):
    return AddOn.objects.create(
        conference=conference,
        name="T-Shirt",
        slug="tshirt",
        price=Decimal("25.00"),
    )


@pytest.fixture
def base_config(conference):
    return VoucherBulkConfig(
        conference=conference,
        prefix="TEST-",
        count=5,
        voucher_type=Voucher.VoucherType.COMP,
        discount_value=Decimal("0.00"),
        max_uses=1,
    )


# ---------------------------------------------------------------------------
# _generate_unique_code tests
# ---------------------------------------------------------------------------


class TestGenerateUniqueCode:
    """Tests for the internal ``_generate_unique_code`` helper."""

    def test_produces_code_with_prefix(self):
        code = _generate_unique_code("SPEAKER-", set())
        assert code.startswith("SPEAKER-")

    def test_code_has_correct_length(self):
        prefix = "PFX-"
        code = _generate_unique_code(prefix, set())
        random_part = code[len(prefix) :]
        assert len(random_part) == _CODE_LENGTH

    def test_code_is_uppercase_alphanumeric(self):
        code = _generate_unique_code("", set())
        allowed = set(string.ascii_uppercase + string.digits)
        assert all(c in allowed for c in code)

    def test_code_with_prefix_is_uppercase_alphanumeric_in_random_part(self):
        prefix = "TEST-"
        code = _generate_unique_code(prefix, set())
        random_part = code[len(prefix) :]
        allowed = set(string.ascii_uppercase + string.digits)
        assert all(c in allowed for c in random_part)

    def test_avoids_existing_codes(self):
        existing = set()
        codes = []
        for _ in range(50):
            code = _generate_unique_code("", existing)
            assert code not in existing
            existing.add(code)
            codes.append(code)
        assert len(set(codes)) == 50

    def test_raises_runtime_error_on_exhaustion(self):
        with patch(
            "django_program.registration.services.voucher_service.secrets.choice",
            return_value="A",
        ):
            existing = {"A" * _CODE_LENGTH}
            with pytest.raises(RuntimeError, match="Failed to generate a unique voucher code"):
                _generate_unique_code("", existing)

    def test_empty_prefix_works(self):
        code = _generate_unique_code("", set())
        assert len(code) == _CODE_LENGTH


# ---------------------------------------------------------------------------
# generate_voucher_codes tests
# ---------------------------------------------------------------------------


class TestGenerateVoucherCodes:
    """Tests for the public ``generate_voucher_codes`` function."""

    def test_creates_correct_number_of_vouchers(self, base_config):
        created = generate_voucher_codes(base_config)
        assert len(created) == 5
        assert Voucher.objects.filter(conference=base_config.conference).count() == 5

    def test_generated_codes_have_correct_prefix(self, base_config):
        created = generate_voucher_codes(base_config)
        for voucher in created:
            assert voucher.code.startswith("TEST-")

    def test_generated_codes_are_uppercase_alphanumeric(self, base_config):
        created = generate_voucher_codes(base_config)
        allowed = set(string.ascii_uppercase + string.digits)
        for voucher in created:
            random_part = voucher.code[len("TEST-") :]
            assert all(c in allowed for c in random_part)

    def test_all_codes_are_unique(self, base_config):
        base_config.count = 50
        created = generate_voucher_codes(base_config)
        codes = [v.code for v in created]
        assert len(set(codes)) == 50

    def test_voucher_fields_match_config(self, conference):
        config = VoucherBulkConfig(
            conference=conference,
            prefix="DISC-",
            count=2,
            voucher_type=Voucher.VoucherType.PERCENTAGE,
            discount_value=Decimal("25.00"),
            max_uses=3,
            unlocks_hidden_tickets=True,
        )
        created = generate_voucher_codes(config)
        for v in created:
            assert v.voucher_type == Voucher.VoucherType.PERCENTAGE
            assert v.discount_value == Decimal("25.00")
            assert v.max_uses == 3
            assert v.unlocks_hidden_tickets is True

    def test_m2m_ticket_types_set_correctly(self, base_config, ticket_type):
        base_config.applicable_ticket_types = TicketType.objects.filter(pk=ticket_type.pk)
        created = generate_voucher_codes(base_config)
        for v in created:
            assert ticket_type in v.applicable_ticket_types.all()

    def test_m2m_addons_set_correctly(self, base_config, addon):
        base_config.applicable_addons = AddOn.objects.filter(pk=addon.pk)
        created = generate_voucher_codes(base_config)
        for v in created:
            assert addon in v.applicable_addons.all()

    def test_m2m_both_ticket_types_and_addons(self, base_config, ticket_type, addon):
        base_config.applicable_ticket_types = TicketType.objects.filter(pk=ticket_type.pk)
        base_config.applicable_addons = AddOn.objects.filter(pk=addon.pk)
        created = generate_voucher_codes(base_config)
        for v in created:
            assert list(v.applicable_ticket_types.all()) == [ticket_type]
            assert list(v.applicable_addons.all()) == [addon]

    def test_m2m_empty_querysets_are_not_set(self, base_config):
        base_config.applicable_ticket_types = TicketType.objects.none()
        base_config.applicable_addons = AddOn.objects.none()
        created = generate_voucher_codes(base_config)
        for v in created:
            assert v.applicable_ticket_types.count() == 0
            assert v.applicable_addons.count() == 0

    def test_m2m_none_querysets_are_not_set(self, base_config):
        base_config.applicable_ticket_types = None
        base_config.applicable_addons = None
        created = generate_voucher_codes(base_config)
        for v in created:
            assert v.applicable_ticket_types.count() == 0
            assert v.applicable_addons.count() == 0

    def test_duplicate_code_prevention(self, conference):
        Voucher.objects.create(
            conference=conference,
            code="EXIST-AAAAAAAA",
            voucher_type=Voucher.VoucherType.COMP,
            discount_value=Decimal("0.00"),
        )
        config = VoucherBulkConfig(
            conference=conference,
            prefix="EXIST-",
            count=3,
            voucher_type=Voucher.VoucherType.COMP,
            discount_value=Decimal("0.00"),
        )
        created = generate_voucher_codes(config)
        assert len(created) == 3
        all_codes = list(Voucher.objects.filter(conference=conference).values_list("code", flat=True))
        assert len(set(all_codes)) == 4  # 1 existing + 3 new

    def test_generated_codes_use_specified_prefix(self, conference):
        """Verify generated codes start with the configured prefix."""
        Voucher.objects.create(
            conference=conference,
            code="OTHER-12345678",
            voucher_type=Voucher.VoucherType.COMP,
            discount_value=Decimal("0.00"),
        )
        config = VoucherBulkConfig(
            conference=conference,
            prefix="NEW-",
            count=2,
            voucher_type=Voucher.VoucherType.COMP,
            discount_value=Decimal("0.00"),
        )
        created = generate_voucher_codes(config)
        assert len(created) == 2
        for v in created:
            assert v.code.startswith("NEW-")

    def test_count_zero_raises_value_error(self, conference):
        config = VoucherBulkConfig(
            conference=conference,
            prefix="BAD-",
            count=0,
            voucher_type=Voucher.VoucherType.COMP,
            discount_value=Decimal("0.00"),
        )
        with pytest.raises(ValueError, match="count must be between 1 and 500"):
            generate_voucher_codes(config)

    def test_count_negative_raises_value_error(self, conference):
        config = VoucherBulkConfig(
            conference=conference,
            prefix="BAD-",
            count=-1,
            voucher_type=Voucher.VoucherType.COMP,
            discount_value=Decimal("0.00"),
        )
        with pytest.raises(ValueError, match="count must be between 1 and 500"):
            generate_voucher_codes(config)

    def test_count_over_500_raises_value_error(self, conference):
        config = VoucherBulkConfig(
            conference=conference,
            prefix="BAD-",
            count=501,
            voucher_type=Voucher.VoucherType.COMP,
            discount_value=Decimal("0.00"),
        )
        with pytest.raises(ValueError, match="count must be between 1 and 500"):
            generate_voucher_codes(config)

    def test_count_exactly_1_succeeds(self, conference):
        config = VoucherBulkConfig(
            conference=conference,
            prefix="ONE-",
            count=1,
            voucher_type=Voucher.VoucherType.COMP,
            discount_value=Decimal("0.00"),
        )
        created = generate_voucher_codes(config)
        assert len(created) == 1

    def test_count_exactly_500_succeeds(self, conference):
        config = VoucherBulkConfig(
            conference=conference,
            prefix="MAX-",
            count=500,
            voucher_type=Voucher.VoucherType.COMP,
            discount_value=Decimal("0.00"),
        )
        created = generate_voucher_codes(config)
        assert len(created) == 500

    def test_valid_from_and_until_propagated(self, conference):
        now = timezone.now()
        config = VoucherBulkConfig(
            conference=conference,
            prefix="DATE-",
            count=2,
            voucher_type=Voucher.VoucherType.PERCENTAGE,
            discount_value=Decimal("10.00"),
            valid_from=now,
            valid_until=now,
        )
        created = generate_voucher_codes(config)
        for v in created:
            assert v.valid_from == now
            assert v.valid_until == now

    def test_empty_prefix(self, conference):
        config = VoucherBulkConfig(
            conference=conference,
            prefix="",
            count=3,
            voucher_type=Voucher.VoucherType.COMP,
            discount_value=Decimal("0.00"),
        )
        created = generate_voucher_codes(config)
        assert len(created) == 3
        for v in created:
            assert len(v.code) == _CODE_LENGTH


# ---------------------------------------------------------------------------
# VoucherBulkConfig dataclass tests
# ---------------------------------------------------------------------------


class TestVoucherBulkConfig:
    """Tests for the ``VoucherBulkConfig`` dataclass defaults."""

    def test_defaults(self, conference):
        config = VoucherBulkConfig(
            conference=conference,
            prefix="X-",
            count=1,
            voucher_type="comp",
            discount_value=Decimal("0.00"),
        )
        assert config.max_uses == 1
        assert config.valid_from is None
        assert config.valid_until is None
        assert config.unlocks_hidden_tickets is False
        assert config.applicable_ticket_types is None
        assert config.applicable_addons is None
