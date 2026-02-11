"""TOML loader for conference bootstrap configuration.

Loads and validates a conference TOML file (see ``conference.example.toml``)
so that conferences, sections, ticket types, add-ons, sponsor levels, and
vouchers can be created programmatically.
"""

import re
import tomllib
from decimal import Decimal
from pathlib import Path
from typing import Any

_REQUIRED_CONFERENCE_FIELDS: set[str] = {"name", "start", "end", "timezone"}
_REQUIRED_SECTION_FIELDS: set[str] = {"name", "start", "end"}
_REQUIRED_TICKET_FIELDS: set[str] = {"name", "price", "quantity"}

_SLUG_RE = re.compile(r"[^\w\s-]")
_WHITESPACE_RE = re.compile(r"[-\s]+")


def _slugify(value: str) -> str:
    """Convert a string to a URL-friendly slug.

    Args:
        value: The string to slugify.

    Returns:
        Lowercase, hyphen-separated slug.
    """
    value = _SLUG_RE.sub("", value.lower())
    return _WHITESPACE_RE.sub("-", value).strip("-")


def _ensure_slugs(items: list[dict[str, Any]], label: str) -> None:
    """Add a ``slug`` key derived from ``name`` to each item that lacks one.

    Args:
        items: List of config mappings to process.
        label: Human-readable context for error messages.
    """
    for idx, item in enumerate(items):
        if "slug" not in item:
            if "name" not in item:
                msg = f"{label}[{idx}] is missing required field: name"
                raise ValueError(msg)
            item["slug"] = _slugify(item["name"])


def _validate_unique_slugs(items: list[dict[str, Any]], label: str) -> None:
    """Ensure each item has a unique, non-empty string slug."""
    seen: set[str] = set()
    duplicates: set[str] = set()

    for idx, item in enumerate(items):
        slug = item.get("slug")
        if not isinstance(slug, str) or not slug:
            msg = f"{label}[{idx}].slug must be a non-empty string"
            raise ValueError(msg)
        if slug in seen:
            duplicates.add(slug)
        seen.add(slug)

    if duplicates:
        msg = f"{label} has duplicate slugs: {', '.join(sorted(duplicates))}"
        raise ValueError(msg)


def _validate_list(
    conf: dict[str, Any],
    key: str,
    required_fields: set[str] | None = None,
    *,
    must_exist: bool = False,
) -> None:
    """Validate and slugify an optional list of mappings within the conference config.

    Args:
        conf: The conference config dict.
        key: The key to validate (e.g. ``"sections"``, ``"tickets"``).
        required_fields: If given, validate each item has these fields.
        must_exist: If ``True``, the key must be present and non-empty.
    """
    label = f"conference.{key}"
    items = conf.get(key)

    if items is None:
        if must_exist:
            msg = f"{label} must be a non-empty list"
            raise ValueError(msg)
        return

    if not isinstance(items, list) or (must_exist and len(items) == 0):
        msg = f"{label} must be a non-empty list"
        raise ValueError(msg)

    for idx, item in enumerate(items):
        _validate_mapping(item, required_fields or set(), f"{label}[{idx}]")

    _ensure_slugs(items, label)
    _validate_unique_slugs(items, label)


def load_conference_config(path: str | Path) -> dict[str, Any]:
    """Load and validate a conference TOML configuration file.

    Args:
        path: Filesystem path to the TOML file.

    Returns:
        The ``conference`` mapping from the parsed TOML, with native types
        (``datetime.date`` for dates, ``Decimal`` for prices). Slugs are
        auto-generated from ``name`` when not explicitly provided.

    Raises:
        FileNotFoundError: If *path* does not exist.
        ValueError: If required keys or fields are missing, or the file is
            not valid TOML.
    """
    path = Path(path)
    if not path.exists():
        msg = f"Conference config file not found: {path}"
        raise FileNotFoundError(msg)

    with path.open("rb") as fh:
        try:
            data: dict[str, Any] = tomllib.load(fh, parse_float=Decimal)
        except tomllib.TOMLDecodeError as exc:
            msg = f"Invalid TOML in {path}: {exc}"
            raise ValueError(msg) from exc

    if "conference" not in data:
        msg = "Missing required [conference] table in config file"
        raise ValueError(msg)

    conf = data["conference"]

    _validate_mapping(conf, _REQUIRED_CONFERENCE_FIELDS, "conference")
    if "slug" not in conf:
        conf["slug"] = _slugify(conf["name"])

    _validate_list(conf, "sections", _REQUIRED_SECTION_FIELDS, must_exist=True)
    _validate_list(conf, "tickets", _REQUIRED_TICKET_FIELDS)
    _validate_list(conf, "addons")
    _validate_list(conf, "sponsor_levels")

    return conf


def _validate_mapping(mapping: object, required: set[str], label: str) -> None:
    """Validate that *mapping* is a dict containing all *required* keys.

    Args:
        mapping: The value to validate.
        required: Set of required key names.
        label: Human-readable context for error messages.

    Raises:
        TypeError: If *mapping* is not a dict.
        ValueError: If *mapping* is missing required keys.
    """
    if not isinstance(mapping, dict):
        msg = f"{label} must be a mapping, got {type(mapping).__name__}"
        raise TypeError(msg)
    missing = required - mapping.keys()
    if missing:
        msg = f"{label} is missing required fields: {', '.join(sorted(missing))}"
        raise ValueError(msg)
