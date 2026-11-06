"""Configurable navigation for the management dashboard.

The sidebar and the Cmd/Ctrl-K palette are built from a :class:`NavRegistry`
instead of hard-coded template markup.  django-program registers its own
sections (see :mod:`django_program.manage.nav_builtin`); host projects add
their own sections and items, or trim the built-in ones, through
``DJANGO_PROGRAM["manage"]``::

    DJANGO_PROGRAM = {
        "manage": {
            "builtin_nav": ["conference"],  # keep only these built-in keys
            "hide_nav": ["conference-edit"],  # then drop these keys
            "nav": ["myproject.staff.nav.register"],
        },
    }

    # myproject/staff/nav.py
    from django_program.manage.nav import NavItem


    def register(registry):
        registry.section("desk", "Registration desk", order=10)
        registry.add(
            "desk",
            NavItem(
                key="desk-check-in",
                label="Check in attendees",
                url="registration:check_in",
                icon="check-square",
                permission="registration.check_in",
            ),
        )

Item URLs are URL names (reversed, with ``conference_slug`` when
``conference_url=True``) or literal paths/URLs (anything containing ``/``).
"""

import functools
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal

from django.core.exceptions import ImproperlyConfigured
from django.test.signals import setting_changed
from django.urls import NoReverseMatch, reverse
from django.utils.module_loading import import_string

from django_program.features import is_feature_enabled
from django_program.settings import get_config

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser, AnonymousUser
    from django.http import HttpRequest

    from django_program.conference.models import Conference

    User = AbstractUser | AnonymousUser

PermissionCheck = str | Sequence[str] | Callable[["User"], bool] | None
"""A permission string, any-of sequence of permission strings, a ``user -> bool``
callable, or ``None`` (visible to anyone who can see the shell)."""

Label = str | Callable[["NavContext"], str]


@dataclass(frozen=True, slots=True)
class NavContext:
    """Per-request inputs used to resolve visibility, URLs and labels."""

    request: HttpRequest
    conference: Conference | None
    active_nav: str = ""

    @property
    def user(self) -> User:
        """Return the requesting user."""
        return self.request.user


@dataclass(frozen=True, slots=True)
class NavItem:
    """One link (or POST action) in the sidebar and palette.

    Attributes:
        key: Globally unique key, also the default ``active_nav`` value.
        label: Link text, or a callable receiving the :class:`NavContext`.
        url: URL name or literal path/URL.
        icon: Icon name from the manage sprite (``dp-i-<name>``) or raw ``<svg>`` markup.
        permission: Visibility check, see :data:`PermissionCheck`.
        feature: django-program feature name; hidden when the feature is off.
        conference_url: Reverse ``url`` with ``conference_slug``; hidden without a conference.
        active: ``active_nav`` values that mark this item current (defaults to ``key``).
        group: Optional sub-heading inside the section.
        method: ``"post"`` renders a CSRF form button instead of a link.
        description: Extra palette search text.
        badge: Attention item key whose count is shown next to the label.
        children: Callable returning dynamic child items (e.g. talk types).
        order: Sort order inside the section; ties keep registration order.
    """

    key: str
    label: Label
    url: str
    icon: str = ""
    permission: PermissionCheck = None
    feature: str = ""
    conference_url: bool = False
    active: tuple[str, ...] = ()
    group: str = ""
    method: Literal["get", "post"] = "get"
    description: str = ""
    badge: str = ""
    children: Callable[[NavContext], Iterable[NavItem]] | None = None
    order: int = 0


@dataclass(frozen=True, slots=True)
class NavSection:
    """A titled, collapsible group of nav items.

    Attributes:
        key: Unique section key.
        label: Section title, or a callable receiving the :class:`NavContext`.
        order: Sort order among sections; ties keep registration order.
        permission: Extra visibility check for the whole section.
        feature: django-program feature name; hidden when the feature is off.
        utility: Render below a separator at the end of the sidebar.
    """

    key: str
    label: Label
    order: int = 0
    permission: PermissionCheck = None
    feature: str = ""
    utility: bool = False


@dataclass(slots=True)
class _SectionEntry:
    section: NavSection
    items: list[NavItem] = field(default_factory=list)


class NavRegistry:
    """Mutable registry of sections and items, built once per configuration."""

    def __init__(self) -> None:
        """Create an empty registry."""
        self._sections: dict[str, _SectionEntry] = {}
        self._item_sections: dict[str, str] = {}
        self._hidden: set[str] = set()

    def section(self, key: str, label: Label, **options: object) -> NavSection:
        """Add a section, or update an existing section's label and options.

        Args:
            key: Unique section key.
            label: Section title.
            **options: Other :class:`NavSection` fields.

        Returns:
            The stored section.
        """
        entry = self._sections.get(key)
        if entry is None:
            section = NavSection(key=key, label=label, **options)  # type: ignore[arg-type]
            self._sections[key] = _SectionEntry(section)
            return section
        entry.section = replace(entry.section, label=label, **options)
        return entry.section

    def add(self, section_key: str, *items: NavItem) -> None:
        """Append items to a section.

        Raises:
            ImproperlyConfigured: If the section does not exist or a key is taken.
        """
        entry = self._sections.get(section_key)
        if entry is None:
            msg = f"Unknown manage nav section {section_key!r}; call registry.section() first"
            raise ImproperlyConfigured(msg)
        for item in items:
            if item.key in self._item_sections or item.key in self._sections:
                msg = f"Duplicate manage nav key {item.key!r}"
                raise ImproperlyConfigured(msg)
            self._item_sections[item.key] = section_key
            entry.items.append(item)

    def remove(self, key: str) -> None:
        """Remove a section (with its items) or an item by key.

        Keys that are not registered statically (e.g. dynamic ``children``) are
        remembered and dropped when the nav is resolved.
        """
        entry = self._sections.pop(key, None)
        if entry is not None:
            for item in entry.items:
                self._item_sections.pop(item.key, None)
            return
        section_key = self._item_sections.pop(key, None)
        if section_key is None:
            self._hidden.add(key)
            return
        items = self._sections[section_key].items
        items[:] = [item for item in items if item.key != key]

    def is_hidden(self, key: str) -> bool:
        """Return whether a dynamic item key was removed with :meth:`remove`."""
        return key in self._hidden

    def keep(self, keys: Iterable[str]) -> None:
        """Keep only the given section or top-level item keys; everything else is removed.

        Dynamic ``children`` follow their parent item.
        """
        wanted = set(keys)
        for section_key in list(self._sections):
            if section_key in wanted:
                continue
            entry = self._sections[section_key]
            kept = [item for item in entry.items if item.key in wanted]
            if not kept:
                self.remove(section_key)
                continue
            for item in entry.items:
                if item.key not in wanted:
                    self._item_sections.pop(item.key, None)
            entry.items[:] = kept

    def __contains__(self, key: object) -> bool:
        """Return whether a section or item key is registered."""
        return key in self._sections or key in self._item_sections

    def entries(self) -> list[tuple[NavSection, list[NavItem]]]:
        """Return sections and their items in display order."""
        ordered = sorted(
            enumerate(self._sections.values()),
            key=lambda pair: (pair[1].section.utility, pair[1].section.order, pair[0]),
        )
        return [
            (entry.section, [item for _, item in sorted(enumerate(entry.items), key=lambda p: (p[1].order, p[0]))])
            for _, entry in ordered
        ]


@functools.lru_cache(maxsize=1)
def get_registry() -> NavRegistry:
    """Build the registry from built-ins plus ``DJANGO_PROGRAM["manage"]`` hooks.

    Order: built-in nav, ``builtin_nav`` filter, host ``nav`` callables, ``hide_nav``.

    Raises:
        ImproperlyConfigured: If a ``nav`` entry cannot be imported or is not callable.
    """
    from django_program.manage.nav_builtin import register_builtin_nav  # noqa: PLC0415

    config = get_config().manage
    registry = NavRegistry()
    if config.builtin_nav is not False:
        register_builtin_nav(registry)
        if config.builtin_nav is not True:
            registry.keep(config.builtin_nav)
    for path in config.nav:
        try:
            hook = import_string(path)
        except ImportError as exc:
            msg = f"DJANGO_PROGRAM['manage']['nav'] entry {path!r} could not be imported: {exc}"
            raise ImproperlyConfigured(msg) from exc
        if not callable(hook):
            msg = f"DJANGO_PROGRAM['manage']['nav'] entry {path!r} is not callable"
            raise ImproperlyConfigured(msg)
        hook(registry)
    for key in config.hide_nav:
        registry.remove(key)
    return registry


def _clear_registry_cache(*, setting: str, **kwargs: object) -> None:  # noqa: ARG001
    if setting == "DJANGO_PROGRAM":
        get_registry.cache_clear()


setting_changed.connect(_clear_registry_cache, dispatch_uid="django_program.manage.nav.clear_registry")


def has_full_manage_access(user: User) -> bool:
    """Return whether ``user`` bypasses built-in manage permission checks."""
    return bool(user.is_superuser or user.has_perm("program_conference.change_conference"))


def manage_perm(*perms: str) -> Callable[[User], bool]:
    """Build a check passing for full manage access or any of ``perms``.

    Bare codenames default to the ``program_conference`` app label, matching
    :class:`~django_program.manage.views.ConferencePermissionMixin`.
    """
    qualified = tuple(perm if "." in perm else f"program_conference.{perm}" for perm in perms)

    def check(user: User) -> bool:
        return has_full_manage_access(user) or any(user.has_perm(perm) for perm in qualified)

    return check


def check_permission(user: User, permission: PermissionCheck) -> bool:
    """Evaluate a :data:`PermissionCheck` for ``user``."""
    if permission is None:
        return True
    if isinstance(permission, str):
        return bool(user.has_perm(permission))
    if callable(permission):
        return bool(permission(user))
    return any(user.has_perm(perm) for perm in permission)


@dataclass(frozen=True, slots=True)
class ResolvedItem:
    """A nav item resolved for one request."""

    key: str
    label: str
    href: str
    icon: str
    group: str
    method: str
    description: str
    section_label: str
    is_active: bool = False
    badge_count: int | None = None
    children: tuple[ResolvedItem, ...] = ()

    @property
    def has_active_child(self) -> bool:
        """Return whether any descendant is the current page."""
        return any(child.is_active or child.has_active_child for child in self.children)


@dataclass(frozen=True, slots=True)
class ResolvedSection:
    """A visible section with its visible items."""

    key: str
    label: str
    utility: bool
    items: tuple[ResolvedItem, ...]

    @property
    def is_active(self) -> bool:
        """Return whether the current page belongs to this section."""
        return any(item.is_active or item.has_active_child for item in self.items)


def _label(label: Label, ctx: NavContext) -> str:
    return str(label(ctx) if callable(label) else label)


def _visible(entry: NavItem | NavSection, ctx: NavContext) -> bool:
    if entry.feature and not is_feature_enabled(entry.feature, conference=ctx.conference):
        return False
    return check_permission(ctx.user, entry.permission)


def _href(item: NavItem, ctx: NavContext) -> str | None:
    if "/" in item.url:
        return item.url
    kwargs = {}
    if item.conference_url:
        if ctx.conference is None:
            return None
        kwargs["conference_slug"] = ctx.conference.slug
    try:
        return reverse(item.url, kwargs=kwargs or None)
    except NoReverseMatch:
        return None


class _BadgeCounts:
    """Attention counts loaded on the first badge lookup, so pages without badges skip providers."""

    def __init__(self, source: Mapping[str, int] | Callable[[], Mapping[str, int]] | None) -> None:
        self._source = source
        self._counts: Mapping[str, int] | None = None

    def get(self, key: str) -> int | None:
        if self._counts is None:
            source = self._source
            self._counts = (source() if callable(source) else source) or {}
        return self._counts.get(key)


def _resolve_item(item: NavItem, ctx: NavContext, section_label: str, badges: _BadgeCounts) -> tuple[ResolvedItem, ...]:
    """Resolve one item, returning nothing, the item, or its promoted children.

    A failed permission check hides the item and its children.  When the item
    itself is unavailable for another reason (its feature is off, it needs a
    conference, or its URL does not reverse), its visible children take its place.
    """
    registry = get_registry()
    if registry.is_hidden(item.key) or not check_permission(ctx.user, item.permission):
        return ()
    children = tuple(
        resolved
        for raw in (item.children(ctx) if item.children else ())
        for resolved in _resolve_item(raw, ctx, section_label, badges)
    )
    feature_on = not item.feature or is_feature_enabled(item.feature, conference=ctx.conference)
    href = _href(item, ctx) if feature_on else None
    if href is None:
        return tuple(replace(child, group=item.group, icon=child.icon or item.icon) for child in children)
    return (
        ResolvedItem(
            key=item.key,
            label=_label(item.label, ctx),
            href=href,
            icon=item.icon,
            group=item.group,
            method=item.method,
            description=item.description,
            section_label=section_label,
            is_active=bool(ctx.active_nav) and ctx.active_nav in (item.active or (item.key,)),
            badge_count=badges.get(item.badge) if item.badge else None,
            children=children,
        ),
    )


def _prefix_length(item: ResolvedItem, path: str) -> int:
    """Return ``len(item.href)`` when it is a GET path prefix of ``path``, else ``-1``."""
    if item.method == "get" and item.href.startswith("/") and path.startswith(item.href):
        return len(item.href)
    return -1


def _mark(item: ResolvedItem, key: str) -> ResolvedItem:
    children = tuple(_mark(child, key) for child in item.children)
    return replace(item, is_active=item.key == key, children=children)


def _walk(items: Iterable[ResolvedItem]) -> Iterable[ResolvedItem]:
    for item in items:
        yield item
        yield from _walk(item.children)


def _settle_active(sections: list[ResolvedSection], path: str) -> list[ResolvedSection]:
    """Leave exactly one current entry, or none when nothing matches.

    Entries matching ``active_nav`` compete by longest URL prefix of ``path``
    (several can share a value, e.g. a parent and its sub-tabs or promoted
    children); without a prefix match the first in display order wins.  With no
    ``active_nav`` match, the longest URL prefix of ``path`` among all entries wins.
    """
    entries = [entry for section in sections for entry in _walk(section.items)]
    active = [entry for entry in entries if entry.is_active]
    if len(active) == 1 or not entries:
        return sections
    candidates = active or entries
    best = max(candidates, key=lambda entry: _prefix_length(entry, path))
    if _prefix_length(best, path) < 0:
        if not active:
            return sections
        best = active[0]
    return [replace(section, items=tuple(_mark(item, best.key) for item in section.items)) for section in sections]


def build_nav(
    request: HttpRequest,
    *,
    conference: Conference | None = None,
    active_nav: str = "",
    badges: Mapping[str, int] | Callable[[], Mapping[str, int]] | None = None,
) -> list[ResolvedSection]:
    """Resolve the registry for one request.

    Items are hidden when their feature is off, the permission check fails,
    they need a conference that is not available, or their URL name does not
    reverse (module URLs not mounted).  When no item matches ``active_nav``,
    the item whose URL is the longest prefix of ``request.path`` is marked active.

    Args:
        request: The current request (``request.user`` is checked).
        conference: The conference in scope, if any.
        active_nav: The page's ``active_nav`` value.
        badges: Attention counts keyed by attention item key, or a callable
            returning them; a callable runs only if a visible item has a badge.

    Returns:
        Visible sections in display order, each with at least one item.
    """
    ctx = NavContext(request=request, conference=conference, active_nav=active_nav)
    counts = _BadgeCounts(badges)
    sections: list[ResolvedSection] = []
    for section, items in get_registry().entries():
        if not _visible(section, ctx):
            continue
        label = _label(section.label, ctx)
        resolved = tuple(entry for raw in items for entry in _resolve_item(raw, ctx, label, counts))
        if resolved:
            sections.append(ResolvedSection(key=section.key, label=label, utility=section.utility, items=resolved))
    return _settle_active(sections, request.path)
