"""Tests for badge generation — models, QR codes, PDF/PNG output, and caching."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from django_program.conference.models import Conference
from django_program.registration.attendee import Attendee
from django_program.registration.badge import Badge, BadgeTemplate
from django_program.registration.models import Order, OrderLineItem, TicketType
from django_program.registration.services.badge import BadgeGenerationService

User = get_user_model()

pytestmark = pytest.mark.django_db


# -- Helpers ------------------------------------------------------------------


def _make_conference(**kwargs: object) -> Conference:
    defaults: dict[str, object] = {
        "name": "TestCon 2026",
        "slug": f"testcon-{uuid4().hex[:6]}",
        "start_date": date(2026, 7, 1),
        "end_date": date(2026, 7, 5),
    }
    defaults.update(kwargs)
    return Conference.objects.create(**defaults)


def _make_user(**kwargs: object) -> object:
    defaults: dict[str, object] = {
        "username": f"user-{uuid4().hex[:8]}",
        "email": f"{uuid4().hex[:8]}@test.com",
        "first_name": "Jane",
        "last_name": "Doe",
    }
    defaults.update(kwargs)
    return User.objects.create_user(**defaults)


def _make_template(conference: Conference, **kwargs: object) -> BadgeTemplate:
    defaults: dict[str, object] = {
        "name": "Default Badge",
        "slug": f"badge-{uuid4().hex[:6]}",
        "is_default": True,
    }
    defaults.update(kwargs)
    return BadgeTemplate.objects.create(conference=conference, **defaults)


def _make_attendee(conference: Conference, user: object | None = None) -> Attendee:
    if user is None:
        user = _make_user()
    return Attendee.objects.create(user=user, conference=conference)


def _make_ticket_type(conference: Conference, **kwargs: object) -> TicketType:
    defaults: dict[str, object] = {
        "name": "Individual",
        "slug": f"individual-{uuid4().hex[:6]}",
        "price": Decimal("100.00"),
    }
    defaults.update(kwargs)
    return TicketType.objects.create(conference=conference, **defaults)


def _make_order_with_ticket(
    conference: Conference,
    user: object,
    ticket_type: TicketType,
) -> Order:
    order = Order.objects.create(
        conference=conference,
        user=user,
        status=Order.Status.PAID,
        subtotal=ticket_type.price,
        total=ticket_type.price,
        reference=f"ORD-{uuid4().hex[:8].upper()}",
    )
    OrderLineItem.objects.create(
        order=order,
        description=f"Ticket: {ticket_type.name}",
        quantity=1,
        unit_price=ticket_type.price,
        line_total=ticket_type.price,
        ticket_type=ticket_type,
    )
    return order


# -- Tests: BadgeTemplate model -----------------------------------------------


@pytest.mark.unit
class TestBadgeTemplateModel:
    """Tests for the BadgeTemplate model."""

    def test_create_badge_template(self) -> None:
        conf = _make_conference()
        tpl = _make_template(conf)
        assert tpl.pk is not None
        assert tpl.width_mm == 102
        assert tpl.height_mm == 152
        assert tpl.is_default is True

    def test_badge_template_str(self) -> None:
        conf = _make_conference()
        tpl = _make_template(conf, name="VIP Badge")
        assert "VIP Badge" in str(tpl)
        assert conf.slug in str(tpl)

    def test_badge_template_unique_slug_per_conference(self) -> None:
        conf = _make_conference()
        _make_template(conf, slug="default", is_default=True)
        with pytest.raises(IntegrityError):
            _make_template(conf, slug="default", is_default=False)

    def test_badge_template_one_default_per_conference(self) -> None:
        conf = _make_conference()
        _make_template(conf, slug="first", is_default=True)
        with pytest.raises(IntegrityError):
            _make_template(conf, slug="second", is_default=True)

    def test_badge_template_default_across_conferences(self) -> None:
        conf1 = _make_conference()
        conf2 = _make_conference()
        tpl1 = _make_template(conf1, is_default=True)
        tpl2 = _make_template(conf2, is_default=True)
        assert tpl1.is_default is True
        assert tpl2.is_default is True

    def test_badge_template_defaults(self) -> None:
        conf = _make_conference()
        tpl = _make_template(conf)
        assert tpl.background_color == "#FFFFFF"
        assert tpl.text_color == "#000000"
        assert tpl.accent_color == "#4338CA"
        assert tpl.show_name is True
        assert tpl.show_qr_code is True
        assert tpl.show_email is False


# -- Tests: Badge model -------------------------------------------------------


@pytest.mark.unit
class TestBadgeModel:
    """Tests for the Badge model."""

    def test_create_badge(self) -> None:
        conf = _make_conference()
        attendee = _make_attendee(conf)
        tpl = _make_template(conf)
        badge = Badge.objects.create(attendee=attendee, template=tpl)
        assert badge.pk is not None
        assert badge.format == Badge.Format.PDF

    def test_badge_str(self) -> None:
        conf = _make_conference()
        attendee = _make_attendee(conf)
        badge = Badge.objects.create(attendee=attendee, format=Badge.Format.PNG)
        assert "png" in str(badge).lower()

    def test_badge_format_choices(self) -> None:
        assert Badge.Format.PDF == "pdf"
        assert Badge.Format.PNG == "png"


# -- Tests: QR code generation ------------------------------------------------


@pytest.mark.unit
class TestQRCodeGeneration:
    """Tests for QR code generation."""

    def test_generate_qr_code_returns_png_bytes(self) -> None:
        service = BadgeGenerationService()
        result = service.generate_qr_code("test-data")
        assert isinstance(result, bytes)
        assert len(result) > 0
        # PNG magic bytes
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    def test_generate_qr_code_custom_size(self) -> None:
        service = BadgeGenerationService()
        result = service.generate_qr_code("test-data", size=100)
        assert isinstance(result, bytes)
        assert len(result) > 0


# -- Tests: PDF badge generation ----------------------------------------------


@pytest.mark.unit
class TestPDFBadgeGeneration:
    """Tests for PDF badge generation."""

    def test_generate_badge_pdf_returns_bytes(self) -> None:
        conf = _make_conference()
        attendee = _make_attendee(conf)
        tpl = _make_template(conf)
        service = BadgeGenerationService()
        result = service.generate_badge_pdf(attendee, tpl)
        assert isinstance(result, bytes)
        assert len(result) > 0
        # PDF magic bytes
        assert result[:5] == b"%PDF-"

    def test_generate_badge_pdf_with_order(self) -> None:
        conf = _make_conference()
        user = _make_user()
        tt = _make_ticket_type(conf, name="Corporate")
        order = _make_order_with_ticket(conf, user, tt)
        attendee = Attendee.objects.create(user=user, conference=conf, order=order)
        tpl = _make_template(conf)
        service = BadgeGenerationService()
        result = service.generate_badge_pdf(attendee, tpl)
        assert isinstance(result, bytes)
        assert result[:5] == b"%PDF-"

    def test_generate_badge_pdf_all_fields_shown(self) -> None:
        conf = _make_conference()
        attendee = _make_attendee(conf)
        tpl = _make_template(
            conf,
            show_email=True,
            show_company=True,
        )
        service = BadgeGenerationService()
        result = service.generate_badge_pdf(attendee, tpl)
        assert isinstance(result, bytes)
        assert len(result) > 100

    def test_generate_badge_pdf_no_qr(self) -> None:
        conf = _make_conference()
        attendee = _make_attendee(conf)
        tpl = _make_template(conf, show_qr_code=False)
        service = BadgeGenerationService()
        result = service.generate_badge_pdf(attendee, tpl)
        assert isinstance(result, bytes)
        assert result[:5] == b"%PDF-"


# -- Tests: PNG badge generation ----------------------------------------------


@pytest.mark.unit
class TestPNGBadgeGeneration:
    """Tests for PNG badge generation."""

    def test_generate_badge_png_returns_bytes(self) -> None:
        conf = _make_conference()
        attendee = _make_attendee(conf)
        tpl = _make_template(conf)
        service = BadgeGenerationService()
        result = service.generate_badge_png(attendee, tpl)
        assert isinstance(result, bytes)
        # PNG magic bytes
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    def test_generate_badge_png_with_order(self) -> None:
        conf = _make_conference()
        user = _make_user()
        tt = _make_ticket_type(conf, name="Student")
        order = _make_order_with_ticket(conf, user, tt)
        attendee = Attendee.objects.create(user=user, conference=conf, order=order)
        tpl = _make_template(conf)
        service = BadgeGenerationService()
        result = service.generate_badge_png(attendee, tpl)
        assert isinstance(result, bytes)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"


# -- Tests: generate_or_get_badge ---------------------------------------------


@pytest.mark.unit
class TestGenerateOrGetBadge:
    """Tests for the generate_or_get_badge caching behavior."""

    def test_generates_new_badge(self) -> None:
        conf = _make_conference()
        attendee = _make_attendee(conf)
        tpl = _make_template(conf)
        service = BadgeGenerationService()
        badge = service.generate_or_get_badge(attendee, template=tpl)
        assert badge.pk is not None
        assert badge.generated_at is not None
        assert badge.file
        assert badge.format == Badge.Format.PDF

    def test_returns_existing_badge(self) -> None:
        conf = _make_conference()
        attendee = _make_attendee(conf)
        tpl = _make_template(conf)
        service = BadgeGenerationService()
        badge1 = service.generate_or_get_badge(attendee, template=tpl)
        badge2 = service.generate_or_get_badge(attendee, template=tpl)
        assert badge1.pk == badge2.pk

    def test_uses_default_template_when_none(self) -> None:
        conf = _make_conference()
        attendee = _make_attendee(conf)
        _make_template(conf, is_default=True)
        service = BadgeGenerationService()
        badge = service.generate_or_get_badge(attendee)
        assert badge.pk is not None

    def test_raises_when_no_default_template(self) -> None:
        conf = _make_conference()
        attendee = _make_attendee(conf)
        service = BadgeGenerationService()
        with pytest.raises(ValueError, match="No default badge template"):
            service.generate_or_get_badge(attendee)

    def test_generates_png_format(self) -> None:
        conf = _make_conference()
        attendee = _make_attendee(conf)
        tpl = _make_template(conf)
        service = BadgeGenerationService()
        badge = service.generate_or_get_badge(attendee, template=tpl, badge_format="png")
        assert badge.format == Badge.Format.PNG
        assert badge.file


# -- Tests: bulk_generate_badges ----------------------------------------------


@pytest.mark.unit
class TestBulkGenerateBadges:
    """Tests for bulk badge generation."""

    def test_bulk_generate_all_attendees(self) -> None:
        conf = _make_conference()
        _make_attendee(conf)
        _make_attendee(conf)
        _make_attendee(conf)
        tpl = _make_template(conf)
        service = BadgeGenerationService()
        badges = list(service.bulk_generate_badges(conf, template=tpl))
        assert len(badges) == 3
        assert all(b.generated_at is not None for b in badges)

    def test_bulk_generate_filtered_by_ticket_type(self) -> None:
        conf = _make_conference()
        tt_individual = _make_ticket_type(conf, name="Individual", slug="individual")
        tt_corporate = _make_ticket_type(conf, name="Corporate", slug="corporate")

        # User with individual ticket
        user1 = _make_user()
        order1 = _make_order_with_ticket(conf, user1, tt_individual)
        Attendee.objects.create(user=user1, conference=conf, order=order1)

        # User with corporate ticket
        user2 = _make_user()
        order2 = _make_order_with_ticket(conf, user2, tt_corporate)
        Attendee.objects.create(user=user2, conference=conf, order=order2)

        tpl = _make_template(conf)
        service = BadgeGenerationService()
        badges = list(service.bulk_generate_badges(conf, template=tpl, ticket_type=tt_individual))
        assert len(badges) == 1

    def test_bulk_generate_empty_conference(self) -> None:
        conf = _make_conference()
        tpl = _make_template(conf)
        service = BadgeGenerationService()
        badges = list(service.bulk_generate_badges(conf, template=tpl))
        assert len(badges) == 0
