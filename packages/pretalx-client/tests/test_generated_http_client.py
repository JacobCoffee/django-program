"""Tests for the auto-generated HTTP client (GeneratedPretalxClient).

Verifies initialization, core HTTP methods (_request, _paginate,
_request_or_none, _paginate_or_none), and spot-checks a few generated
endpoint methods.
"""

from unittest.mock import MagicMock, Mock

import httpx
import pytest

from pretalx_client.generated.http_client import GeneratedPretalxClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(json_data, status_code=200, url="https://pretalx.com/api/"):
    """Build a mock httpx.Response."""
    response = Mock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_data
    response.raise_for_status = Mock()

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
    """Build a context-manager mock for httpx.Client."""
    mock_http = MagicMock()
    mock_http.get = Mock(side_effect=list(responses))
    mock_http.request = Mock(side_effect=list(responses))
    mock_cm = MagicMock()
    mock_cm.__enter__ = Mock(return_value=mock_http)
    mock_cm.__exit__ = Mock(return_value=False)
    return mock_cm, mock_http


# ---------------------------------------------------------------------------
# GeneratedPretalxClient.__init__()
# ---------------------------------------------------------------------------


class TestGeneratedClientInit:
    """Tests for GeneratedPretalxClient initialization."""

    @pytest.mark.unit
    def test_defaults(self):
        client = GeneratedPretalxClient()
        assert client.base_url == "https://pretalx.com"
        assert client.api_token == ""
        assert client.timeout == 30
        assert client.headers == {"Accept": "application/json"}
        assert "Authorization" not in client.headers

    @pytest.mark.unit
    def test_with_token(self):
        client = GeneratedPretalxClient(api_token="secret")
        assert client.headers["Authorization"] == "Token secret"

    @pytest.mark.unit
    def test_url_normalization(self):
        client = GeneratedPretalxClient(base_url="https://pretalx.example.com/api/")
        assert client.base_url == "https://pretalx.example.com"

    @pytest.mark.unit
    def test_custom_timeout(self):
        client = GeneratedPretalxClient(timeout=60)
        assert client.timeout == 60


# ---------------------------------------------------------------------------
# _request()
# ---------------------------------------------------------------------------


class TestRequest:
    """Tests for the _request() core method."""

    @pytest.mark.unit
    def test_get_request(self, monkeypatch):
        resp = _make_response({"name": "test"})
        mock_cm, mock_http = _make_mock_client_cm([resp])
        monkeypatch.setattr("pretalx_client.generated.http_client.httpx.Client", lambda **kw: mock_cm)

        client = GeneratedPretalxClient()
        result = client._request("GET", "/api/events/test/")

        assert result == {"name": "test"}
        mock_http.request.assert_called_once_with("GET", "https://pretalx.com/api/events/test/", params=None, json=None)

    @pytest.mark.unit
    def test_request_with_params(self, monkeypatch):
        resp = _make_response({"results": []})
        mock_cm, mock_http = _make_mock_client_cm([resp])
        monkeypatch.setattr("pretalx_client.generated.http_client.httpx.Client", lambda **kw: mock_cm)

        client = GeneratedPretalxClient()
        client._request("GET", "/api/test/", params={"q": "search"})

        mock_http.request.assert_called_once_with(
            "GET", "https://pretalx.com/api/test/", params={"q": "search"}, json=None
        )

    @pytest.mark.unit
    def test_request_with_json_body(self, monkeypatch):
        resp = _make_response({"id": 1})
        mock_cm, mock_http = _make_mock_client_cm([resp])
        monkeypatch.setattr("pretalx_client.generated.http_client.httpx.Client", lambda **kw: mock_cm)

        client = GeneratedPretalxClient()
        client._request("POST", "/api/test/", json_body={"name": "new"})

        mock_http.request.assert_called_once_with(
            "POST", "https://pretalx.com/api/test/", params=None, json={"name": "new"}
        )

    @pytest.mark.unit
    def test_request_http_error(self, monkeypatch):
        resp = _make_response({}, status_code=500, url="https://pretalx.com/api/test/")
        mock_cm, _ = _make_mock_client_cm([resp])
        monkeypatch.setattr("pretalx_client.generated.http_client.httpx.Client", lambda **kw: mock_cm)

        client = GeneratedPretalxClient()
        with pytest.raises(RuntimeError, match="Pretalx API request failed"):
            client._request("GET", "/api/test/")

    @pytest.mark.unit
    def test_request_connection_error(self, monkeypatch):
        mock_http = MagicMock()
        mock_http.request.side_effect = httpx.RequestError("Connection refused", request=Mock())
        mock_cm = MagicMock()
        mock_cm.__enter__ = Mock(return_value=mock_http)
        mock_cm.__exit__ = Mock(return_value=False)
        monkeypatch.setattr("pretalx_client.generated.http_client.httpx.Client", lambda **kw: mock_cm)

        client = GeneratedPretalxClient()
        with pytest.raises(RuntimeError, match="Pretalx API connection error"):
            client._request("GET", "/api/test/")


# ---------------------------------------------------------------------------
# _request_or_none()
# ---------------------------------------------------------------------------


class TestRequestOrNone:
    """Tests for the _request_or_none() method."""

    @pytest.mark.unit
    def test_returns_none_on_404(self, monkeypatch):
        resp = _make_response({}, status_code=404)
        mock_cm, _ = _make_mock_client_cm([resp])
        monkeypatch.setattr("pretalx_client.generated.http_client.httpx.Client", lambda **kw: mock_cm)

        client = GeneratedPretalxClient()
        assert client._request_or_none("GET", "/api/missing/") is None

    @pytest.mark.unit
    def test_returns_data_on_success(self, monkeypatch):
        resp = _make_response({"id": 1})
        mock_cm, _ = _make_mock_client_cm([resp])
        monkeypatch.setattr("pretalx_client.generated.http_client.httpx.Client", lambda **kw: mock_cm)

        client = GeneratedPretalxClient()
        assert client._request_or_none("GET", "/api/test/") == {"id": 1}

    @pytest.mark.unit
    def test_raises_on_non_404(self, monkeypatch):
        resp = _make_response({}, status_code=500, url="https://pretalx.com/api/test/")
        mock_cm, _ = _make_mock_client_cm([resp])
        monkeypatch.setattr("pretalx_client.generated.http_client.httpx.Client", lambda **kw: mock_cm)

        client = GeneratedPretalxClient()
        with pytest.raises(RuntimeError, match="Pretalx API request failed"):
            client._request_or_none("GET", "/api/test/")


# ---------------------------------------------------------------------------
# _paginate()
# ---------------------------------------------------------------------------


class TestPaginate:
    """Tests for the _paginate() pagination method."""

    @pytest.mark.unit
    def test_single_page(self, monkeypatch):
        resp = _make_response({"results": [{"id": 1}, {"id": 2}], "next": None})
        mock_cm, _ = _make_mock_client_cm([resp])
        monkeypatch.setattr("pretalx_client.generated.http_client.httpx.Client", lambda **kw: mock_cm)

        client = GeneratedPretalxClient()
        assert client._paginate("/api/events/evt/speakers/") == [{"id": 1}, {"id": 2}]

    @pytest.mark.unit
    def test_multiple_pages(self, monkeypatch):
        page1 = _make_response({"results": [{"id": 1}], "next": "https://pretalx.com/api/events/evt/speakers/?page=2"})
        page2 = _make_response({"results": [{"id": 2}], "next": None})
        mock_cm, _ = _make_mock_client_cm([page1, page2])
        monkeypatch.setattr("pretalx_client.generated.http_client.httpx.Client", lambda **kw: mock_cm)

        client = GeneratedPretalxClient()
        assert client._paginate("/api/events/evt/speakers/") == [{"id": 1}, {"id": 2}]

    @pytest.mark.unit
    def test_array_response(self, monkeypatch):
        """Some endpoints return a plain list instead of paginated results."""
        resp = _make_response([{"slug": "evt1"}, {"slug": "evt2"}])
        mock_cm, _ = _make_mock_client_cm([resp])
        monkeypatch.setattr("pretalx_client.generated.http_client.httpx.Client", lambda **kw: mock_cm)

        client = GeneratedPretalxClient()
        assert client._paginate("/api/events/") == [{"slug": "evt1"}, {"slug": "evt2"}]

    @pytest.mark.unit
    def test_http_error(self, monkeypatch):
        resp = _make_response({}, status_code=500, url="https://pretalx.com/api/test/")
        mock_cm, _ = _make_mock_client_cm([resp])
        monkeypatch.setattr("pretalx_client.generated.http_client.httpx.Client", lambda **kw: mock_cm)

        client = GeneratedPretalxClient()
        with pytest.raises(RuntimeError, match="Pretalx API request failed"):
            client._paginate("/api/test/")

    @pytest.mark.unit
    def test_params_only_sent_first_request(self, monkeypatch):
        """Query params should only be sent on the first page request."""
        page1 = _make_response({"results": [{"id": 1}], "next": "https://pretalx.com/api/test/?page=2"})
        page2 = _make_response({"results": [{"id": 2}], "next": None})
        mock_cm, mock_http = _make_mock_client_cm([page1, page2])
        monkeypatch.setattr("pretalx_client.generated.http_client.httpx.Client", lambda **kw: mock_cm)

        client = GeneratedPretalxClient()
        client._paginate("/api/test/", params={"q": "foo"})

        calls = mock_http.get.call_args_list
        assert calls[0][1].get("params") == {"q": "foo"}
        # Second call should not have params (they're embedded in the next URL)
        assert calls[1][1].get("params") is None


# ---------------------------------------------------------------------------
# _paginate_or_none()
# ---------------------------------------------------------------------------


class TestPaginateOrNone:
    """Tests for the _paginate_or_none() method."""

    @pytest.mark.unit
    def test_returns_none_on_404(self, monkeypatch):
        resp = _make_response({}, status_code=404, url="https://pretalx.com/api/test/")
        mock_cm, _ = _make_mock_client_cm([resp])
        monkeypatch.setattr("pretalx_client.generated.http_client.httpx.Client", lambda **kw: mock_cm)

        client = GeneratedPretalxClient()
        assert client._paginate_or_none("/api/test/") is None

    @pytest.mark.unit
    def test_returns_results_on_success(self, monkeypatch):
        resp = _make_response({"results": [{"id": 1}], "next": None})
        mock_cm, _ = _make_mock_client_cm([resp])
        monkeypatch.setattr("pretalx_client.generated.http_client.httpx.Client", lambda **kw: mock_cm)

        client = GeneratedPretalxClient()
        assert client._paginate_or_none("/api/test/") == [{"id": 1}]


# ---------------------------------------------------------------------------
# Spot-check generated methods
# ---------------------------------------------------------------------------


class TestGeneratedMethods:
    """Spot-check a few auto-generated endpoint methods."""

    @pytest.mark.unit
    def test_speakers_list_calls_paginate(self, monkeypatch):
        resp = _make_response({"results": [{"code": "SPK1"}], "next": None})
        mock_cm, _ = _make_mock_client_cm([resp])
        monkeypatch.setattr("pretalx_client.generated.http_client.httpx.Client", lambda **kw: mock_cm)

        client = GeneratedPretalxClient()
        result = client.speakers_list(event="pycon-2026")
        assert result == [{"code": "SPK1"}]

    @pytest.mark.unit
    def test_speakers_list_with_query_params(self, monkeypatch):
        resp = _make_response({"results": [], "next": None})
        mock_cm, mock_http = _make_mock_client_cm([resp])
        monkeypatch.setattr("pretalx_client.generated.http_client.httpx.Client", lambda **kw: mock_cm)

        client = GeneratedPretalxClient()
        client.speakers_list(event="evt", q="alice", auto_paginate=True)

        call_params = mock_http.get.call_args[1].get("params")
        assert call_params == {"q": "alice"}

    @pytest.mark.unit
    def test_submissions_list_with_state(self, monkeypatch):
        resp = _make_response({"results": [{"code": "S1"}], "next": None})
        mock_cm, mock_http = _make_mock_client_cm([resp])
        monkeypatch.setattr("pretalx_client.generated.http_client.httpx.Client", lambda **kw: mock_cm)

        client = GeneratedPretalxClient()
        result = client.submissions_list(event="evt", state=["confirmed", "accepted"])
        assert result == [{"code": "S1"}]

        call_params = mock_http.get.call_args[1].get("params")
        assert call_params["state"] == ["confirmed", "accepted"]

    @pytest.mark.unit
    def test_access_codes_destroy(self, monkeypatch):
        """Delete methods should return None."""
        resp = _make_response({}, status_code=204)
        # Override status for 204 - no raise
        resp.raise_for_status = Mock()
        mock_cm, mock_http = _make_mock_client_cm([resp])
        monkeypatch.setattr("pretalx_client.generated.http_client.httpx.Client", lambda **kw: mock_cm)

        client = GeneratedPretalxClient()
        result = client.access_codes_destroy(event="evt", id=42)
        assert result is None

        mock_http.request.assert_called_once()
        call_args = mock_http.request.call_args
        assert call_args[0][0] == "DELETE"
        assert "/api/events/evt/access-codes/42/" in call_args[0][1]

    @pytest.mark.unit
    def test_root_retrieve(self, monkeypatch):
        resp = _make_response({"name": {"en": "PyCon US"}, "slug": "pycon-us"})
        mock_cm, _mock_http = _make_mock_client_cm([resp])
        monkeypatch.setattr("pretalx_client.generated.http_client.httpx.Client", lambda **kw: mock_cm)

        client = GeneratedPretalxClient()
        result = client.root_retrieve(event="pycon-us")
        assert result["slug"] == "pycon-us"

    @pytest.mark.unit
    def test_auto_paginate_false(self, monkeypatch):
        """When auto_paginate=False, should return the raw response dict."""
        resp = _make_response({"count": 10, "results": [{"id": 1}], "next": "url"})
        mock_cm, _mock_http = _make_mock_client_cm([resp])
        monkeypatch.setattr("pretalx_client.generated.http_client.httpx.Client", lambda **kw: mock_cm)

        client = GeneratedPretalxClient()
        result = client.speakers_list(event="evt", auto_paginate=False)
        # Returns raw dict, not flattened list
        assert isinstance(result, dict)
        assert result["count"] == 10

    @pytest.mark.unit
    def test_method_count(self):
        """Verify the generated client has the expected number of public methods."""
        public_methods = [
            name
            for name in dir(GeneratedPretalxClient)
            if not name.startswith("_") and callable(getattr(GeneratedPretalxClient, name))
        ]
        assert len(public_methods) == 129
