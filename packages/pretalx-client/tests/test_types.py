"""Tests for pretalx_client.models -- helper functions and dataclasses."""

import enum
from datetime import datetime

import pytest

from pretalx_client.models import (
    PretalxSlot,
    PretalxSpeaker,
    PretalxTalk,
    SubmissionState,
    _localized,
    _parse_datetime,
    _resolve_id_or_localized,
)

# ---------------------------------------------------------------------------
# _localized()
# ---------------------------------------------------------------------------


class TestLocalized:
    """Tests for the _localized() helper."""

    @pytest.mark.unit
    def test_none_returns_empty(self):
        assert _localized(None) == ""

    @pytest.mark.unit
    def test_plain_string_returned_as_is(self):
        assert _localized("Tutorial") == "Tutorial"

    @pytest.mark.unit
    def test_empty_string_returned_as_is(self):
        assert _localized("") == ""

    @pytest.mark.unit
    def test_dict_with_en_key(self):
        assert _localized({"en": "Talk", "de": "Vortrag"}) == "Talk"

    @pytest.mark.unit
    def test_dict_with_name_sub_key(self):
        """When value has a 'name' key whose value is itself a multilingual dict."""
        assert _localized({"name": {"en": "Workshop"}}) == "Workshop"

    @pytest.mark.unit
    def test_dict_with_name_sub_key_no_en(self):
        """name sub-key present but no 'en'; should fall through to first string."""
        assert _localized({"name": {"de": "Werkstatt"}}) == "Werkstatt"

    @pytest.mark.unit
    def test_dict_with_only_non_en_values(self):
        """No 'en' key -- should return the first string value found."""
        result = _localized({"de": "Vortrag", "fr": "Conférence"})
        assert result in ("Vortrag", "Conférence")

    @pytest.mark.unit
    def test_dict_with_en_key_non_string_value(self):
        """'en' key present but non-string value -- str() is applied."""
        assert _localized({"en": 42, "de": 99}) == "42"

    @pytest.mark.unit
    def test_dict_with_no_string_values_no_en(self):
        """No 'en' key and all non-string values returns empty string."""
        assert _localized({"de": 99, "fr": 100}) == ""

    @pytest.mark.unit
    def test_non_dict_non_string_value(self):
        """An unexpected type (e.g. int) should be str()-ified."""
        assert _localized(42) == "42"

    @pytest.mark.unit
    def test_non_dict_non_string_list(self):
        assert _localized([1, 2]) == "[1, 2]"


# ---------------------------------------------------------------------------
# _resolve_id_or_localized()
# ---------------------------------------------------------------------------


class TestResolveIdOrLocalized:
    """Tests for the _resolve_id_or_localized() helper."""

    @pytest.mark.unit
    def test_none_returns_empty(self):
        assert _resolve_id_or_localized(None) == ""

    @pytest.mark.unit
    def test_none_with_mapping_returns_empty(self):
        assert _resolve_id_or_localized(None, {1: "Room A"}) == ""

    @pytest.mark.unit
    def test_integer_with_mapping_hit(self):
        mapping = {7: "Tutorial", 12: "Talk"}
        assert _resolve_id_or_localized(7, mapping) == "Tutorial"

    @pytest.mark.unit
    def test_integer_with_mapping_miss(self):
        mapping = {7: "Tutorial"}
        assert _resolve_id_or_localized(99, mapping) == "99"

    @pytest.mark.unit
    def test_integer_without_mapping(self):
        assert _resolve_id_or_localized(42) == "42"

    @pytest.mark.unit
    def test_integer_with_none_mapping(self):
        assert _resolve_id_or_localized(42, None) == "42"

    @pytest.mark.unit
    def test_integer_with_empty_mapping(self):
        assert _resolve_id_or_localized(42, {}) == "42"

    @pytest.mark.unit
    def test_string_delegates_to_localized(self):
        assert _resolve_id_or_localized("Talk") == "Talk"

    @pytest.mark.unit
    def test_dict_delegates_to_localized(self):
        assert _resolve_id_or_localized({"en": "Workshop"}) == "Workshop"

    @pytest.mark.unit
    def test_dict_with_name_sub_key(self):
        assert _resolve_id_or_localized({"name": {"en": "Poster"}}) == "Poster"


# ---------------------------------------------------------------------------
# _parse_datetime()
# ---------------------------------------------------------------------------


class TestParseDatetime:
    """Tests for the _parse_datetime() helper."""

    @pytest.mark.unit
    def test_empty_string_returns_none(self):
        assert _parse_datetime("") is None

    @pytest.mark.unit
    def test_valid_iso_datetime(self):
        result = _parse_datetime("2026-07-15T10:30:00+00:00")
        assert isinstance(result, datetime)
        assert result.year == 2026
        assert result.month == 7
        assert result.day == 15
        assert result.hour == 10
        assert result.minute == 30

    @pytest.mark.unit
    def test_valid_naive_datetime(self):
        result = _parse_datetime("2026-07-15T10:30:00")
        assert isinstance(result, datetime)
        assert result.year == 2026

    @pytest.mark.unit
    def test_invalid_string_returns_none(self):
        assert _parse_datetime("not-a-date") is None

    @pytest.mark.unit
    def test_partial_date_string(self):
        """A date-only string is valid ISO and should parse."""
        result = _parse_datetime("2026-07-15")
        assert isinstance(result, datetime)
        assert result.year == 2026


# ---------------------------------------------------------------------------
# SubmissionState
# ---------------------------------------------------------------------------


class TestSubmissionState:
    """Tests for the SubmissionState StrEnum."""

    @pytest.mark.unit
    def test_is_str_enum(self):
        assert issubclass(SubmissionState, enum.StrEnum)

    @pytest.mark.unit
    def test_expected_members(self):
        expected = {"submitted", "accepted", "rejected", "confirmed", "withdrawn", "canceled", "deleted"}
        actual = {s.value for s in SubmissionState}
        assert actual == expected

    @pytest.mark.unit
    def test_member_names(self):
        assert SubmissionState.SUBMITTED == "submitted"
        assert SubmissionState.ACCEPTED == "accepted"
        assert SubmissionState.REJECTED == "rejected"
        assert SubmissionState.CONFIRMED == "confirmed"
        assert SubmissionState.WITHDRAWN == "withdrawn"
        assert SubmissionState.CANCELED == "canceled"
        assert SubmissionState.DELETED == "deleted"

    @pytest.mark.unit
    def test_string_comparison(self):
        """StrEnum members should compare equal to their string values."""
        assert SubmissionState.CONFIRMED == "confirmed"
        assert "accepted" == SubmissionState.ACCEPTED


# ---------------------------------------------------------------------------
# PretalxSpeaker.from_api()
# ---------------------------------------------------------------------------


class TestPretalxSpeakerFromApi:
    """Tests for PretalxSpeaker.from_api()."""

    @pytest.mark.unit
    def test_complete_data(self):
        data = {
            "code": "ABCDE",
            "name": "Guido van Rossum",
            "biography": "Creator of Python.",
            "avatar_url": "https://example.com/avatar.jpg",
            "email": "guido@python.org",
            "submissions": ["TALK1", "TALK2"],
        }
        speaker = PretalxSpeaker.from_api(data)

        assert speaker.code == "ABCDE"
        assert speaker.name == "Guido van Rossum"
        assert speaker.biography == "Creator of Python."
        assert speaker.avatar_url == "https://example.com/avatar.jpg"
        assert speaker.email == "guido@python.org"
        assert speaker.submissions == ["TALK1", "TALK2"]

    @pytest.mark.unit
    def test_minimal_data(self):
        """Only code and name provided; everything else defaults."""
        data = {"code": "XYZ", "name": "Nobody"}
        speaker = PretalxSpeaker.from_api(data)

        assert speaker.code == "XYZ"
        assert speaker.name == "Nobody"
        assert speaker.biography == ""
        assert speaker.avatar_url == ""
        assert speaker.email == ""
        assert speaker.submissions == []

    @pytest.mark.unit
    def test_empty_dict(self):
        speaker = PretalxSpeaker.from_api({})
        assert speaker.code == ""
        assert speaker.name == ""
        assert speaker.biography == ""
        assert speaker.avatar_url == ""

    @pytest.mark.unit
    def test_avatar_fallback_to_avatar_key(self):
        """When 'avatar_url' is absent, 'avatar' key should be used."""
        data = {
            "code": "SPK",
            "name": "Speaker",
            "avatar": "https://example.com/fallback.jpg",
        }
        speaker = PretalxSpeaker.from_api(data)
        assert speaker.avatar_url == "https://example.com/fallback.jpg"

    @pytest.mark.unit
    def test_avatar_url_preferred_over_avatar(self):
        """'avatar_url' takes precedence over 'avatar'."""
        data = {
            "code": "SPK",
            "name": "Speaker",
            "avatar_url": "https://example.com/primary.jpg",
            "avatar": "https://example.com/fallback.jpg",
        }
        speaker = PretalxSpeaker.from_api(data)
        assert speaker.avatar_url == "https://example.com/primary.jpg"

    @pytest.mark.unit
    def test_none_biography_becomes_empty(self):
        data = {"code": "SPK", "name": "Speaker", "biography": None}
        speaker = PretalxSpeaker.from_api(data)
        assert speaker.biography == ""

    @pytest.mark.unit
    def test_none_email_becomes_empty(self):
        data = {"code": "SPK", "name": "Speaker", "email": None}
        speaker = PretalxSpeaker.from_api(data)
        assert speaker.email == ""

    @pytest.mark.unit
    def test_none_submissions_becomes_empty_list(self):
        data = {"code": "SPK", "name": "Speaker", "submissions": None}
        speaker = PretalxSpeaker.from_api(data)
        assert speaker.submissions == []

    @pytest.mark.unit
    def test_frozen_dataclass(self):
        speaker = PretalxSpeaker.from_api({"code": "A", "name": "B"})
        with pytest.raises(AttributeError):
            speaker.name = "Changed"


# ---------------------------------------------------------------------------
# PretalxTalk.from_api()
# ---------------------------------------------------------------------------


class TestPretalxTalkFromApi:
    """Tests for PretalxTalk.from_api()."""

    @pytest.mark.unit
    def test_complete_data_with_slot(self):
        data = {
            "code": "TALK1",
            "title": "Async All the Things",
            "abstract": "An intro to async.",
            "description": "Detailed description here.",
            "submission_type": {"en": "Talk"},
            "track": {"en": "Core Python"},
            "duration": 30,
            "state": "confirmed",
            "speakers": [{"code": "SPK1"}, {"code": "SPK2"}],
            "slot": {
                "room": {"en": "Main Hall"},
                "start": "2026-07-15T10:00:00+00:00",
                "end": "2026-07-15T10:30:00+00:00",
            },
        }
        talk = PretalxTalk.from_api(data)

        assert talk.code == "TALK1"
        assert talk.title == "Async All the Things"
        assert talk.abstract == "An intro to async."
        assert talk.description == "Detailed description here."
        assert talk.submission_type == "Talk"
        assert talk.track == "Core Python"
        assert talk.duration == 30
        assert talk.state == "confirmed"
        assert talk.speaker_codes == ["SPK1", "SPK2"]
        assert talk.room == "Main Hall"
        assert talk.slot_start == "2026-07-15T10:00:00+00:00"
        assert talk.slot_end == "2026-07-15T10:30:00+00:00"

    @pytest.mark.unit
    def test_missing_slot(self):
        data = {
            "code": "TALK2",
            "title": "No Slot Yet",
            "speakers": [],
        }
        talk = PretalxTalk.from_api(data)

        assert talk.room == ""
        assert talk.slot_start == ""
        assert talk.slot_end == ""

    @pytest.mark.unit
    def test_null_slot(self):
        """Slot key explicitly set to None."""
        data = {
            "code": "TALK3",
            "title": "Null Slot",
            "slot": None,
        }
        talk = PretalxTalk.from_api(data)
        assert talk.room == ""
        assert talk.slot_start == ""
        assert talk.slot_end == ""

    @pytest.mark.unit
    def test_integer_ids_with_mappings(self):
        """Real Pretalx API sends integer IDs for submission_type, track, room."""
        data = {
            "code": "TALK4",
            "title": "Mapped IDs",
            "submission_type": 7,
            "track": 3,
            "slot": {"room": 12, "start": "2026-07-15T10:00:00", "end": "2026-07-15T10:30:00"},
            "speakers": [],
        }
        sub_types = {7: "Tutorial", 8: "Talk"}
        tracks = {3: "Data Science", 5: "Web"}
        rooms = {12: "Room 200", 14: "Room 300"}

        talk = PretalxTalk.from_api(data, submission_types=sub_types, tracks=tracks, rooms=rooms)

        assert talk.submission_type == "Tutorial"
        assert talk.track == "Data Science"
        assert talk.room == "Room 200"

    @pytest.mark.unit
    def test_integer_ids_without_mappings(self):
        """Integer IDs with no mapping fall back to str(value)."""
        data = {
            "code": "TALK5",
            "title": "Unmapped",
            "submission_type": 99,
            "track": 42,
            "slot": {"room": 77, "start": "", "end": ""},
            "speakers": [],
        }
        talk = PretalxTalk.from_api(data)

        assert talk.submission_type == "99"
        assert talk.track == "42"
        assert talk.room == "77"

    @pytest.mark.unit
    def test_speakers_as_dicts(self):
        data = {
            "code": "T",
            "title": "T",
            "speakers": [{"code": "A"}, {"code": "B"}],
        }
        talk = PretalxTalk.from_api(data)
        assert talk.speaker_codes == ["A", "B"]

    @pytest.mark.unit
    def test_speakers_as_strings(self):
        data = {
            "code": "T",
            "title": "T",
            "speakers": ["SPK1", "SPK2"],
        }
        talk = PretalxTalk.from_api(data)
        assert talk.speaker_codes == ["SPK1", "SPK2"]

    @pytest.mark.unit
    def test_speakers_as_integers(self):
        """Some API shapes return integer speaker IDs."""
        data = {
            "code": "T",
            "title": "T",
            "speakers": [101, 202],
        }
        talk = PretalxTalk.from_api(data)
        assert talk.speaker_codes == ["101", "202"]

    @pytest.mark.unit
    def test_none_speakers(self):
        data = {"code": "T", "title": "T", "speakers": None}
        talk = PretalxTalk.from_api(data)
        assert talk.speaker_codes == []

    @pytest.mark.unit
    def test_none_abstract_and_description(self):
        data = {"code": "T", "title": "T", "abstract": None, "description": None}
        talk = PretalxTalk.from_api(data)
        assert talk.abstract == ""
        assert talk.description == ""

    @pytest.mark.unit
    def test_none_state(self):
        data = {"code": "T", "title": "T", "state": None}
        talk = PretalxTalk.from_api(data)
        assert talk.state == ""

    @pytest.mark.unit
    def test_none_submission_type_and_track(self):
        data = {"code": "T", "title": "T", "submission_type": None, "track": None}
        talk = PretalxTalk.from_api(data)
        assert talk.submission_type == ""
        assert talk.track == ""

    @pytest.mark.unit
    def test_empty_dict(self):
        talk = PretalxTalk.from_api({})
        assert talk.code == ""
        assert talk.title == ""
        assert talk.duration is None

    @pytest.mark.unit
    def test_frozen_dataclass(self):
        talk = PretalxTalk.from_api({"code": "X", "title": "Y"})
        with pytest.raises(AttributeError):
            talk.title = "Changed"


# ---------------------------------------------------------------------------
# PretalxSlot.from_api()
# ---------------------------------------------------------------------------


class TestPretalxSlotFromApi:
    """Tests for PretalxSlot.from_api()."""

    @pytest.mark.unit
    def test_complete_data(self):
        data = {
            "room": {"en": "Main Hall"},
            "start": "2026-07-15T09:00:00+00:00",
            "end": "2026-07-15T10:00:00+00:00",
            "code": "TALK1",
            "title": {"en": "Keynote"},
        }
        slot = PretalxSlot.from_api(data)

        assert slot.room == "Main Hall"
        assert slot.start == "2026-07-15T09:00:00+00:00"
        assert slot.end == "2026-07-15T10:00:00+00:00"
        assert slot.code == "TALK1"
        assert slot.title == "Keynote"
        assert isinstance(slot.start_dt, datetime)
        assert isinstance(slot.end_dt, datetime)

    @pytest.mark.unit
    def test_submission_key_fallback(self):
        """The real /slots/ API uses 'submission' instead of 'code'."""
        data = {
            "room": 5,
            "start": "2026-07-15T09:00:00",
            "end": "2026-07-15T10:00:00",
            "submission": "ABC123",
        }
        rooms = {5: "Room A"}
        slot = PretalxSlot.from_api(data, rooms=rooms)

        assert slot.code == "ABC123"
        assert slot.room == "Room A"

    @pytest.mark.unit
    def test_submission_preferred_over_code(self):
        """'submission' key should be checked before 'code'."""
        data = {
            "room": "Hall B",
            "start": "2026-07-15T09:00:00",
            "end": "2026-07-15T10:00:00",
            "submission": "SUB1",
            "code": "CODE1",
        }
        slot = PretalxSlot.from_api(data)
        assert slot.code == "SUB1"

    @pytest.mark.unit
    def test_room_id_resolution(self):
        data = {
            "room": 42,
            "start": "2026-07-15T09:00:00",
            "end": "2026-07-15T10:00:00",
        }
        rooms = {42: "Ballroom"}
        slot = PretalxSlot.from_api(data, rooms=rooms)
        assert slot.room == "Ballroom"

    @pytest.mark.unit
    def test_room_id_without_mapping(self):
        data = {
            "room": 42,
            "start": "2026-07-15T09:00:00",
            "end": "2026-07-15T10:00:00",
        }
        slot = PretalxSlot.from_api(data)
        assert slot.room == "42"

    @pytest.mark.unit
    def test_empty_datetimes(self):
        data = {"room": "Hall", "start": "", "end": ""}
        slot = PretalxSlot.from_api(data)

        assert slot.start == ""
        assert slot.end == ""
        assert slot.start_dt is None
        assert slot.end_dt is None

    @pytest.mark.unit
    def test_none_datetimes(self):
        data = {"room": "Hall", "start": None, "end": None}
        slot = PretalxSlot.from_api(data)

        assert slot.start == ""
        assert slot.end == ""
        assert slot.start_dt is None
        assert slot.end_dt is None

    @pytest.mark.unit
    def test_missing_code_and_submission(self):
        """Neither 'code' nor 'submission' present -- defaults to empty."""
        data = {"room": "Hall", "start": "", "end": ""}
        slot = PretalxSlot.from_api(data)
        assert slot.code == ""

    @pytest.mark.unit
    def test_title_absent_gives_empty(self):
        """When 'title' key is not present at all, title should be empty."""
        data = {"room": "Hall", "start": "", "end": ""}
        slot = PretalxSlot.from_api(data)
        assert slot.title == ""

    @pytest.mark.unit
    def test_title_none_gives_empty(self):
        """When 'title' key is present but None, _localized(None) returns empty."""
        data = {"room": "Hall", "start": "", "end": "", "title": None}
        slot = PretalxSlot.from_api(data)
        assert slot.title == ""

    @pytest.mark.unit
    def test_title_localized_dict(self):
        data = {"room": "Hall", "start": "", "end": "", "title": {"en": "Break", "de": "Pause"}}
        slot = PretalxSlot.from_api(data)
        assert slot.title == "Break"

    @pytest.mark.unit
    def test_frozen_dataclass(self):
        slot = PretalxSlot.from_api({"room": "Hall", "start": "", "end": ""})
        with pytest.raises(AttributeError):
            slot.room = "Changed"

    @pytest.mark.unit
    def test_none_room(self):
        data = {"room": None, "start": "", "end": ""}
        slot = PretalxSlot.from_api(data)
        assert slot.room == ""
