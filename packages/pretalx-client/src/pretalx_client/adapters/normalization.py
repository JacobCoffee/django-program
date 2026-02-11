"""Normalization helpers for Pretalx multilingual and ID-based fields.

Pretalx returns localized fields as either plain strings or dicts keyed by
language code (e.g. ``{"en": "Talk", "de": "Vortrag"}``).  It also returns
foreign-key fields as integer IDs in the real API but as inline objects in
the public/legacy API.  These helpers normalize both patterns into plain
Python strings.
"""

from typing import Any


def localized(value: str | dict[str, Any] | None) -> str:
    """Extract a display string from a Pretalx multilingual field.

    Pretalx returns localized fields as either a plain string or a dict
    keyed by language code (e.g. ``{"en": "Talk", "de": "Vortrag"}``).
    This helper returns the ``en`` value when available, falling back to
    the first available language, or an empty string for ``None``.

    Args:
        value: A string, a multilingual dict, an object with a ``name``
            dict, or ``None``.

    Returns:
        The resolved display string.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return str(value)

    if "en" in value:
        return str(value["en"])
    if "name" in value:
        return localized(value["name"])
    return next((v for v in value.values() if isinstance(v, str)), "")


def resolve_id_or_localized(
    value: int | str | dict[str, Any] | None,
    mapping: dict[int, str] | None = None,
) -> str:
    """Resolve a Pretalx field that may be an integer ID or a localized value.

    When the real API returns an integer ID (e.g. for ``submission_type``,
    ``track``, or ``room``), the optional mapping dict is used to look up the
    human-readable name.  Falls back to :func:`localized` for string/dict
    values, or ``str(value)`` for unmapped integers.

    Args:
        value: An integer ID, a string, a multilingual dict, or ``None``.
        mapping: Optional ``{id: name}`` dict for resolving integer IDs.

    Returns:
        The resolved display string, or empty string for ``None``.
    """
    if value is None:
        return ""
    if isinstance(value, int):
        if mapping and value in mapping:
            return mapping[value]
        return str(value)
    return localized(value)
