"""Template tag resolving the manage shell (nav, config, palette) for a page.

Usage::

    {% load manage_shell %}
    {% manage_shell as shell %}

``shell`` exposes ``nav`` (resolved sections), ``conference``, ``config``
(the :class:`~django_program.settings.ManageConfig`), ``home_href``,
``logout_href``, ``logout_same_origin`` and ``palette_items``.  Works on any
page that extends ``django_program/manage/base.html``, including host pages
that only have ``request`` and ``user`` in context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from django import template
from django.apps import apps
from django.urls import NoReverseMatch, reverse
from django.utils.html import escape
from django.utils.safestring import mark_safe

from django_program.manage.attention import attention_counts
from django_program.manage.nav import ResolvedItem, ResolvedSection, build_nav, is_same_origin, manage_perm
from django_program.settings import ManageConfig, get_config

if TYPE_CHECKING:
    from django.http import HttpRequest

    from django_program.conference.models import Conference

register = template.Library()

_can_view_dashboard = manage_perm("view_dashboard")


@dataclass(frozen=True, slots=True)
class ManageShell:
    """Resolved manage shell data for one request."""

    nav: list[ResolvedSection]
    conference: Conference | None
    config: ManageConfig
    home_href: str
    logout_href: str
    logout_same_origin: bool = True
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
    """Return the django-program conference in scope.

    A ``conference`` context value from the host (its own model, a slug, ...) is
    ignored; only django-program ``Conference`` instances count.
    """
    if not apps.is_installed("django_program.conference"):
        return None
    from django_program.conference.models import Conference  # noqa: PLC0415

    if isinstance(context_conference, Conference):
        return context_conference
    if not config.conference:
        return None
    return Conference.objects.filter(slug=config.conference).first()


def _resolve_home_href(
    config: ManageConfig, conference: Conference | None, user: object, sections: list[ResolvedSection]
) -> str:
    """Return the top-bar title link.

    ``home_url`` wins. In single-conference mode the conference dashboard is used
    when the user may open it, otherwise their first sidebar page.  Without
    single-conference mode, the conference list.
    """
    if config.home_url:
        return _resolve_url(config.home_url)
    if config.conference and conference is not None:
        if _can_view_dashboard(user):
            try:
                return reverse("manage:dashboard", kwargs={"conference_slug": conference.slug})
            except NoReverseMatch:
                pass
        return next((item.href for section in sections for item in section.items if item.method == "get"), "")
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
                "same_origin": resolved.same_origin,
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
        context: The current template context. Without ``request`` (no
            ``django.template.context_processors.request``) the shell renders
            without navigation.

    Returns:
        A :class:`ManageShell` with nav, config, and palette data.
    """
    config = get_config().manage
    request: HttpRequest | None = context.get("request")
    if request is None:
        return ManageShell(
            nav=[],
            conference=None,
            config=config,
            home_href=_resolve_url(config.home_url),
            logout_href=_resolve_url(config.logout_url),
        )
    conference = _resolve_conference(context.get("conference"), config)
    active_nav = context.get("active_nav") or ""
    sections = build_nav(
        request,
        conference=conference,
        active_nav=active_nav,
        badges=lambda: attention_counts(request, conference),
    )
    logout_href = _resolve_url(config.logout_url)
    return ManageShell(
        nav=sections,
        conference=conference,
        config=config,
        home_href=_resolve_home_href(config, conference, request.user, sections),
        logout_href=logout_href,
        logout_same_origin=is_same_origin(logout_href, request) if logout_href else True,
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
