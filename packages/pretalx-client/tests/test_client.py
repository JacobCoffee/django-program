"""Tests for pretalx_client.client -- PretalxClient HTTP layer."""

from unittest.mock import MagicMock, Mock, patch

import httpx
import pytest

from pretalx_client.client import PretalxClient
from pretalx_client.models import PretalxSlot, PretalxSpeaker, PretalxTalk

# ---------------------------------------------------------------------------
# PretalxClient.__init__()
# ---------------------------------------------------------------------------


class TestPretalxClientInit:
    """Tests for client initialization and URL normalization."""

    @pytest.mark.unit
    def test_default_base_url(self):
        client = PretalxClient("my-event")
        assert client.base_url == "https://pretalx.com"
        assert client.event_slug == "my-event"
        assert client.api_url == "https://pretalx.com/api/events/my-event/"

    @pytest.mark.unit
    def test_trailing_slash_stripped(self):
        client = PretalxClient("evt", base_url="https://pretalx.example.com/")
        assert client.base_url == "https://pretalx.example.com"
        assert client.api_url == "https://pretalx.example.com/api/events/evt/"

    @pytest.mark.unit
    def test_api_suffix_stripped(self):
        """If the user passes a URL ending in /api, it gets normalized."""
        client = PretalxClient("evt", base_url="https://pretalx.example.com/api")
        assert client.base_url == "https://pretalx.example.com"
        assert client.api_url == "https://pretalx.example.com/api/events/evt/"

    @pytest.mark.unit
    def test_trailing_slash_and_api_suffix(self):
        client = PretalxClient("evt", base_url="https://pretalx.example.com/api/")
        assert client.base_url == "https://pretalx.example.com"

    @pytest.mark.unit
    def test_no_token_no_auth_header(self):
        client = PretalxClient("evt")
        assert "Authorization" not in client.headers
        assert client.headers["Accept"] == "application/json"

    @pytest.mark.unit
    def test_empty_token_no_auth_header(self):
        client = PretalxClient("evt", api_token="")
        assert "Authorization" not in client.headers

    @pytest.mark.unit
    def test_token_sets_auth_header(self):
        client = PretalxClient("evt", api_token="abc123")
        assert client.headers["Authorization"] == "Token abc123"

    @pytest.mark.unit
    def test_api_token_stored(self):
        client = PretalxClient("evt", api_token="secret")
        assert client.api_token == "secret"

    @pytest.mark.unit
    def test_generated_client_created(self):
        """Verify that __init__ creates a GeneratedPretalxClient instance."""
        client = PretalxClient("evt", api_token="tok")
        assert client._http is not None
        assert client._http.base_url == "https://pretalx.com"
        assert client._http.api_token == "tok"


# ---------------------------------------------------------------------------
# Helpers for mocking httpx (used for _get_paginated / _get_paginated_or_none)
# ---------------------------------------------------------------------------


def _make_response(json_data, status_code=200, url="https://pretalx.com/api/events/evt/"):
    """Build a mock httpx.Response."""
    response = Mock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_data
    response.raise_for_status = Mock()

    # For error responses, make raise_for_status actually raise
    if status_code >= 400:
        request = Mock(spec=httpx.Request)
        request.url = url
        response.request = request
        exc = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=request,
            response=response,
        )
        response.raise_for_status.side_effect = exc

    return response


def _make_mock_client_cm(responses):
    """Build a context-manager mock for httpx.Client that returns responses in order.

    ``responses`` is a list of mock response objects.  Each call to
    ``client.get()`` pops the next response from the list.
    """
    mock_http_client = MagicMock()
    mock_http_client.get = Mock(side_effect=responses)
    mock_cm = MagicMock()
    mock_cm.__enter__ = Mock(return_value=mock_http_client)
    mock_cm.__exit__ = Mock(return_value=False)
    return mock_cm, mock_http_client


# ---------------------------------------------------------------------------
# PretalxClient._get_paginated()
# ---------------------------------------------------------------------------


class TestGetPaginated:
    """Tests for the _get_paginated() pagination handler.

    Now delegates to GeneratedPretalxClient._paginate(), so we mock httpx
    at the generated module level.
    """

    @pytest.mark.unit
    @patch("pretalx_client.generated.http_client.httpx.Client")
    def test_single_page(self, mock_client_cls):
        page = _make_response({"results": [{"id": 1}, {"id": 2}], "next": None})
        mock_cm, mock_http = _make_mock_client_cm([page])
        mock_client_cls.return_value = mock_cm

        client = PretalxClient("evt")
        results = client._get_paginated("https://pretalx.com/api/events/evt/speakers/")

        assert results == [{"id": 1}, {"id": 2}]
        mock_http.get.assert_called_once()

    @pytest.mark.unit
    @patch("pretalx_client.generated.http_client.httpx.Client")
    def test_multiple_pages(self, mock_client_cls):
        page1 = _make_response(
            {
                "results": [{"id": 1}],
                "next": "https://pretalx.com/api/events/evt/speakers/?page=2",
            }
        )
        page2 = _make_response(
            {
                "results": [{"id": 2}],
                "next": None,
            }
        )
        mock_cm, mock_http = _make_mock_client_cm([page1, page2])
        mock_client_cls.return_value = mock_cm

        client = PretalxClient("evt")
        results = client._get_paginated("https://pretalx.com/api/events/evt/speakers/")

        assert results == [{"id": 1}, {"id": 2}]
        assert mock_http.get.call_count == 2

    @pytest.mark.unit
    @patch("pretalx_client.generated.http_client.httpx.Client")
    def test_empty_results(self, mock_client_cls):
        page = _make_response({"results": [], "next": None})
        mock_cm, _ = _make_mock_client_cm([page])
        mock_client_cls.return_value = mock_cm

        client = PretalxClient("evt")
        results = client._get_paginated("https://pretalx.com/api/events/evt/speakers/")

        assert results == []

    @pytest.mark.unit
    @patch("pretalx_client.generated.http_client.httpx.Client")
    def test_http_error_raises_runtime_error(self, mock_client_cls):
        error_response = _make_response({}, status_code=500, url="https://pretalx.com/api/events/evt/speakers/")
        mock_cm, _ = _make_mock_client_cm([error_response])
        mock_client_cls.return_value = mock_cm

        client = PretalxClient("evt")
        with pytest.raises(RuntimeError, match="Pretalx API request failed"):
            client._get_paginated("https://pretalx.com/api/events/evt/speakers/")

    @pytest.mark.unit
    @patch("pretalx_client.generated.http_client.httpx.Client")
    def test_connection_error_raises_runtime_error(self, mock_client_cls):
        mock_http_client = MagicMock()
        mock_http_client.get.side_effect = httpx.RequestError("Connection refused", request=Mock())
        mock_cm = MagicMock()
        mock_cm.__enter__ = Mock(return_value=mock_http_client)
        mock_cm.__exit__ = Mock(return_value=False)
        mock_client_cls.return_value = mock_cm

        client = PretalxClient("evt")
        with pytest.raises(RuntimeError, match="Pretalx API connection error"):
            client._get_paginated("https://pretalx.com/api/events/evt/speakers/")

    @pytest.mark.unit
    @patch("pretalx_client.generated.http_client.httpx.Client")
    def test_passes_headers(self, mock_client_cls):
        """Verify that httpx.Client is constructed with the client's headers."""
        page = _make_response({"results": [], "next": None})
        mock_cm, _ = _make_mock_client_cm([page])
        mock_client_cls.return_value = mock_cm

        client = PretalxClient("evt", api_token="tok123")
        client._get_paginated("https://pretalx.com/api/events/evt/speakers/")

        mock_client_cls.assert_called_once_with(timeout=30, headers=client._http.headers)


# ---------------------------------------------------------------------------
# PretalxClient._get_paginated_or_none()
# ---------------------------------------------------------------------------


class TestGetPaginatedOrNone:
    """Tests for the _get_paginated_or_none() method."""

    @pytest.mark.unit
    @patch("pretalx_client.generated.http_client.httpx.Client")
    def test_returns_none_on_404(self, mock_client_cls):
        error_response = _make_response({}, status_code=404, url="https://pretalx.com/api/events/evt/talks/")
        mock_cm, _ = _make_mock_client_cm([error_response])
        mock_client_cls.return_value = mock_cm

        client = PretalxClient("evt")
        result = client._get_paginated_or_none("https://pretalx.com/api/events/evt/talks/")

        assert result is None

    @pytest.mark.unit
    @patch("pretalx_client.generated.http_client.httpx.Client")
    def test_raises_on_non_404_error(self, mock_client_cls):
        error_response = _make_response({}, status_code=500, url="https://pretalx.com/api/events/evt/talks/")
        mock_cm, _ = _make_mock_client_cm([error_response])
        mock_client_cls.return_value = mock_cm

        client = PretalxClient("evt")
        with pytest.raises(RuntimeError, match="Pretalx API request failed"):
            client._get_paginated_or_none("https://pretalx.com/api/events/evt/talks/")

    @pytest.mark.unit
    @patch("pretalx_client.generated.http_client.httpx.Client")
    def test_returns_results_on_success(self, mock_client_cls):
        page = _make_response({"results": [{"id": 1}], "next": None})
        mock_cm, _ = _make_mock_client_cm([page])
        mock_client_cls.return_value = mock_cm

        client = PretalxClient("evt")
        result = client._get_paginated_or_none("https://pretalx.com/api/events/evt/talks/")

        assert result == [{"id": 1}]


# ---------------------------------------------------------------------------
# PretalxClient.fetch_speakers()
# ---------------------------------------------------------------------------


class TestFetchSpeakers:
    """Tests for fetch_speakers()."""

    @pytest.mark.unit
    def test_returns_speaker_dataclasses(self):
        raw_data = [
            {"code": "SPK1", "name": "Alice", "biography": "Dev", "submissions": ["T1"]},
            {"code": "SPK2", "name": "Bob"},
        ]

        client = PretalxClient("evt")
        with patch.object(client._http, "speakers_list", return_value=raw_data) as mock_get:
            speakers = client.fetch_speakers()

        mock_get.assert_called_once_with(event="evt")
        assert len(speakers) == 2
        assert all(isinstance(s, PretalxSpeaker) for s in speakers)
        assert speakers[0].code == "SPK1"
        assert speakers[0].name == "Alice"
        assert speakers[1].code == "SPK2"

    @pytest.mark.unit
    def test_empty_results(self):
        client = PretalxClient("evt")
        with patch.object(client._http, "speakers_list", return_value=[]):
            speakers = client.fetch_speakers()

        assert speakers == []


# ---------------------------------------------------------------------------
# PretalxClient.fetch_talks()
# ---------------------------------------------------------------------------


class TestFetchTalks:
    """Tests for fetch_talks()."""

    @pytest.mark.unit
    def test_talks_endpoint_success(self):
        """When /talks/ returns data, use it directly."""
        raw_data = [
            {"code": "T1", "title": "Talk One", "speakers": []},
        ]
        client = PretalxClient("evt")
        with patch.object(client, "_get_paginated_or_none", return_value=raw_data) as mock_get_or_none:
            with patch.object(client, "_get_paginated") as mock_get:
                talks = client.fetch_talks()

        mock_get_or_none.assert_called_once_with("https://pretalx.com/api/events/evt/talks/")
        mock_get.assert_not_called()
        assert len(talks) == 1
        assert isinstance(talks[0], PretalxTalk)
        assert talks[0].code == "T1"

    @pytest.mark.unit
    def test_talks_404_falls_back_to_submissions(self):
        """When /talks/ returns 404 (None), fetches confirmed + accepted submissions."""
        confirmed = [{"code": "C1", "title": "Confirmed Talk", "speakers": []}]
        accepted = [{"code": "A1", "title": "Accepted Talk", "speakers": []}]

        client = PretalxClient("evt")
        with patch.object(client, "_get_paginated_or_none", return_value=None):
            with patch.object(client, "_get_paginated", side_effect=[confirmed, accepted]) as mock_get:
                talks = client.fetch_talks()

        assert mock_get.call_count == 2
        calls = [c.args[0] for c in mock_get.call_args_list]
        assert "submissions/?state=confirmed" in calls[0]
        assert "submissions/?state=accepted" in calls[1]

        assert len(talks) == 2
        assert talks[0].code == "C1"
        assert talks[1].code == "A1"

    @pytest.mark.unit
    def test_mappings_passed_through(self):
        """Verify that submission_types, tracks, and rooms mappings reach from_api."""
        raw_data = [
            {
                "code": "T1",
                "title": "Mapped",
                "submission_type": 7,
                "track": 3,
                "slot": {"room": 12, "start": "", "end": ""},
                "speakers": [],
            }
        ]
        sub_types = {7: "Tutorial"}
        tracks = {3: "Data"}
        rooms = {12: "Hall A"}

        client = PretalxClient("evt")
        with patch.object(client, "_get_paginated_or_none", return_value=raw_data):
            talks = client.fetch_talks(submission_types=sub_types, tracks=tracks, rooms=rooms)

        assert talks[0].submission_type == "Tutorial"
        assert talks[0].track == "Data"
        assert talks[0].room == "Hall A"

    @pytest.mark.unit
    def test_mappings_passed_through_in_fallback(self):
        """Mappings should also be used when falling back to submissions."""
        confirmed = [
            {
                "code": "C1",
                "title": "Confirmed",
                "submission_type": 7,
                "track": 3,
                "slot": {"room": 12, "start": "", "end": ""},
                "speakers": [],
            }
        ]
        sub_types = {7: "Tutorial"}
        tracks = {3: "Data"}
        rooms = {12: "Hall A"}

        client = PretalxClient("evt")
        with patch.object(client, "_get_paginated_or_none", return_value=None):
            with patch.object(client, "_get_paginated", side_effect=[confirmed, []]):
                talks = client.fetch_talks(submission_types=sub_types, tracks=tracks, rooms=rooms)

        assert talks[0].submission_type == "Tutorial"
        assert talks[0].track == "Data"
        assert talks[0].room == "Hall A"


# ---------------------------------------------------------------------------
# PretalxClient.fetch_schedule()
# ---------------------------------------------------------------------------


class TestFetchSchedule:
    """Tests for fetch_schedule()."""

    @pytest.mark.unit
    def test_returns_slot_dataclasses(self):
        raw_data = [
            {
                "room": {"en": "Main Hall"},
                "start": "2026-07-15T09:00:00+00:00",
                "end": "2026-07-15T10:00:00+00:00",
                "submission": "TALK1",
            },
        ]
        client = PretalxClient("evt")
        with patch.object(client._http, "slots_list", return_value=raw_data) as mock_get:
            slots = client.fetch_schedule()

        mock_get.assert_called_once_with(event="evt")
        assert len(slots) == 1
        assert isinstance(slots[0], PretalxSlot)
        assert slots[0].code == "TALK1"
        assert slots[0].room == "Main Hall"

    @pytest.mark.unit
    def test_rooms_mapping_forwarded(self):
        raw_data = [
            {"room": 42, "start": "", "end": "", "submission": "T1"},
        ]
        rooms = {42: "Ballroom"}

        client = PretalxClient("evt")
        with patch.object(client._http, "slots_list", return_value=raw_data):
            slots = client.fetch_schedule(rooms=rooms)

        assert slots[0].room == "Ballroom"

    @pytest.mark.unit
    def test_url_construction(self):
        client = PretalxClient("pycon-us-2026", base_url="https://pretalx.pycon.org")
        with patch.object(client._http, "slots_list", return_value=[]) as mock_get:
            client.fetch_schedule()

        mock_get.assert_called_once_with(event="pycon-us-2026")

    @pytest.mark.unit
    def test_empty_schedule(self):
        client = PretalxClient("evt")
        with patch.object(client._http, "slots_list", return_value=[]):
            slots = client.fetch_schedule()
        assert slots == []


# ---------------------------------------------------------------------------
# PretalxClient.fetch_rooms() / fetch_submission_types() / fetch_tracks()
# ---------------------------------------------------------------------------


class TestFetchMappings:
    """Tests for the ID-to-name mapping fetch methods."""

    @pytest.mark.unit
    @patch("pretalx_client.generated.http_client.httpx.Client")
    def test_fetch_rooms(self, mock_client_cls):
        raw = [
            {"id": 1, "name": {"en": "Hall A"}},
            {"id": 2, "name": {"en": "Hall B"}},
        ]
        page = _make_response({"results": raw, "next": None})
        mock_cm, _ = _make_mock_client_cm([page])
        mock_client_cls.return_value = mock_cm

        client = PretalxClient("evt")
        result = client.fetch_rooms()

        assert result == {1: "Hall A", 2: "Hall B"}

    @pytest.mark.unit
    @patch("pretalx_client.generated.http_client.httpx.Client")
    def test_fetch_submission_types(self, mock_client_cls):
        raw = [{"id": 7, "name": {"en": "Tutorial"}}]
        page = _make_response({"results": raw, "next": None})
        mock_cm, _ = _make_mock_client_cm([page])
        mock_client_cls.return_value = mock_cm

        client = PretalxClient("evt")
        result = client.fetch_submission_types()
        assert result == {7: "Tutorial"}

    @pytest.mark.unit
    @patch("pretalx_client.generated.http_client.httpx.Client")
    def test_fetch_tracks(self, mock_client_cls):
        raw = [{"id": 3, "name": "Data Science"}]
        page = _make_response({"results": raw, "next": None})
        mock_cm, _ = _make_mock_client_cm([page])
        mock_client_cls.return_value = mock_cm

        client = PretalxClient("evt")
        result = client.fetch_tracks()
        assert result == {3: "Data Science"}

    @pytest.mark.unit
    @patch("pretalx_client.generated.http_client.httpx.Client")
    def test_fetch_mapping_skips_items_without_id(self, mock_client_cls):
        raw = [
            {"id": 1, "name": {"en": "Valid"}},
            {"name": {"en": "No ID"}},
        ]
        page = _make_response({"results": raw, "next": None})
        mock_cm, _ = _make_mock_client_cm([page])
        mock_client_cls.return_value = mock_cm

        client = PretalxClient("evt")
        result = client.fetch_rooms()
        assert result == {1: "Valid"}

    @pytest.mark.unit
    def test_fetch_rooms_full(self):
        raw = [
            {"id": 1, "name": {"en": "Hall A"}, "capacity": 200, "position": 0},
        ]
        client = PretalxClient("evt")
        with patch.object(client._http, "rooms_list", return_value=raw) as mock_get:
            result = client.fetch_rooms_full()

        mock_get.assert_called_once_with(event="evt")
        assert result == raw


# ---------------------------------------------------------------------------
# PretalxClient.fetch_submissions()
# ---------------------------------------------------------------------------


class TestFetchSubmissions:
    """Tests for fetch_submissions()."""

    @pytest.mark.unit
    @patch("pretalx_client.generated.http_client.httpx.Client")
    def test_no_state_filter(self, mock_client_cls):
        raw = [{"code": "S1", "title": "Sub One", "speakers": []}]
        page = _make_response({"results": raw, "next": None})
        mock_cm, _ = _make_mock_client_cm([page])
        mock_client_cls.return_value = mock_cm

        client = PretalxClient("evt")
        results = client.fetch_submissions()

        assert len(results) == 1
        assert isinstance(results[0], PretalxTalk)

    @pytest.mark.unit
    @patch("pretalx_client.generated.http_client.httpx.Client")
    def test_with_state_filter(self, mock_client_cls):
        raw = [{"code": "S1", "title": "Sub One", "speakers": []}]
        page = _make_response({"results": raw, "next": None})
        mock_cm, mock_http = _make_mock_client_cm([page])
        mock_client_cls.return_value = mock_cm

        client = PretalxClient("evt")
        client.fetch_submissions(state="confirmed")

        # The URL should contain the state query param
        call_url = mock_http.get.call_args[0][0]
        assert "submissions/" in call_url
        assert "state=confirmed" in call_url

    @pytest.mark.unit
    @patch("pretalx_client.generated.http_client.httpx.Client")
    def test_mappings_passed_through(self, mock_client_cls):
        raw = [
            {
                "code": "S1",
                "title": "Sub",
                "submission_type": 7,
                "track": 3,
                "slot": {"room": 12, "start": "", "end": ""},
                "speakers": [],
            }
        ]
        sub_types = {7: "Tutorial"}
        tracks = {3: "Data"}
        rooms = {12: "Hall A"}

        page = _make_response({"results": raw, "next": None})
        mock_cm, _ = _make_mock_client_cm([page])
        mock_client_cls.return_value = mock_cm

        client = PretalxClient("evt")
        results = client.fetch_submissions(submission_types=sub_types, tracks=tracks, rooms=rooms)

        assert results[0].submission_type == "Tutorial"
        assert results[0].track == "Data"
        assert results[0].room == "Hall A"
