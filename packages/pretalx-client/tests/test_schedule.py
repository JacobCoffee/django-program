"""Tests for pretalx_client.adapters.schedule -- parse_datetime() and normalize_slot()."""

from datetime import datetime

import pytest

from pretalx_client.adapters.schedule import normalize_slot, parse_datetime

# ---------------------------------------------------------------------------
# parse_datetime()
# ---------------------------------------------------------------------------


class TestParseDatetime:
    """Tests for the parse_datetime() function."""

    @pytest.mark.unit
    def test_valid_iso_datetime_with_offset(self):
        result = parse_datetime("2026-07-15T10:30:00+00:00")
        assert isinstance(result, datetime)
        assert result.year == 2026
        assert result.month == 7
        assert result.day == 15
        assert result.hour == 10
        assert result.minute == 30

    @pytest.mark.unit
    def test_valid_iso_datetime_naive(self):
        result = parse_datetime("2026-07-15T10:30:00")
        assert isinstance(result, datetime)
        assert result.year == 2026

    @pytest.mark.unit
    def test_valid_date_only_string(self):
        result = parse_datetime("2026-07-15")
        assert isinstance(result, datetime)
        assert result.year == 2026
        assert result.month == 7
        assert result.day == 15

    @pytest.mark.unit
    def test_empty_string_returns_none(self):
        assert parse_datetime("") is None

    @pytest.mark.unit
    def test_invalid_string_returns_none(self):
        assert parse_datetime("not-a-date") is None

    @pytest.mark.unit
    def test_garbage_string_returns_none(self):
        assert parse_datetime("xyz123!@#") is None

    @pytest.mark.unit
    def test_none_equivalent_empty_value(self):
        """An empty/falsy value triggers the early return."""
        assert parse_datetime("") is None


# ---------------------------------------------------------------------------
# normalize_slot() -- legacy format (string room, code, title keys)
# ---------------------------------------------------------------------------


class TestNormalizeSlotLegacy:
    """Tests for normalize_slot() with legacy format data."""

    @pytest.mark.unit
    def test_legacy_format_string_room_code_title(self):
        data = {
            "room": {"en": "Main Hall"},
            "start": "2026-07-15T09:00:00+00:00",
            "end": "2026-07-15T10:00:00+00:00",
            "code": "TALK1",
            "title": {"en": "Opening Keynote"},
        }
        result = normalize_slot(data)

        assert result["room"] == "Main Hall"
        assert result["start"] == "2026-07-15T09:00:00+00:00"
        assert result["end"] == "2026-07-15T10:00:00+00:00"
        assert result["code"] == "TALK1"
        assert result["title"] == "Opening Keynote"
        assert isinstance(result["start_dt"], datetime)
        assert isinstance(result["end_dt"], datetime)

    @pytest.mark.unit
    def test_legacy_format_plain_string_room(self):
        data = {
            "room": "Room 200",
            "start": "2026-07-15T09:00:00",
            "end": "2026-07-15T10:00:00",
            "code": "ABC",
            "title": "A Talk Title",
        }
        result = normalize_slot(data)
        assert result["room"] == "Room 200"
        assert result["title"] == "A Talk Title"


# ---------------------------------------------------------------------------
# normalize_slot() -- paginated /slots/ format
# ---------------------------------------------------------------------------


class TestNormalizeSlotPaginated:
    """Tests for normalize_slot() with the paginated /slots/ format."""

    @pytest.mark.unit
    def test_paginated_format_integer_room_submission_key(self):
        """The /slots/ endpoint returns integer room IDs and 'submission' instead of 'code'."""
        data = {
            "room": 42,
            "start": "2026-07-15T09:00:00+00:00",
            "end": "2026-07-15T10:00:00+00:00",
            "submission": "SUB123",
        }
        result = normalize_slot(data)

        assert result["code"] == "SUB123"
        assert result["room"] == "42"
        assert result["title"] == ""

    @pytest.mark.unit
    def test_paginated_format_no_title_key(self):
        """The /slots/ endpoint does not include a 'title' key."""
        data = {
            "room": 5,
            "start": "",
            "end": "",
            "submission": "XYZ",
        }
        result = normalize_slot(data)
        assert result["title"] == ""

    @pytest.mark.unit
    def test_submission_preferred_over_code(self):
        """When both 'submission' and 'code' are present, 'submission' wins."""
        data = {
            "room": "Hall",
            "start": "",
            "end": "",
            "submission": "SUB1",
            "code": "CODE1",
        }
        result = normalize_slot(data)
        assert result["code"] == "SUB1"


# ---------------------------------------------------------------------------
# normalize_slot() -- room ID resolution
# ---------------------------------------------------------------------------


class TestNormalizeSlotRoomResolution:
    """Tests for room ID resolution via the rooms mapping."""

    @pytest.mark.unit
    def test_room_id_resolved_with_mapping(self):
        data = {"room": 42, "start": "", "end": ""}
        rooms = {42: "Ballroom", 99: "Lobby"}
        result = normalize_slot(data, rooms=rooms)
        assert result["room"] == "Ballroom"

    @pytest.mark.unit
    def test_room_id_not_in_mapping(self):
        data = {"room": 77, "start": "", "end": ""}
        rooms = {42: "Ballroom"}
        result = normalize_slot(data, rooms=rooms)
        assert result["room"] == "77"

    @pytest.mark.unit
    def test_room_id_without_mapping(self):
        data = {"room": 42, "start": "", "end": ""}
        result = normalize_slot(data)
        assert result["room"] == "42"

    @pytest.mark.unit
    def test_room_id_with_none_mapping(self):
        data = {"room": 42, "start": "", "end": ""}
        result = normalize_slot(data, rooms=None)
        assert result["room"] == "42"


# ---------------------------------------------------------------------------
# normalize_slot() -- missing keys / empty defaults
# ---------------------------------------------------------------------------


class TestNormalizeSlotMissingKeys:
    """Tests for normalize_slot() with missing or empty data."""

    @pytest.mark.unit
    def test_missing_all_optional_keys(self):
        data = {"start": "", "end": ""}
        result = normalize_slot(data)

        assert result["room"] == ""
        assert result["code"] == ""
        assert result["title"] == ""
        assert result["start_dt"] is None
        assert result["end_dt"] is None

    @pytest.mark.unit
    def test_empty_dict(self):
        result = normalize_slot({})
        assert result["room"] == ""
        assert result["start"] == ""
        assert result["end"] == ""
        assert result["code"] == ""
        assert result["title"] == ""
        assert result["start_dt"] is None
        assert result["end_dt"] is None

    @pytest.mark.unit
    def test_none_start_and_end(self):
        data = {"room": "Hall", "start": None, "end": None}
        result = normalize_slot(data)
        assert result["start"] == ""
        assert result["end"] == ""
        assert result["start_dt"] is None
        assert result["end_dt"] is None

    @pytest.mark.unit
    def test_none_room(self):
        data = {"room": None, "start": "", "end": ""}
        result = normalize_slot(data)
        assert result["room"] == ""

    @pytest.mark.unit
    def test_title_present_but_none(self):
        """When the title key exists but is None, localized(None) returns empty."""
        data = {"room": "Hall", "start": "", "end": "", "title": None}
        result = normalize_slot(data)
        assert result["title"] == ""

    @pytest.mark.unit
    def test_result_keys_always_present(self):
        """The returned dict always contains all expected keys."""
        result = normalize_slot({})
        expected_keys = {"room", "start", "end", "code", "title", "start_dt", "end_dt"}
        assert set(result.keys()) == expected_keys
