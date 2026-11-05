"""Pluggable "needs attention" counts for the management dashboard.

Providers are callables ``(request, conference) -> Iterable[AttentionItem]``
listed in ``DJANGO_PROGRAM["manage"]["attention"]``.  Their items appear on
the dashboard and as sidebar badges for nav items whose ``badge`` matches the
item ``key``.  Results are computed at most once per request.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from django_program.settings import get_config

if TYPE_CHECKING:
    from django.http import HttpRequest

    from django_program.conference.models import Conference

Tone = Literal["info", "success", "warning", "danger"]
AttentionProvider = Callable[["HttpRequest", "Conference | None"], Iterable["AttentionItem"]]

_REQUEST_CACHE_ATTR = "_django_program_attention"


@dataclass(frozen=True, slots=True)
class AttentionItem:
    """One count that may need staff action.

    Attributes:
        key: Unique key; nav items with ``badge=key`` show ``count``.
        label: Short description, e.g. "Receipts to review".
        count: Current count.
        url: Where to act on it (already resolved).
        tone: Visual emphasis.
        description: Optional supporting sentence.
    """

    key: str
    label: str
    count: int
    url: str = ""
    tone: Tone = "warning"
    description: str = ""


def _load_providers() -> list[AttentionProvider]:
    providers: list[AttentionProvider] = []
    for path in get_config().manage.attention:
        try:
            provider = import_string(path)
        except ImportError as exc:
            msg = f"DJANGO_PROGRAM['manage']['attention'] entry {path!r} could not be imported: {exc}"
            raise ImproperlyConfigured(msg) from exc
        if not callable(provider):
            msg = f"DJANGO_PROGRAM['manage']['attention'] entry {path!r} is not callable"
            raise ImproperlyConfigured(msg)
        providers.append(provider)
    return providers


def get_attention(request: HttpRequest, conference: Conference | None) -> list[AttentionItem]:
    """Return attention items from every configured provider, cached on the request.

    Args:
        request: The current request.
        conference: The conference in scope, if any.

    Returns:
        Items in provider order.
    """
    cached = getattr(request, _REQUEST_CACHE_ATTR, None)
    if cached is not None:
        return cached
    items = [item for provider in _load_providers() for item in provider(request, conference)]
    setattr(request, _REQUEST_CACHE_ATTR, items)
    return items


def attention_counts(request: HttpRequest, conference: Conference | None) -> dict[str, int]:
    """Return ``{item.key: item.count}`` for sidebar badges."""
    return {item.key: item.count for item in get_attention(request, conference)}
