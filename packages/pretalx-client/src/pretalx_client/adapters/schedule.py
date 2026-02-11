"""Schedule slot parsing and datetime normalization for Pretalx API data.

Handles the differences between the legacy Pretalx schedule format (string
room/code/title) and the paginated ``/slots/`` endpoint format (integer
room IDs, ``submission`` key instead of ``code``, no ``title``).
"""

from datetime import datetime
from typing import Any

from pretalx_client.adapters.normalization import localized, resolve_id_or_localized


def parse_datetime(value: str) -> datetime | None:
    """Parse an ISO 8601 datetime string, returning ``None`` on failure.

    Args:
        value: An ISO 8601 formatted datetime string.

    Returns:
        A ``datetime`` instance, or ``None`` if the string is empty or
        cannot be parsed.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):  # fmt: skip
        return None


def normalize_slot(
    data: dict[str, Any],
    *,
    rooms: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Normalize a raw Pretalx slot dict into a consistent field set.

    Handles both the legacy format (string ``room``, ``code``, ``title``
    keys) and the real paginated ``/slots/`` format (integer ``room`` ID,
    ``submission`` key instead of ``code``, no ``title``).

    Args:
        data: A single slot object from the Pretalx schedule endpoint.
        rooms: Optional ``{id: name}`` mapping for resolving integer
            room IDs.

    Returns:
        A dict with normalized keys: ``room``, ``start``, ``end``,
        ``code``, ``title``, ``start_dt``, ``end_dt``.
    """
    start_str = data.get("start") or ""
    end_str = data.get("end") or ""

    room_raw = data.get("room")
    room = resolve_id_or_localized(room_raw, rooms)

    code = data.get("submission") or data.get("code") or ""
    title = localized(data.get("title")) if "title" in data else ""

    return {
        "room": room,
        "start": start_str,
        "end": end_str,
        "code": code,
        "title": title,
        "start_dt": parse_datetime(start_str),
        "end_dt": parse_datetime(end_str),
    }
