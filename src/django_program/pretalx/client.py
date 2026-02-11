"""Re-exports from the standalone ``pretalx-client`` library.

The HTTP client and typed dataclasses have been extracted into the
``pretalx-client`` workspace package.  This module re-exports everything
so that existing imports from ``django_program.pretalx.client`` continue
to work without changes.
"""

from pretalx_client.client import PretalxClient
from pretalx_client.models import (
    PretalxSlot,
    PretalxSpeaker,
    PretalxTalk,
    SubmissionState,
    _localized,
    _parse_datetime,
    _resolve_id_or_localized,
)

__all__ = [
    "PretalxClient",
    "PretalxSlot",
    "PretalxSpeaker",
    "PretalxTalk",
    "SubmissionState",
    "_localized",
    "_parse_datetime",
    "_resolve_id_or_localized",
]
