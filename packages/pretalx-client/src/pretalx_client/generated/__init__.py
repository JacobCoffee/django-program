"""Generated Pretalx API models and HTTP client from OpenAPI schema.

Re-exports the key generated types used by the handwritten adapter layer
in :mod:`pretalx_client.models`, plus the generated HTTP client class.
Import from here rather than reaching into sub-modules directly.
"""

from pretalx_client.generated.http_client import GeneratedPretalxClient
from pretalx_client.generated.models import (
    Room as GeneratedRoom,
)
from pretalx_client.generated.models import (
    Speaker as GeneratedSpeaker,
)
from pretalx_client.generated.models import (
    SpeakerOrga as GeneratedSpeakerOrga,
)
from pretalx_client.generated.models import (
    StateEnum,
)
from pretalx_client.generated.models import (
    Submission as GeneratedSubmission,
)
from pretalx_client.generated.models import (
    TalkSlot as GeneratedTalkSlot,
)

__all__ = [
    "GeneratedPretalxClient",
    "GeneratedRoom",
    "GeneratedSpeaker",
    "GeneratedSpeakerOrga",
    "GeneratedSubmission",
    "GeneratedTalkSlot",
    "StateEnum",
]
