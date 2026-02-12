"""Adapters for normalizing Pretalx API data.

This package provides helpers for handling Pretalx's multilingual fields,
ID-to-name resolution, datetime parsing, schedule slot normalization, and
the talks endpoint fallback pattern.
"""

from pretalx_client.adapters.normalization import localized, resolve_id_or_localized
from pretalx_client.adapters.schedule import normalize_slot, parse_datetime
from pretalx_client.adapters.talks import fetch_talks_with_fallback

__all__ = [
    "fetch_talks_with_fallback",
    "localized",
    "normalize_slot",
    "parse_datetime",
    "resolve_id_or_localized",
]
