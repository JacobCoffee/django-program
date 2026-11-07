"""Coverage-focused tests for django_program.sponsors.admin and models."""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib import admin

from django_program.conference.models import Conference
from django_program.registration.models import Voucher
from django_program.sponsors.admin import BulkPurchaseVoucherInline
from django_program.sponsors.models import BulkPurchase, BulkPurchaseVoucher, Sponsor, SponsorLevel


@pytest.fixture
def conference() -> Conference:
    return Conference.objects.create(
        name="AdminCon",
        slug="admincon",
        start_date=date(2027, 7, 1),
        end_date=date(2027, 7, 3),
        timezone="UTC",
    )


@pytest.fixture
def level(conference: Conference) -> SponsorLevel:
    return SponsorLevel.objects.create(
        conference=conference,
        name="Gold",
        cost=Decimal("5000.00"),
    )


@pytest.fixture
def sponsor(conference: Conference, level: SponsorLevel) -> Sponsor:
    return Sponsor.objects.create(
        conference=conference,
        level=level,
        name="AdminCo",
    )


# ---------------------------------------------------------------------------
# admin.py line 35: BulkPurchaseVoucherInline.has_add_permission always False
# ---------------------------------------------------------------------------


def test_bulk_purchase_voucher_inline_denies_add():
    inline = BulkPurchaseVoucherInline(BulkPurchase, admin_site=admin.site)
    assert inline.has_add_permission(request=None, obj=None) is False
    assert inline.has_add_permission(request=None) is False


# ---------------------------------------------------------------------------
# models.py: computed_total (443), vouchers_generated (448), is_fulfilled (453)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_bulk_purchase_computed_total(conference: Conference, sponsor: Sponsor):
    bp = BulkPurchase.objects.create(
        conference=conference,
        sponsor=sponsor,
        quantity=4,
        unit_price=Decimal("25.00"),
        total_amount=Decimal("100.00"),
    )
    assert bp.computed_total == Decimal("100.00")


@pytest.mark.django_db
def test_bulk_purchase_vouchers_generated_and_is_fulfilled(conference: Conference, sponsor: Sponsor):
    bp = BulkPurchase.objects.create(
        conference=conference,
        sponsor=sponsor,
        quantity=2,
        unit_price=Decimal("10.00"),
        total_amount=Decimal("20.00"),
    )
    assert bp.vouchers_generated == 0
    assert bp.is_fulfilled is False

    v1 = Voucher.objects.create(conference=conference, code="MODEL1", voucher_type="comp")
    BulkPurchaseVoucher.objects.create(bulk_purchase=bp, voucher=v1)

    bp.refresh_from_db()
    assert bp.vouchers_generated == 1
    assert bp.is_fulfilled is False

    v2 = Voucher.objects.create(conference=conference, code="MODEL2", voucher_type="comp")
    BulkPurchaseVoucher.objects.create(bulk_purchase=bp, voucher=v2)

    bp.refresh_from_db()
    assert bp.vouchers_generated == 2
    assert bp.is_fulfilled is True


# ---------------------------------------------------------------------------
# models.py line 481: BulkPurchaseVoucher.__str__
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_bulk_purchase_voucher_str(conference: Conference, sponsor: Sponsor):
    bp = BulkPurchase.objects.create(
        conference=conference,
        sponsor=sponsor,
        quantity=1,
        unit_price=Decimal("10.00"),
        total_amount=Decimal("10.00"),
    )
    voucher = Voucher.objects.create(conference=conference, code="STRCODE", voucher_type="comp")
    link = BulkPurchaseVoucher.objects.create(bulk_purchase=bp, voucher=voucher)

    assert str(link) == f"{bp} → STRCODE"
