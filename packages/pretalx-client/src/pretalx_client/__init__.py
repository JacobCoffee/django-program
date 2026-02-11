"""Standalone Python client for the Pretalx REST API."""

from pretalx_client.client import PretalxClient
from pretalx_client.models import PretalxSlot, PretalxSpeaker, PretalxTalk, SubmissionState

__all__ = [
    "PretalxClient",
    "PretalxSlot",
    "PretalxSpeaker",
    "PretalxTalk",
    "SubmissionState",
]
