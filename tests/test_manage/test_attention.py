"""Tests for ``django_program.manage.attention_builtin.builtin_attention``."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory, override_settings
from django.urls import NoReverseMatch

from django_program.conference.models import Conference
from django_program.manage.attention_builtin import builtin_attention
from django_program.programs.models import Receipt, TravelGrant


@pytest.fixture
def conference(db):
    return Conference.objects.create(
        name="Attention Conf",
        slug="attention-conf",
        start_date=date(2027, 5, 1),
        end_date=date(2027, 5, 3),
        timezone="UTC",
        is_active=True,
    )


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(username="admin", password="password", email="admin@test.com")


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(username="regular", password="password")


def _request(user):
    req = RequestFactory().get("/")
    req.user = user
    return req


def _grant_perm(user: User, app_label: str, codename: str) -> None:
    ct = ContentType.objects.get(app_label=app_label, model=_model_for(app_label, codename))
    perm = Permission.objects.get(content_type=ct, codename=codename)
    user.user_permissions.add(perm)


def _model_for(app_label: str, codename: str) -> str:
    if codename == "view_travel_grant":
        return "travelgrant"
    if codename == "review_receipt":
        return "receipt"
    if codename == "view_registration":
        return "conference"
    msg = f"unknown codename {codename!r}"
    raise ValueError(msg)


@pytest.fixture
def pending_grant(conference, regular_user):
    return TravelGrant.objects.create(
        conference=conference,
        user=regular_user,
        status=TravelGrant.GrantStatus.SUBMITTED,
        requested_amount=Decimal("500.00"),
        travel_from="Chicago",
        reason="Need help",
    )


@pytest.fixture
def pending_receipt(conference, regular_user):
    grant = TravelGrant.objects.create(
        conference=conference,
        user=regular_user,
        status=TravelGrant.GrantStatus.ACCEPTED,
        requested_amount=Decimal("500.00"),
        travel_from="Chicago",
        reason="Need help",
    )
    return Receipt.objects.create(
        grant=grant,
        receipt_type=Receipt.ReceiptType.AIRFARE,
        amount=Decimal("250.00"),
        date=date(2027, 4, 1),
        receipt_file="test.pdf",
    )


class TestConferenceNone:
    def test_no_conference_yields_nothing(self, superuser, pending_grant):
        items = list(builtin_attention(_request(superuser), None))
        assert items == []


class TestTravelGrantsPending:
    def test_superuser_sees_pending_grant(self, conference, superuser, pending_grant):
        items = {item.key: item for item in builtin_attention(_request(superuser), conference)}
        assert "travel-grants-pending" in items
        item = items["travel-grants-pending"]
        assert item.count == 1
        assert item.tone == "warning"
        assert conference.slug in item.url

    def test_no_items_when_count_is_zero(self, conference, superuser):
        items = {item.key: item for item in builtin_attention(_request(superuser), conference)}
        assert "travel-grants-pending" not in items

    @override_settings(DJANGO_PROGRAM={"features": {"travel_grants_enabled": False}})
    def test_no_items_when_feature_disabled(self, conference, superuser, pending_grant):
        items = {item.key: item for item in builtin_attention(_request(superuser), conference)}
        assert "travel-grants-pending" not in items

    def test_no_items_without_permission(self, conference, regular_user, pending_grant):
        items = {item.key: item for item in builtin_attention(_request(regular_user), conference)}
        assert "travel-grants-pending" not in items

    def test_items_with_scoped_permission(self, conference, regular_user, pending_grant):
        _grant_perm(regular_user, "program_programs", "view_travel_grant")
        items = {item.key: item for item in builtin_attention(_request(regular_user), conference)}
        assert items["travel-grants-pending"].count == 1


class TestReceiptsPending:
    def test_superuser_sees_pending_receipt(self, conference, superuser, pending_receipt):
        items = {item.key: item for item in builtin_attention(_request(superuser), conference)}
        assert "receipts-pending" in items
        item = items["receipts-pending"]
        assert item.count == 1
        assert item.tone == "warning"
        assert conference.slug in item.url

    def test_approved_receipt_not_counted(self, conference, superuser, pending_receipt):
        pending_receipt.approved = True
        pending_receipt.save(update_fields=["approved"])
        items = {item.key: item for item in builtin_attention(_request(superuser), conference)}
        assert "receipts-pending" not in items

    @override_settings(DJANGO_PROGRAM={"features": {"travel_grants_enabled": False}})
    def test_no_items_when_feature_disabled(self, conference, superuser, pending_receipt):
        items = {item.key: item for item in builtin_attention(_request(superuser), conference)}
        assert "receipts-pending" not in items

    def test_no_items_without_permission(self, conference, regular_user, pending_receipt):
        items = {item.key: item for item in builtin_attention(_request(regular_user), conference)}
        assert "receipts-pending" not in items


class TestUnmountedManageUrls:
    """``manage:`` URLs may not be mounted on host pages; skip the item instead of 500ing."""

    def test_pending_grant_skipped_when_url_cannot_be_reversed(self, conference, superuser, pending_grant):
        with patch(
            "django_program.manage.attention_builtin.reverse",
            side_effect=NoReverseMatch("manage: not mounted"),
        ):
            items = {item.key: item for item in builtin_attention(_request(superuser), conference)}
        assert "travel-grants-pending" not in items

    def test_pending_receipt_skipped_when_url_cannot_be_reversed(self, conference, superuser, pending_receipt):
        with patch(
            "django_program.manage.attention_builtin.reverse",
            side_effect=NoReverseMatch("manage: not mounted"),
        ):
            items = {item.key: item for item in builtin_attention(_request(superuser), conference)}
        assert "receipts-pending" not in items
