"""Tests for sponsor template tags."""

from datetime import date
from decimal import Decimal
from unittest.mock import PropertyMock, patch

import pytest
from django.template import Context, Template

from django_program.conference.models import Conference
from django_program.sponsors.models import Sponsor, SponsorLevel
from django_program.sponsors.templatetags.sponsor_tags import (
    sponsor_logo_url,
    sponsors_by_level,
)


@pytest.fixture
def conference() -> Conference:
    return Conference.objects.create(
        name="SponsorTagCon",
        slug="sponsortagcon",
        start_date=date(2027, 6, 1),
        end_date=date(2027, 6, 3),
        timezone="UTC",
    )


@pytest.fixture
def gold_level(conference: Conference) -> SponsorLevel:
    return SponsorLevel.objects.create(
        conference=conference,
        name="Gold",
        cost=Decimal("10000.00"),
        order=1,
    )


@pytest.fixture
def silver_level(conference: Conference) -> SponsorLevel:
    return SponsorLevel.objects.create(
        conference=conference,
        name="Silver",
        cost=Decimal("5000.00"),
        order=2,
    )


# ---------------------------------------------------------------------------
# sponsors_by_level
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_sponsors_by_level_empty_conference(conference: Conference):
    result = sponsors_by_level(conference)

    assert result == []


@pytest.mark.django_db
def test_sponsors_by_level_excludes_inactive(conference: Conference, gold_level: SponsorLevel):
    Sponsor.objects.create(
        conference=conference,
        level=gold_level,
        name="Active Corp",
        is_active=True,
    )
    Sponsor.objects.create(
        conference=conference,
        level=gold_level,
        name="Inactive Corp",
        is_active=False,
    )

    result = sponsors_by_level(conference)

    assert len(result) == 1
    assert len(result[0]["sponsors"]) == 1
    assert result[0]["sponsors"][0].name == "Active Corp"


@pytest.mark.django_db
def test_sponsors_by_level_groups_and_orders(
    conference: Conference,
    gold_level: SponsorLevel,
    silver_level: SponsorLevel,
):
    Sponsor.objects.create(conference=conference, level=gold_level, name="Zeta Gold")
    Sponsor.objects.create(conference=conference, level=gold_level, name="Alpha Gold")
    Sponsor.objects.create(conference=conference, level=silver_level, name="Beta Silver")

    result = sponsors_by_level(conference)

    assert len(result) == 2
    assert result[0]["level"] == gold_level
    assert [s.name for s in result[0]["sponsors"]] == ["Alpha Gold", "Zeta Gold"]
    assert result[1]["level"] == silver_level
    assert [s.name for s in result[1]["sponsors"]] == ["Beta Silver"]


@pytest.mark.django_db
def test_sponsors_by_level_skips_empty_levels(
    conference: Conference,
    gold_level: SponsorLevel,
    silver_level: SponsorLevel,
):
    Sponsor.objects.create(conference=conference, level=gold_level, name="Solo Corp")

    result = sponsors_by_level(conference)

    assert len(result) == 1
    assert result[0]["level"] == gold_level


@pytest.mark.django_db
def test_sponsors_by_level_template_rendering(
    conference: Conference,
    gold_level: SponsorLevel,
):
    Sponsor.objects.create(conference=conference, level=gold_level, name="Template Corp")

    tpl = Template(
        "{% load sponsor_tags %}"
        "{% sponsors_by_level conference as groups %}"
        "{% for g in groups %}{{ g.level.name }}:{% for s in g.sponsors %}{{ s.name }}{% endfor %}{% endfor %}"
    )
    rendered = tpl.render(Context({"conference": conference}))

    assert "Gold:Template Corp" in rendered


# ---------------------------------------------------------------------------
# sponsor_logo_url
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_sponsor_logo_url_no_logo(conference: Conference, gold_level: SponsorLevel):
    sponsor = Sponsor.objects.create(
        conference=conference,
        level=gold_level,
        name="No Logo Corp",
    )

    result = sponsor_logo_url(sponsor)

    assert result == ""


@pytest.mark.django_db
def test_sponsor_logo_url_uses_logo_url_field(conference: Conference, gold_level: SponsorLevel):
    sponsor = Sponsor.objects.create(
        conference=conference,
        level=gold_level,
        name="Remote Logo Corp",
        logo_url="https://example.com/logo.png",
    )

    result = sponsor_logo_url(sponsor)

    assert result == "https://example.com/logo.png"


@pytest.mark.django_db
def test_sponsor_logo_url_prefers_uploaded_logo(conference: Conference, gold_level: SponsorLevel):
    sponsor = Sponsor.objects.create(
        conference=conference,
        level=gold_level,
        name="Upload Logo Corp",
        logo_url="https://example.com/fallback.png",
    )
    sponsor.logo.name = "sponsors/logos/test.png"
    with patch.object(
        type(sponsor.logo), "url", new_callable=PropertyMock, return_value="/media/sponsors/logos/test.png"
    ):
        result = sponsor_logo_url(sponsor)

    assert result == "/media/sponsors/logos/test.png"


@pytest.mark.django_db
def test_sponsor_logo_url_template_rendering(conference: Conference, gold_level: SponsorLevel):
    sponsor = Sponsor.objects.create(
        conference=conference,
        level=gold_level,
        name="Tag Logo Corp",
        logo_url="https://example.com/tag-logo.png",
    )

    tpl = Template("{% load sponsor_tags %}{% sponsor_logo_url sponsor as logo %}{{ logo }}")
    rendered = tpl.render(Context({"sponsor": sponsor}))

    assert rendered.strip() == "https://example.com/tag-logo.png"
