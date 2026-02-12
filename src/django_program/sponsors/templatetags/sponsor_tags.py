"""Template tags for the sponsors app."""

from typing import TYPE_CHECKING, Any

from django import template

from django_program.sponsors.models import Sponsor

if TYPE_CHECKING:
    from django_program.conference.models import Conference

register = template.Library()


@register.simple_tag
def sponsors_by_level(conference: Conference) -> list[dict[str, Any]]:
    """Group active sponsors by their sponsorship level for a conference.

    Returns a list of dictionaries, each containing a ``level``
    (:class:`~django_program.sponsors.models.SponsorLevel`) and its associated
    ``sponsors`` (a list of :class:`~django_program.sponsors.models.Sponsor`
    instances). Only active sponsors are included. Results are ordered by
    ``level.order`` then ``sponsor.name``.

    Usage in templates::

        {% load sponsor_tags %}
        {% sponsors_by_level conference as sponsor_groups %}
        {% for group in sponsor_groups %}
            <h2>{{ group.level.name }}</h2>
            {% for sponsor in group.sponsors %}
                <p>{{ sponsor.name }}</p>
            {% endfor %}
        {% endfor %}

    Args:
        conference: A :class:`~django_program.conference.models.Conference` instance.

    Returns:
        A list of dicts with ``"level"`` and ``"sponsors"`` keys.
    """
    sponsors = (
        Sponsor.objects.filter(
            conference=conference,
            is_active=True,
        )
        .select_related("level")
        .order_by("level__order", "level__name", "name")
    )

    grouped: dict[int, dict[str, Any]] = {}
    for sponsor in sponsors:
        level = sponsor.level
        group = grouped.get(level.pk)
        if group is None:
            group = {"level": level, "sponsors": []}
            grouped[level.pk] = group
        group["sponsors"].append(sponsor)

    return list(grouped.values())


@register.simple_tag
def sponsor_logo_url(sponsor: Sponsor) -> str:
    """Get the best available logo URL for a sponsor.

    Checks for a locally uploaded logo file first (``sponsor.logo``), then
    falls back to the remote ``logo_url`` field.  Returns an empty string if
    neither is available.

    Usage in templates::

        {% load sponsor_tags %}
        {% sponsor_logo_url sponsor as logo %}
        {% if logo %}
            <img src="{{ logo }}" alt="{{ sponsor.name }}">
        {% endif %}

    Args:
        sponsor: A :class:`~django_program.sponsors.models.Sponsor` instance.

    Returns:
        The logo URL string, or ``""`` if no logo is available.
    """
    if sponsor.logo and sponsor.logo.name:
        return str(sponsor.logo.url)
    if sponsor.logo_url:
        return str(sponsor.logo_url)
    return ""
