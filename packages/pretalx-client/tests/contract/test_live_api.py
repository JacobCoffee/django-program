"""Contract tests that hit the live Pretalx API.

These tests are gated by the ``PRETALX_API_TOKEN`` and ``PRETALX_EVENT_SLUG``
environment variables. When either is missing the entire module is skipped.
"""

import pytest

from pretalx_client.models import PretalxSlot, PretalxSpeaker, PretalxTalk


@pytest.mark.integration
class TestLiveFetchSpeakers:
    """Verify fetch_speakers() against the live API."""

    def test_fetch_speakers_returns_list(self, live_client):
        speakers = live_client.fetch_speakers()
        assert isinstance(speakers, list)
        if not speakers:
            pytest.skip("API returned no speakers for this event")
        assert all(isinstance(s, PretalxSpeaker) for s in speakers)
        assert speakers[0].code  # non-empty code


@pytest.mark.integration
class TestLiveFetchTalks:
    """Verify fetch_talks() against the live API."""

    def test_fetch_talks_returns_list(self, live_client):
        talks = live_client.fetch_talks()
        assert isinstance(talks, list)
        if not talks:
            pytest.skip("API returned no talks for this event")
        assert all(isinstance(t, PretalxTalk) for t in talks)
        assert talks[0].code  # non-empty code


@pytest.mark.integration
class TestLiveFetchSchedule:
    """Verify fetch_schedule() against the live API."""

    def test_fetch_schedule_returns_list(self, live_client):
        schedule = live_client.fetch_schedule()
        assert isinstance(schedule, list)
        if not schedule:
            pytest.skip("API returned no schedule slots for this event")
        assert all(isinstance(s, PretalxSlot) for s in schedule)


@pytest.mark.integration
class TestLiveFetchRooms:
    """Verify fetch_rooms() against the live API."""

    def test_fetch_rooms_returns_dict(self, live_client):
        rooms = live_client.fetch_rooms()
        assert isinstance(rooms, dict)
        if not rooms:
            pytest.skip("API returned no rooms for this event")
        first_key = next(iter(rooms))
        assert isinstance(first_key, int)
        assert isinstance(rooms[first_key], str)
