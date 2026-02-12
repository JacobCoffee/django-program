"""Talks fetch adapter with endpoint fallback logic.

Encapsulates the pattern where the Pretalx ``/talks/`` endpoint is tried
first and, when it returns 404 (as it does for some events like PyCon US),
falls back to ``/submissions/`` with both ``confirmed`` and ``accepted``
states to capture all scheduled content.
"""

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pretalx_client.client import PretalxClient

logger = logging.getLogger(__name__)


def fetch_talks_with_fallback(
    client: PretalxClient,
) -> list[dict[str, Any]]:
    """Fetch raw talk dicts, falling back from ``/talks/`` to ``/submissions/``.

    Tries the ``/talks/`` endpoint first. When that returns 404 (as it
    does for some Pretalx events like PyCon US), falls back to
    ``/submissions/`` with both ``confirmed`` and ``accepted`` states to
    capture all scheduled content including tutorials and sponsor talks.

    Args:
        client: A :class:`~pretalx_client.client.PretalxClient` instance.

    Returns:
        A list of raw API dicts representing talks or submissions.
    """
    url = f"{client.api_url}talks/"
    raw = client._get_paginated_or_none(url)  # noqa: SLF001
    if raw is None:
        logger.info("talks/ endpoint returned 404, falling back to submissions/ with confirmed+accepted states")
        confirmed = client._get_paginated(  # noqa: SLF001
            f"{client.api_url}submissions/?state=confirmed"
        )
        accepted = client._get_paginated(  # noqa: SLF001
            f"{client.api_url}submissions/?state=accepted"
        )
        raw = confirmed + accepted
        logger.info(
            "Fetched %d confirmed + %d accepted = %d submissions",
            len(confirmed),
            len(accepted),
            len(raw),
        )
    return raw
