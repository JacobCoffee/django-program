"""Fixtures for contract tests that hit the live Pretalx API."""

import os

import pytest

from pretalx_client.client import PretalxClient


@pytest.fixture(scope="session")
def pretalx_api_token():
    """Read PRETALX_API_TOKEN from the environment, skip if not set."""
    token = os.environ.get("PRETALX_API_TOKEN", "")
    if not token:
        pytest.skip("PRETALX_API_TOKEN not set -- skipping live API tests")
    return token


@pytest.fixture(scope="session")
def pretalx_event_slug():
    """Read PRETALX_EVENT_SLUG from the environment, skip if not set."""
    slug = os.environ.get("PRETALX_EVENT_SLUG", "")
    if not slug:
        pytest.skip("PRETALX_EVENT_SLUG not set -- skipping live API tests")
    return slug


@pytest.fixture(scope="session")
def live_client(pretalx_api_token, pretalx_event_slug):
    """A PretalxClient configured against the live API."""
    return PretalxClient(
        pretalx_event_slug,
        api_token=pretalx_api_token,
    )
