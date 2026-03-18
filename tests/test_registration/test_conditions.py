"""Tests for the discount and condition engine."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone

from django_program.conference.models import Conference
from django_program.pretalx.models import Speaker, Talk
from django_program.registration.conditions import (
    DiscountEffect,
    DiscountForCategory,
    DiscountForProduct,
    GroupMemberCondition,
    IncludedProductCondition,
    SpeakerCondition,
    TimeOrStockLimitCondition,
)
from django_program.registration.models import (
    AddOn,
    Cart,
    CartItem,
    Order,
    OrderLineItem,
    TicketType,
    Voucher,
)
from django_program.registration.services.cart import get_summary
from django_program.registration.services.conditions import (
    evaluate_for_cart,
    get_eligible_discounts,
    get_visible_products,
)

User = get_user_model()


# -- Helpers ------------------------------------------------------------------


def _make_order(*, conference, user, status, reference=None):
    return Order.objects.create(
        conference=conference,
        user=user,
        status=status,
        subtotal=Decimal("0.00"),
        total=Decimal("0.00"),
        reference=reference or f"ORD-{uuid4().hex[:8].upper()}",
    )


# -- Fixtures -----------------------------------------------------------------


@pytest.fixture
def conference():
    return Conference.objects.create(
        name="TestCon",
        slug=f"testcon-cond-{uuid4().hex[:6]}",
        start_date=date(2027, 6, 1),
        end_date=date(2027, 6, 3),
        timezone="UTC",
    )


@pytest.fixture
def user():
    return User.objects.create_user(
        username=f"conduser-{uuid4().hex[:6]}",
        email="cond@example.com",
        password="testpass123",
    )


@pytest.fixture
def other_user():
    return User.objects.create_user(
        username=f"otheruser-{uuid4().hex[:6]}",
        email="other-cond@example.com",
        password="testpass123",
    )


@pytest.fixture
def ticket_type(conference):
    return TicketType.objects.create(
        conference=conference,
        name="General",
        slug="general",
        price=Decimal("100.00"),
        total_quantity=0,
        limit_per_user=10,
        is_active=True,
    )


@pytest.fixture
def addon(conference):
    return AddOn.objects.create(
        conference=conference,
        name="T-Shirt",
        slug="tshirt",
        price=Decimal("25.00"),
        is_active=True,
    )


@pytest.fixture
def cart(user, conference):
    return Cart.objects.create(
        user=user,
        conference=conference,
        status=Cart.Status.OPEN,
        expires_at=timezone.now() + timedelta(minutes=30),
    )


# =============================================================================
# DiscountEffect.calculate_discount tests
# =============================================================================


class TestDiscountEffectCalculation:
    """Tests for DiscountEffect.calculate_discount (via a concrete subclass)."""

    @pytest.mark.django_db
    def test_percentage_discount(self, conference):
        condition = TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="20% off",
            discount_type=DiscountEffect.DiscountType.PERCENTAGE,
            discount_value=Decimal("20.00"),
        )
        result = condition.calculate_discount(Decimal("100.00"), 2)
        assert result == Decimal("40.00")

    @pytest.mark.django_db
    def test_fixed_amount_discount(self, conference):
        condition = TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="$10 off",
            discount_type=DiscountEffect.DiscountType.FIXED_AMOUNT,
            discount_value=Decimal("10.00"),
        )
        result = condition.calculate_discount(Decimal("100.00"), 2)
        assert result == Decimal("20.00")

    @pytest.mark.django_db
    def test_fixed_amount_capped_at_line_total(self, conference):
        condition = TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="$200 off",
            discount_type=DiscountEffect.DiscountType.FIXED_AMOUNT,
            discount_value=Decimal("200.00"),
        )
        result = condition.calculate_discount(Decimal("50.00"), 1)
        assert result == Decimal("50.00")

    @pytest.mark.django_db
    def test_max_quantity_limits_discount(self, conference):
        condition = TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="50% off first 2",
            discount_type=DiscountEffect.DiscountType.PERCENTAGE,
            discount_value=Decimal("50.00"),
            max_quantity=2,
        )
        result = condition.calculate_discount(Decimal("100.00"), 5)
        assert result == Decimal("100.00")  # 50% of (100 * 2)

    @pytest.mark.django_db
    def test_percentage_100_is_full_comp(self, conference):
        condition = TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="Comp",
            discount_type=DiscountEffect.DiscountType.PERCENTAGE,
            discount_value=Decimal("100.00"),
        )
        result = condition.calculate_discount(Decimal("150.00"), 1)
        assert result == Decimal("150.00")


# =============================================================================
# TimeOrStockLimitCondition tests
# =============================================================================


class TestTimeOrStockLimitCondition:
    """Tests for time-window and stock-limited conditions."""

    @pytest.mark.django_db
    def test_evaluates_true_within_window(self, conference, user):
        now = timezone.now()
        condition = TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="Early Bird",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
        )
        assert condition.evaluate(user, conference) is True

    @pytest.mark.django_db
    def test_evaluates_false_before_window(self, conference, user):
        now = timezone.now()
        condition = TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="Future Discount",
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
        )
        assert condition.evaluate(user, conference) is False

    @pytest.mark.django_db
    def test_evaluates_false_after_window(self, conference, user):
        now = timezone.now()
        condition = TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="Expired Discount",
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
        )
        assert condition.evaluate(user, conference) is False

    @pytest.mark.django_db
    def test_evaluates_false_when_stock_exhausted(self, conference, user):
        condition = TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="Limited",
            limit=5,
            times_used=5,
        )
        assert condition.evaluate(user, conference) is False

    @pytest.mark.django_db
    def test_evaluates_true_when_stock_remaining(self, conference, user):
        condition = TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="Limited",
            limit=5,
            times_used=3,
        )
        assert condition.evaluate(user, conference) is True

    @pytest.mark.django_db
    def test_unlimited_stock(self, conference, user):
        condition = TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="Unlimited",
            limit=0,
            times_used=999,
        )
        assert condition.evaluate(user, conference) is True

    @pytest.mark.django_db
    def test_no_time_constraints(self, conference, user):
        condition = TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="Always Active",
        )
        assert condition.evaluate(user, conference) is True


# =============================================================================
# SpeakerCondition tests
# =============================================================================


class TestSpeakerCondition:
    """Tests for speaker-based conditions."""

    @pytest.mark.django_db
    def test_evaluates_true_for_linked_speaker(self, conference, user):
        speaker = Speaker.objects.create(
            conference=conference,
            pretalx_code="SPKR001",
            name="Test Speaker",
            user=user,
        )
        talk = Talk.objects.create(
            conference=conference,
            pretalx_code="TALK001",
            title="Test Talk",
        )
        talk.speakers.add(speaker)

        condition = SpeakerCondition.objects.create(
            conference=conference,
            name="Speaker Comp",
            is_presenter=True,
            discount_type=DiscountEffect.DiscountType.PERCENTAGE,
            discount_value=Decimal("100.00"),
        )
        assert condition.evaluate(user, conference) is True

    @pytest.mark.django_db
    def test_evaluates_false_for_non_speaker(self, conference, user):
        condition = SpeakerCondition.objects.create(
            conference=conference,
            name="Speaker Comp",
            is_presenter=True,
        )
        assert condition.evaluate(user, conference) is False

    @pytest.mark.django_db
    def test_copresenter_flag(self, conference, user, other_user):
        primary_speaker = Speaker.objects.create(
            conference=conference,
            pretalx_code="SPKR-PRI",
            name="Primary Speaker",
            user=other_user,
        )
        co_speaker = Speaker.objects.create(
            conference=conference,
            pretalx_code="SPKR-CO",
            name="Co Speaker",
            user=user,
        )
        talk = Talk.objects.create(
            conference=conference,
            pretalx_code="TALK-CO",
            title="Joint Talk",
        )
        talk.speakers.add(primary_speaker, co_speaker)

        # is_presenter=True means any linked speaker qualifies (Pretalx has no
        # explicit primary role, so we don't distinguish presenter vs copresenter
        # when is_presenter is set)
        condition = SpeakerCondition.objects.create(
            conference=conference,
            name="Presenter Flag",
            is_presenter=True,
            is_copresenter=False,
        )
        assert condition.evaluate(user, conference) is True

        # is_copresenter only - qualifies when speaker is on a multi-speaker talk
        condition2 = SpeakerCondition.objects.create(
            conference=conference,
            name="Copresenter Only",
            is_presenter=False,
            is_copresenter=True,
        )
        assert condition2.evaluate(user, conference) is True

    @pytest.mark.django_db
    def test_both_presenter_and_copresenter(self, conference, user):
        speaker = Speaker.objects.create(
            conference=conference,
            pretalx_code="SPKR-BOTH",
            name="Any Speaker",
            user=user,
        )
        condition = SpeakerCondition.objects.create(
            conference=conference,
            name="Any Speaker Role",
            is_presenter=True,
            is_copresenter=True,
        )
        assert condition.evaluate(user, conference) is True


# =============================================================================
# GroupMemberCondition tests
# =============================================================================


class TestGroupMemberCondition:
    """Tests for group-membership-based conditions."""

    @pytest.mark.django_db
    def test_evaluates_true_for_group_member(self, conference, user):
        group = Group.objects.create(name=f"staff-{uuid4().hex[:6]}")
        user.groups.add(group)

        condition = GroupMemberCondition.objects.create(
            conference=conference,
            name="Staff Discount",
            discount_type=DiscountEffect.DiscountType.PERCENTAGE,
            discount_value=Decimal("50.00"),
        )
        condition.groups.add(group)
        assert condition.evaluate(user, conference) is True

    @pytest.mark.django_db
    def test_evaluates_false_for_non_member(self, conference, user):
        group = Group.objects.create(name=f"vip-{uuid4().hex[:6]}")

        condition = GroupMemberCondition.objects.create(
            conference=conference,
            name="VIP Discount",
        )
        condition.groups.add(group)
        assert condition.evaluate(user, conference) is False

    @pytest.mark.django_db
    def test_evaluates_false_with_no_groups_configured(self, conference, user):
        condition = GroupMemberCondition.objects.create(
            conference=conference,
            name="Empty Groups",
        )
        assert condition.evaluate(user, conference) is False


# =============================================================================
# IncludedProductCondition tests
# =============================================================================


class TestIncludedProductCondition:
    """Tests for included-product conditions."""

    @pytest.mark.django_db
    def test_evaluates_true_when_enabling_product_purchased(self, conference, user, ticket_type):
        order = _make_order(conference=conference, user=user, status=Order.Status.PAID)
        OrderLineItem.objects.create(
            order=order,
            description="General",
            quantity=1,
            unit_price=Decimal("100.00"),
            line_total=Decimal("100.00"),
            ticket_type=ticket_type,
        )

        condition = IncludedProductCondition.objects.create(
            conference=conference,
            name="Lunch included with General",
            discount_type=DiscountEffect.DiscountType.PERCENTAGE,
            discount_value=Decimal("100.00"),
        )
        condition.enabling_ticket_types.add(ticket_type)
        assert condition.evaluate(user, conference) is True

    @pytest.mark.django_db
    def test_evaluates_false_without_purchase(self, conference, user, ticket_type):
        condition = IncludedProductCondition.objects.create(
            conference=conference,
            name="Lunch included with General",
        )
        condition.enabling_ticket_types.add(ticket_type)
        assert condition.evaluate(user, conference) is False

    @pytest.mark.django_db
    def test_evaluates_false_with_cancelled_order(self, conference, user, ticket_type):
        order = _make_order(conference=conference, user=user, status=Order.Status.CANCELLED)
        OrderLineItem.objects.create(
            order=order,
            description="General",
            quantity=1,
            unit_price=Decimal("100.00"),
            line_total=Decimal("100.00"),
            ticket_type=ticket_type,
        )

        condition = IncludedProductCondition.objects.create(
            conference=conference,
            name="Lunch included with General",
        )
        condition.enabling_ticket_types.add(ticket_type)
        assert condition.evaluate(user, conference) is False

    @pytest.mark.django_db
    def test_evaluates_false_with_no_enabling_types(self, conference, user):
        condition = IncludedProductCondition.objects.create(
            conference=conference,
            name="Empty",
        )
        assert condition.evaluate(user, conference) is False


# =============================================================================
# DiscountForProduct tests
# =============================================================================


class TestDiscountForProduct:
    """Tests for direct product discounts."""

    @pytest.mark.django_db
    def test_always_evaluates_true_within_window(self, conference, user):
        now = timezone.now()
        condition = DiscountForProduct.objects.create(
            conference=conference,
            name="Flash Sale",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
            discount_type=DiscountEffect.DiscountType.FIXED_AMOUNT,
            discount_value=Decimal("15.00"),
        )
        assert condition.evaluate(user, conference) is True

    @pytest.mark.django_db
    def test_applies_correct_discount(self, conference):
        condition = DiscountForProduct.objects.create(
            conference=conference,
            name="$15 off",
            discount_type=DiscountEffect.DiscountType.FIXED_AMOUNT,
            discount_value=Decimal("15.00"),
        )
        assert condition.calculate_discount(Decimal("100.00"), 1) == Decimal("15.00")

    @pytest.mark.django_db
    def test_evaluates_false_outside_window(self, conference, user):
        now = timezone.now()
        condition = DiscountForProduct.objects.create(
            conference=conference,
            name="Expired Sale",
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
        )
        assert condition.evaluate(user, conference) is False


# =============================================================================
# DiscountForCategory tests
# =============================================================================


class TestDiscountForCategory:
    """Tests for category-wide percentage discounts."""

    @pytest.mark.django_db
    def test_evaluate_within_window(self, conference, user):
        condition = DiscountForCategory.objects.create(
            conference=conference,
            name="10% everything",
            percentage=Decimal("10.00"),
        )
        assert condition.evaluate(user, conference) is True

    @pytest.mark.django_db
    def test_calculate_discount(self, conference):
        condition = DiscountForCategory.objects.create(
            conference=conference,
            name="10% off",
            percentage=Decimal("10.00"),
        )
        assert condition.calculate_discount(Decimal("100.00"), 2) == Decimal("20.00")


# =============================================================================
# ConditionEvaluator integration tests
# =============================================================================


class TestConditionEvaluator:
    """Integration tests for the condition evaluator service."""

    @pytest.mark.django_db
    def test_cart_with_no_conditions(self, cart, ticket_type):
        CartItem.objects.create(cart=cart, ticket_type=ticket_type, quantity=1)
        results = evaluate_for_cart(cart)
        assert results == []

    @pytest.mark.django_db
    def test_cart_with_matching_time_limit(self, cart, ticket_type, conference):
        item = CartItem.objects.create(cart=cart, ticket_type=ticket_type, quantity=1)

        TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="Early Bird 20%",
            discount_type=DiscountEffect.DiscountType.PERCENTAGE,
            discount_value=Decimal("20.00"),
        )

        results = evaluate_for_cart(cart)
        assert len(results) == 1
        assert results[0].cart_item_id == item.pk
        assert results[0].discount_amount == Decimal("20.00")
        assert results[0].condition_name == "Early Bird 20%"

    @pytest.mark.django_db
    def test_cart_with_speaker_condition(self, cart, ticket_type, conference, user):
        item = CartItem.objects.create(cart=cart, ticket_type=ticket_type, quantity=1)

        speaker = Speaker.objects.create(
            conference=conference,
            pretalx_code="SPKR-EVAL",
            name="Test Speaker",
            user=user,
        )
        talk = Talk.objects.create(
            conference=conference,
            pretalx_code="TALK-EVAL",
            title="Test Talk",
        )
        talk.speakers.add(speaker)

        SpeakerCondition.objects.create(
            conference=conference,
            name="Speaker Comp",
            is_presenter=True,
            discount_type=DiscountEffect.DiscountType.PERCENTAGE,
            discount_value=Decimal("100.00"),
        )

        results = evaluate_for_cart(cart)
        assert len(results) == 1
        assert results[0].discount_amount == Decimal("100.00")

    @pytest.mark.django_db
    def test_cart_with_group_member_condition(self, cart, ticket_type, conference, user):
        item = CartItem.objects.create(cart=cart, ticket_type=ticket_type, quantity=1)
        group = Group.objects.create(name=f"staff-eval-{uuid4().hex[:6]}")
        user.groups.add(group)

        condition = GroupMemberCondition.objects.create(
            conference=conference,
            name="Staff 50%",
            discount_type=DiscountEffect.DiscountType.PERCENTAGE,
            discount_value=Decimal("50.00"),
        )
        condition.groups.add(group)

        results = evaluate_for_cart(cart)
        assert len(results) == 1
        assert results[0].discount_amount == Decimal("50.00")

    @pytest.mark.django_db
    def test_priority_first_match_wins(self, cart, ticket_type, conference):
        item = CartItem.objects.create(cart=cart, ticket_type=ticket_type, quantity=1)

        # Lower priority = evaluated first
        TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="10% discount",
            priority=0,
            discount_type=DiscountEffect.DiscountType.PERCENTAGE,
            discount_value=Decimal("10.00"),
        )
        TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="50% discount",
            priority=1,
            discount_type=DiscountEffect.DiscountType.PERCENTAGE,
            discount_value=Decimal("50.00"),
        )

        results = evaluate_for_cart(cart)
        assert len(results) == 1
        assert results[0].discount_amount == Decimal("10.00")
        assert results[0].condition_name == "10% discount"

    @pytest.mark.django_db
    def test_cross_type_priority_ordering(self, cart, conference, user):
        """Priority is respected globally across different condition types."""
        ticket = TicketType.objects.create(
            conference=conference,
            name="CrossType",
            slug="cross-type-prio",
            price=Decimal("100.00"),
            is_active=True,
        )
        CartItem.objects.create(cart=cart, ticket_type=ticket, quantity=1)

        # Higher priority (lower number) group condition: 50% off
        group = Group.objects.create(name="staff-prio-test")
        user.groups.add(group)
        group_cond = GroupMemberCondition.objects.create(
            conference=conference,
            name="Staff 50%",
            priority=-1,
            discount_type=DiscountEffect.DiscountType.PERCENTAGE,
            discount_value=Decimal("50.00"),
        )
        group_cond.groups.add(group)

        # Lower priority (higher number) time condition: 10% off
        TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="Early 10%",
            priority=5,
            discount_type=DiscountEffect.DiscountType.PERCENTAGE,
            discount_value=Decimal("10.00"),
        )

        results = evaluate_for_cart(cart)
        assert len(results) == 1
        assert results[0].condition_name == "Staff 50%"
        assert results[0].discount_amount == Decimal("50.00")

    @pytest.mark.django_db
    def test_applicable_ticket_types_filter(self, cart, conference):
        general = TicketType.objects.create(
            conference=conference,
            name="General",
            slug="general-filter",
            price=Decimal("100.00"),
            is_active=True,
        )
        vip = TicketType.objects.create(
            conference=conference,
            name="VIP",
            slug="vip-filter",
            price=Decimal("200.00"),
            is_active=True,
        )
        CartItem.objects.create(cart=cart, ticket_type=general, quantity=1)
        item_vip = CartItem.objects.create(cart=cart, ticket_type=vip, quantity=1)

        condition = TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="VIP Only 25%",
            discount_type=DiscountEffect.DiscountType.PERCENTAGE,
            discount_value=Decimal("25.00"),
        )
        condition.applicable_ticket_types.add(vip)

        results = evaluate_for_cart(cart)
        assert len(results) == 1
        assert results[0].cart_item_id == item_vip.pk
        assert results[0].discount_amount == Decimal("50.00")

    @pytest.mark.django_db
    def test_inactive_conditions_ignored(self, cart, ticket_type, conference):
        CartItem.objects.create(cart=cart, ticket_type=ticket_type, quantity=1)

        TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="Inactive",
            is_active=False,
            discount_type=DiscountEffect.DiscountType.PERCENTAGE,
            discount_value=Decimal("50.00"),
        )

        results = evaluate_for_cart(cart)
        assert results == []

    @pytest.mark.django_db
    def test_empty_cart_returns_no_discounts(self, cart, conference):
        TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="Active Discount",
            discount_type=DiscountEffect.DiscountType.PERCENTAGE,
            discount_value=Decimal("20.00"),
        )

        results = evaluate_for_cart(cart)
        assert results == []

    @pytest.mark.django_db
    def test_category_discount_applies_to_tickets_and_addons(self, cart, conference):
        ticket = TicketType.objects.create(
            conference=conference,
            name="Gen",
            slug="gen-cat",
            price=Decimal("100.00"),
            is_active=True,
        )
        addon = AddOn.objects.create(
            conference=conference,
            name="Shirt",
            slug="shirt-cat",
            price=Decimal("50.00"),
            is_active=True,
        )
        CartItem.objects.create(cart=cart, ticket_type=ticket, quantity=1)
        CartItem.objects.create(cart=cart, addon=addon, quantity=2)

        DiscountForCategory.objects.create(
            conference=conference,
            name="10% everything",
            percentage=Decimal("10.00"),
            apply_to_tickets=True,
            apply_to_addons=True,
        )

        results = evaluate_for_cart(cart)
        assert len(results) == 2
        sorted_discounts = sorted(results, key=lambda r: r.cart_item_id)
        assert sorted_discounts[0].discount_amount == Decimal("10.00")  # 10% of 100
        assert sorted_discounts[1].discount_amount == Decimal("10.00")  # 10% of (50 * 2)

    @pytest.mark.django_db
    def test_get_eligible_discounts(self, conference, user):
        TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="Active One",
            discount_type=DiscountEffect.DiscountType.PERCENTAGE,
            discount_value=Decimal("10.00"),
        )
        TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="Inactive",
            is_active=False,
            discount_type=DiscountEffect.DiscountType.PERCENTAGE,
            discount_value=Decimal("50.00"),
        )

        eligible = get_eligible_discounts(user, conference)
        assert len(eligible) == 1
        assert eligible[0].name == "Active One"

    @pytest.mark.django_db
    def test_get_visible_products(self, conference, user):
        TicketType.objects.create(
            conference=conference,
            name="Active",
            slug="active-vis",
            price=Decimal("100.00"),
            is_active=True,
        )
        TicketType.objects.create(
            conference=conference,
            name="Inactive",
            slug="inactive-vis",
            price=Decimal("100.00"),
            is_active=False,
        )

        tickets, _addons = get_visible_products(user, conference)
        assert tickets.count() == 1
        assert tickets.first().name == "Active"


# =============================================================================
# Cart pricing integration tests
# =============================================================================


class TestCartPricingIntegration:
    """Tests for condition discount integration with cart pricing."""

    @pytest.mark.django_db
    def test_get_summary_with_condition_discount(self, cart, ticket_type, conference):
        CartItem.objects.create(cart=cart, ticket_type=ticket_type, quantity=2)

        TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="Early Bird 10%",
            discount_type=DiscountEffect.DiscountType.PERCENTAGE,
            discount_value=Decimal("10.00"),
        )

        summary = get_summary(cart)
        assert summary.subtotal == Decimal("200.00")
        assert summary.condition_discount == Decimal("20.00")
        assert summary.total == Decimal("180.00")
        assert summary.items[0].condition_discount == Decimal("20.00")
        assert summary.items[0].condition_name == "Early Bird 10%"

    @pytest.mark.django_db
    def test_condition_plus_voucher_stacking(self, cart, conference):
        ticket = TicketType.objects.create(
            conference=conference,
            name="Gen",
            slug="gen-stack",
            price=Decimal("100.00"),
            is_active=True,
        )
        CartItem.objects.create(cart=cart, ticket_type=ticket, quantity=1)

        TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="20% Early Bird",
            discount_type=DiscountEffect.DiscountType.PERCENTAGE,
            discount_value=Decimal("20.00"),
        )

        voucher = Voucher.objects.create(
            conference=conference,
            code="EXTRA10",
            voucher_type=Voucher.VoucherType.PERCENTAGE,
            discount_value=Decimal("10.00"),
        )
        cart.voucher = voucher
        cart.save()

        summary = get_summary(cart)

        # Condition: 20% of 100 = $20
        assert summary.condition_discount == Decimal("20.00")
        # Voucher: 10% of remaining $80 = $8
        assert summary.items[0].discount == Decimal("8.00")
        # Total discount: 20 + 8 = 28
        assert summary.discount == Decimal("28.00")
        assert summary.total == Decimal("72.00")

    @pytest.mark.django_db
    def test_no_condition_discounts_preserves_voucher_behavior(self, cart, conference):
        ticket = TicketType.objects.create(
            conference=conference,
            name="Gen",
            slug="gen-nocd",
            price=Decimal("100.00"),
            is_active=True,
        )
        CartItem.objects.create(cart=cart, ticket_type=ticket, quantity=1)

        voucher = Voucher.objects.create(
            conference=conference,
            code="SAVE10",
            voucher_type=Voucher.VoucherType.PERCENTAGE,
            discount_value=Decimal("10.00"),
        )
        cart.voucher = voucher
        cart.save()

        summary = get_summary(cart)
        assert summary.condition_discount == Decimal("0.00")
        assert summary.discount == Decimal("10.00")
        assert summary.total == Decimal("90.00")

    @pytest.mark.django_db
    def test_comp_voucher_after_condition_discount(self, cart, conference):
        ticket = TicketType.objects.create(
            conference=conference,
            name="Gen",
            slug="gen-comp",
            price=Decimal("100.00"),
            is_active=True,
        )
        CartItem.objects.create(cart=cart, ticket_type=ticket, quantity=1)

        TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="20% off",
            discount_type=DiscountEffect.DiscountType.PERCENTAGE,
            discount_value=Decimal("20.00"),
        )

        voucher = Voucher.objects.create(
            conference=conference,
            code="COMP",
            voucher_type=Voucher.VoucherType.COMP,
        )
        cart.voucher = voucher
        cart.save()

        summary = get_summary(cart)
        # Condition: 20% of 100 = 20
        assert summary.condition_discount == Decimal("20.00")
        # Voucher comp: 100% of remaining 80 = 80
        assert summary.items[0].discount == Decimal("80.00")
        assert summary.total == Decimal("0.00")


# =============================================================================
# ConditionBase model tests
# =============================================================================


class TestConditionBaseModel:
    """Tests for ConditionBase model methods."""

    @pytest.mark.django_db
    def test_condition_str(self, conference):
        cond = TimeOrStockLimitCondition.objects.create(conference=conference, name="My Condition")
        assert str(cond) == "My Condition"

    @pytest.mark.django_db
    def test_condition_base_evaluate_raises(self, conference, user):

        cond = TimeOrStockLimitCondition.objects.create(conference=conference, name="Test")
        # TimeOrStockLimitCondition overrides evaluate, so test via ConditionBase
        assert isinstance(cond.evaluate(user, conference), bool)


class TestDiscountValidation:
    """Tests for _validate_discount_value."""

    @pytest.mark.django_db
    def test_negative_discount_value_raises(self, conference):
        from django.core.exceptions import ValidationError

        from django_program.registration.conditions import _validate_discount_value

        with pytest.raises(ValidationError, match="cannot be negative"):
            _validate_discount_value(Decimal("-5.00"))

    @pytest.mark.django_db
    def test_zero_discount_value_ok(self, conference):
        from django_program.registration.conditions import _validate_discount_value

        _validate_discount_value(Decimal("0.00"))


class TestDiscountEffectUnknownType:
    """Tests for unknown discount_type fallback."""

    @pytest.mark.django_db
    def test_unknown_discount_type_returns_zero(self, conference):
        cond = TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="Unknown Type",
            discount_type="percentage",
            discount_value=Decimal("10.00"),
        )
        # Force an unknown discount_type
        cond.discount_type = "unknown"
        result = cond.calculate_discount(Decimal("100.00"), 1)
        assert result == Decimal("0.00")


class TestSpeakerConditionEdgeCases:
    """Edge cases for SpeakerCondition.evaluate."""

    @pytest.mark.django_db
    def test_copresenter_false_when_solo_talk(self, conference, user):
        """Copresenter-only condition returns False for single-speaker talks."""
        speaker = Speaker.objects.create(
            conference=conference,
            pretalx_code="SPKR-SOLO",
            name="Solo Speaker",
            user=user,
        )
        talk = Talk.objects.create(
            conference=conference,
            pretalx_code="TALK-SOLO",
            title="Solo Talk",
        )
        talk.speakers.add(speaker)

        condition = SpeakerCondition.objects.create(
            conference=conference,
            name="Copresenter Only",
            is_presenter=False,
            is_copresenter=True,
        )
        assert condition.evaluate(user, conference) is False

    @pytest.mark.django_db
    def test_neither_presenter_nor_copresenter(self, conference, user):
        """Both flags False returns False even for linked speakers."""
        speaker = Speaker.objects.create(
            conference=conference,
            pretalx_code="SPKR-NEITHER",
            name="Neither",
            user=user,
        )
        condition = SpeakerCondition.objects.create(
            conference=conference,
            name="No Flags",
            is_presenter=False,
            is_copresenter=False,
        )
        assert condition.evaluate(user, conference) is False


# =============================================================================
# commit_condition_usage tests
# =============================================================================


class TestCommitConditionUsage:
    """Tests for commit_condition_usage."""

    @pytest.mark.django_db
    def test_increments_times_used(self, conference, cart, user):
        from django_program.registration.services.conditions import (
            CartItemDiscount,
            commit_condition_usage,
        )

        cond = TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="Usage Test",
            discount_type="percentage",
            discount_value=Decimal("10.00"),
            limit=100,
            times_used=0,
        )

        discounts = [
            CartItemDiscount(
                cart_item_id=1,
                condition_name="Usage Test",
                condition_type="TimeOrStockLimitCondition",
                discount_amount=Decimal("10.00"),
                original_price=Decimal("100.00"),
                condition_pk=cond.pk,
                condition_model="TimeOrStockLimitCondition",
            ),
        ]

        commit_condition_usage(discounts)
        cond.refresh_from_db()
        assert cond.times_used == 1

    @pytest.mark.django_db
    def test_skips_discounts_without_pk(self, conference):
        from django_program.registration.services.conditions import (
            CartItemDiscount,
            commit_condition_usage,
        )

        discounts = [
            CartItemDiscount(
                cart_item_id=1,
                condition_name="No PK",
                condition_type="Unknown",
                discount_amount=Decimal("10.00"),
                original_price=Decimal("100.00"),
                condition_pk=None,
                condition_model=None,
            ),
        ]

        commit_condition_usage(discounts)

    @pytest.mark.django_db
    def test_category_discount_scope_tickets_only(self, cart, conference):
        """Category discount with only apply_to_tickets does not apply to addons."""
        ticket = TicketType.objects.create(
            conference=conference,
            name="Gen",
            slug="gen-cat-tickets",
            price=Decimal("100.00"),
            is_active=True,
        )
        addon = AddOn.objects.create(
            conference=conference,
            name="Lunch",
            slug="lunch-cat",
            price=Decimal("50.00"),
            is_active=True,
        )
        CartItem.objects.create(cart=cart, ticket_type=ticket, quantity=1)
        CartItem.objects.create(cart=cart, addon=addon, quantity=1)

        DiscountForCategory.objects.create(
            conference=conference,
            name="Tickets only",
            percentage=Decimal("10.00"),
            apply_to_tickets=True,
            apply_to_addons=False,
        )

        results = evaluate_for_cart(cart)
        assert len(results) == 1
        assert results[0].discount_amount == Decimal("10.00")

    @pytest.mark.django_db
    def test_addon_matches_discount_scope_with_specific_addon(self, cart, conference):
        """Discount scoped to a specific addon applies only to that addon."""
        addon1 = AddOn.objects.create(
            conference=conference,
            name="Lunch",
            slug="lunch-scope",
            price=Decimal("30.00"),
            is_active=True,
        )
        addon2 = AddOn.objects.create(
            conference=conference,
            name="Dinner",
            slug="dinner-scope",
            price=Decimal("50.00"),
            is_active=True,
        )
        CartItem.objects.create(cart=cart, addon=addon1, quantity=1)
        CartItem.objects.create(cart=cart, addon=addon2, quantity=1)

        cond = TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="Lunch discount",
            discount_type="percentage",
            discount_value=Decimal("50.00"),
        )
        cond.applicable_addons.add(addon1)

        results = evaluate_for_cart(cart)
        assert len(results) == 1
        assert results[0].discount_amount == Decimal("15.00")

    @pytest.mark.django_db
    def test_addon_matches_all_when_no_filter(self, cart, conference):
        """Discount with no applicable_addons applies to all addons."""
        addon = AddOn.objects.create(
            conference=conference,
            name="Hat",
            slug="hat-scope",
            price=Decimal("20.00"),
            is_active=True,
        )
        CartItem.objects.create(cart=cart, addon=addon, quantity=1)

        TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="Everything 10%",
            discount_type="percentage",
            discount_value=Decimal("10.00"),
        )

        results = evaluate_for_cart(cart)
        assert len(results) == 1
        assert results[0].discount_amount == Decimal("2.00")

    @pytest.mark.django_db
    def test_zero_discount_skipped(self, cart, conference):
        """Condition with 0% discount produces no results."""
        ticket = TicketType.objects.create(
            conference=conference,
            name="Gen",
            slug="gen-zero",
            price=Decimal("100.00"),
            is_active=True,
        )
        CartItem.objects.create(cart=cart, ticket_type=ticket, quantity=1)

        TimeOrStockLimitCondition.objects.create(
            conference=conference,
            name="Zero Discount",
            discount_type="percentage",
            discount_value=Decimal("0.00"),
        )

        results = evaluate_for_cart(cart)
        assert results == []

    @pytest.mark.django_db
    def test_item_with_no_product_type_skipped(self):
        """_item_matches_discount_scope returns False for item without product type."""
        from unittest.mock import MagicMock

        from django_program.registration.services.conditions import _item_matches_discount_scope

        item = MagicMock()
        item.ticket_type_id = None
        item.addon_id = None
        assert _item_matches_discount_scope(item, set(), set()) is False

    @pytest.mark.django_db
    def test_item_with_no_product_type_skipped_by_category(self):
        """_item_matches_category_scope returns False for item without product type."""
        from unittest.mock import MagicMock

        from django_program.registration.conditions import DiscountForCategory
        from django_program.registration.services.conditions import _item_matches_category_scope

        item = MagicMock()
        item.ticket_type_id = None
        item.addon_id = None
        condition = MagicMock(spec=DiscountForCategory)
        assert _item_matches_category_scope(item, condition) is False

    @pytest.mark.django_db
    def test_category_discount_addons_only(self, cart, conference):
        """Category discount with only apply_to_addons does not apply to tickets."""
        ticket = TicketType.objects.create(
            conference=conference,
            name="Gen",
            slug="gen-addons-only",
            price=Decimal("100.00"),
            is_active=True,
        )
        addon = AddOn.objects.create(
            conference=conference,
            name="Swag",
            slug="swag-cat",
            price=Decimal("40.00"),
            is_active=True,
        )
        CartItem.objects.create(cart=cart, ticket_type=ticket, quantity=1)
        CartItem.objects.create(cart=cart, addon=addon, quantity=1)

        DiscountForCategory.objects.create(
            conference=conference,
            name="Addons only",
            percentage=Decimal("25.00"),
            apply_to_tickets=False,
            apply_to_addons=True,
        )

        results = evaluate_for_cart(cart)
        assert len(results) == 1
        assert results[0].discount_amount == Decimal("10.00")


# =============================================================================
# _finalize_discount_usage (checkout.py line 60) tests
# =============================================================================


class TestFinalizeDiscountUsage:
    """Test for the condition_discounts branch in _finalize_discount_usage."""

    @pytest.mark.django_db
    def test_finalize_calls_commit_when_discounts(self, conference):
        from unittest.mock import MagicMock, patch

        from django_program.registration.services.checkout import _finalize_discount_usage

        summary = MagicMock()
        summary.condition_discounts = [MagicMock()]

        with patch("django_program.registration.services.checkout.commit_condition_usage") as mock_commit:
            _finalize_discount_usage(voucher=None, summary=summary, now=timezone.now())
            mock_commit.assert_called_once_with(summary.condition_discounts)
