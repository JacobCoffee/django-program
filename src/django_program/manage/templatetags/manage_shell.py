"""Template tag resolving the manage shell (nav, config, palette) for a page.

Usage::

    {% load manage_shell %}
    {% manage_shell as shell %}

``shell`` exposes ``nav`` (resolved sections), ``conference``, ``config``
(the :class:`~django_program.settings.ManageConfig`), ``home_href``,
``logout_href`` and ``palette_items``.  Works on any page that extends
``django_program/manage/base.html``, including host pages that only have
``request`` and ``user`` in context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from django import template
from django.urls import NoReverseMatch, reverse
from django.utils.html import escape
from django.utils.safestring import mark_safe

from django_program.manage.attention import attention_counts
from django_program.manage.nav import ResolvedItem, ResolvedSection, build_nav, nav_uses_badges
from django_program.settings import ManageConfig, get_config

if TYPE_CHECKING:
    from django.http import HttpRequest

    from django_program.conference.models import Conference

register = template.Library()


@dataclass(frozen=True, slots=True)
class ManageShell:
    """Resolved manage shell data for one request."""

    nav: list[ResolvedSection]
    conference: Conference | None
    config: ManageConfig
    home_href: str
    logout_href: str
    palette_items: list[dict[str, Any]] = field(default_factory=list)


def _resolve_url(name: str) -> str:
    """Resolve a URL name or literal path/URL; returns "" if it can't be resolved."""
    if not name:
        return ""
    if "/" in name:
        return name
    try:
        return reverse(name)
    except NoReverseMatch:
        return ""


def _resolve_conference(context_conference: object, config: ManageConfig) -> Conference | None:
    if context_conference:
        return context_conference  # type: ignore[return-value]
    if not config.conference:
        return None
    from django_program.conference.models import Conference  # noqa: PLC0415

    return Conference.objects.filter(slug=config.conference).first()


def _resolve_home_href(config: ManageConfig, conference: Conference | None) -> str:
    if config.home_url:
        return _resolve_url(config.home_url)
    if conference is not None:
        try:
            return reverse("manage:dashboard", kwargs={"conference_slug": conference.slug})
        except NoReverseMatch:
            pass
    try:
        return reverse("manage:conference-list")
    except NoReverseMatch:
        return ""


def _palette_items(sections: list[ResolvedSection]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    def add(resolved: ResolvedItem, section_label: str) -> None:
        items.append(
            {
                "key": resolved.key,
                "label": resolved.label,
                "href": resolved.href,
                "section": section_label,
                "description": resolved.description,
                "method": resolved.method,
            }
        )
        for child in resolved.children:
            add(child, section_label)

    for section in sections:
        for item in section.items:
            add(item, section.label)
    return items


@register.simple_tag(takes_context=True)
def manage_shell(context: template.Context) -> ManageShell:
    """Resolve the manage shell for the current page.

    Args:
        context: The current template context; must include ``request``.

    Returns:
        A :class:`ManageShell` with nav, config, and palette data.
    """
    request: HttpRequest = context["request"]
    config = get_config().manage
    conference = _resolve_conference(context.get("conference"), config)
    active_nav = context.get("active_nav") or ""
    badges = attention_counts(request, conference) if nav_uses_badges() else {}
    sections = build_nav(request, conference=conference, active_nav=active_nav, badges=badges)
    return ManageShell(
        nav=sections,
        conference=conference,
        config=config,
        home_href=_resolve_home_href(config, conference),
        logout_href=_resolve_url(config.logout_url),
        palette_items=_palette_items(sections),
    )


@register.filter
def group_nav_items(items: tuple[ResolvedItem, ...]) -> list[dict[str, Any]]:
    """Group resolved nav items into contiguous ``{"label": ..., "items": [...]}`` buckets.

    Items with no ``group`` get an empty-string bucket label.
    """
    groups: list[dict[str, Any]] = []
    for item in items:
        label = item.group
        if groups and groups[-1]["label"] == label:
            groups[-1]["items"].append(item)
        else:
            groups.append({"label": label, "items": [item]})
    return groups


@register.filter
def nav_icon(icon: str) -> str:
    """Render a nav item's icon: a sprite reference, or raw ``<svg>`` markup verbatim."""
    if not icon:
        return ""
    if "<svg" in icon:
        return mark_safe(icon)  # noqa: S308 -- icon is developer-configured, not user input
    markup = f'<svg class="sidebar-nav-icon-svg" aria-hidden="true"><use href="#dp-i-{escape(icon)}"></use></svg>'
    return mark_safe(markup)  # noqa: S308 -- markup is built from an escaped, developer-configured name
