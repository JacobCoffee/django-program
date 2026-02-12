"""Tests for pretalx_client.adapters.talks -- fetch_talks_with_fallback()."""

from unittest.mock import patch

import pytest

from pretalx_client.adapters.talks import fetch_talks_with_fallback
from pretalx_client.client import PretalxClient


class TestFetchTalksWithFallback:
    """Tests for the talks endpoint fallback logic."""

    @pytest.fixture
    def client(self):
        return PretalxClient("evt")

    @pytest.mark.unit
    def test_talks_endpoint_succeeds(self, client):
        """When /talks/ returns a list, that data is used directly."""
        talks_data = [
            {"code": "T1", "title": "Talk One"},
            {"code": "T2", "title": "Talk Two"},
        ]
        with patch.object(client, "_get_paginated_or_none", return_value=talks_data) as mock_or_none:
            with patch.object(client, "_get_paginated") as mock_paginated:
                result = fetch_talks_with_fallback(client)

        mock_or_none.assert_called_once_with(f"{client.api_url}talks/")
        mock_paginated.assert_not_called()
        assert result == talks_data

    @pytest.mark.unit
    def test_talks_endpoint_returns_empty_list(self, client):
        """An empty list from /talks/ is still a success -- no fallback triggered."""
        with patch.object(client, "_get_paginated_or_none", return_value=[]) as mock_or_none:
            with patch.object(client, "_get_paginated") as mock_paginated:
                result = fetch_talks_with_fallback(client)

        mock_or_none.assert_called_once()
        mock_paginated.assert_not_called()
        assert result == []

    @pytest.mark.unit
    def test_talks_404_falls_back_to_submissions(self, client):
        """When /talks/ returns None (404), confirmed + accepted submissions are fetched."""
        confirmed = [{"code": "C1", "title": "Confirmed Talk"}]
        accepted = [{"code": "A1", "title": "Accepted Talk"}]

        with patch.object(client, "_get_paginated_or_none", return_value=None):
            with patch.object(client, "_get_paginated", side_effect=[confirmed, accepted]) as mock_paginated:
                result = fetch_talks_with_fallback(client)

        assert mock_paginated.call_count == 2
        first_url = mock_paginated.call_args_list[0].args[0]
        second_url = mock_paginated.call_args_list[1].args[0]
        assert first_url == f"{client.api_url}submissions/?state=confirmed"
        assert second_url == f"{client.api_url}submissions/?state=accepted"

        assert result == confirmed + accepted

    @pytest.mark.unit
    def test_fallback_combines_both_lists(self, client):
        """The fallback merges confirmed and accepted lists in order."""
        confirmed = [
            {"code": "C1", "title": "Confirmed 1"},
            {"code": "C2", "title": "Confirmed 2"},
        ]
        accepted = [
            {"code": "A1", "title": "Accepted 1"},
        ]

        with patch.object(client, "_get_paginated_or_none", return_value=None):
            with patch.object(client, "_get_paginated", side_effect=[confirmed, accepted]):
                result = fetch_talks_with_fallback(client)

        assert len(result) == 3
        assert result[0]["code"] == "C1"
        assert result[1]["code"] == "C2"
        assert result[2]["code"] == "A1"

    @pytest.mark.unit
    def test_fallback_both_empty(self, client):
        """When /talks/ 404s and both submission queries return empty, result is empty."""
        with patch.object(client, "_get_paginated_or_none", return_value=None):
            with patch.object(client, "_get_paginated", side_effect=[[], []]):
                result = fetch_talks_with_fallback(client)

        assert result == []

    @pytest.mark.unit
    def test_fallback_only_confirmed(self, client):
        """When accepted submissions is empty, only confirmed are returned."""
        confirmed = [{"code": "C1", "title": "Only Confirmed"}]

        with patch.object(client, "_get_paginated_or_none", return_value=None):
            with patch.object(client, "_get_paginated", side_effect=[confirmed, []]):
                result = fetch_talks_with_fallback(client)

        assert result == confirmed

    @pytest.mark.unit
    def test_fallback_only_accepted(self, client):
        """When confirmed submissions is empty, only accepted are returned."""
        accepted = [{"code": "A1", "title": "Only Accepted"}]

        with patch.object(client, "_get_paginated_or_none", return_value=None):
            with patch.object(client, "_get_paginated", side_effect=[[], accepted]):
                result = fetch_talks_with_fallback(client)

        assert result == accepted

    @pytest.mark.unit
    def test_uses_correct_api_url(self):
        """Verify the constructed URL uses the client's api_url attribute."""
        client = PretalxClient("pycon-us-2026", base_url="https://pretalx.pycon.org")
        talks_data = [{"code": "T1", "title": "Talk"}]

        with patch.object(client, "_get_paginated_or_none", return_value=talks_data) as mock_or_none:
            fetch_talks_with_fallback(client)

        expected_url = "https://pretalx.pycon.org/api/events/pycon-us-2026/talks/"
        mock_or_none.assert_called_once_with(expected_url)
