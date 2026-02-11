"""Tests for pretalx_client.adapters.normalization -- localized field helpers."""

import pytest

from pretalx_client.adapters.normalization import localized, resolve_id_or_localized

# ---------------------------------------------------------------------------
# localized()
# ---------------------------------------------------------------------------


class TestLocalized:
    """Tests for the localized() normalization helper."""

    @pytest.mark.unit
    def test_none_returns_empty_string(self):
        assert localized(None) == ""

    @pytest.mark.unit
    def test_plain_string_returned_as_is(self):
        assert localized("Tutorial") == "Tutorial"

    @pytest.mark.unit
    def test_empty_string_returned_as_is(self):
        assert localized("") == ""

    @pytest.mark.unit
    def test_dict_with_en_key_returns_english_value(self):
        assert localized({"en": "Talk", "de": "Vortrag"}) == "Talk"

    @pytest.mark.unit
    def test_dict_without_en_falls_back_to_first_string_value(self):
        result = localized({"de": "Vortrag", "fr": "Conference"})
        assert result in ("Vortrag", "Conference")

    @pytest.mark.unit
    def test_dict_with_name_sub_key_recurses(self):
        assert localized({"name": {"en": "Workshop"}}) == "Workshop"

    @pytest.mark.unit
    def test_dict_with_name_sub_key_no_en(self):
        """name sub-key present but no 'en'; recursion should fall back to first string."""
        assert localized({"name": {"de": "Werkstatt"}}) == "Werkstatt"

    @pytest.mark.unit
    def test_nested_name_key_with_multilingual_dict(self):
        """name sub-key with multiple languages, 'en' should win."""
        assert localized({"name": {"en": "Poster", "de": "Plakat"}}) == "Poster"

    @pytest.mark.unit
    def test_empty_dict_returns_empty_string(self):
        assert localized({}) == ""

    @pytest.mark.unit
    def test_non_dict_non_str_value_returns_str(self):
        assert localized(42) == "42"

    @pytest.mark.unit
    def test_int_value_returns_str_of_int(self):
        assert localized(0) == "0"

    @pytest.mark.unit
    def test_float_value_returns_str(self):
        assert localized(3.14) == "3.14"

    @pytest.mark.unit
    def test_list_value_returns_str(self):
        assert localized([1, 2, 3]) == "[1, 2, 3]"

    @pytest.mark.unit
    def test_bool_value_returns_str(self):
        assert localized(True) == "True"

    @pytest.mark.unit
    def test_en_key_with_non_string_value_applies_str(self):
        """'en' key present but value is an int -- str() should be applied."""
        assert localized({"en": 99}) == "99"

    @pytest.mark.unit
    def test_dict_with_all_non_string_values_no_en(self):
        """No 'en' key and all values are non-string; fallback returns empty string."""
        assert localized({"de": 100, "fr": 200}) == ""

    @pytest.mark.unit
    def test_en_key_takes_priority_over_name_key(self):
        """When both 'en' and 'name' are present, 'en' is checked first."""
        assert localized({"en": "English Value", "name": {"en": "Name Value"}}) == "English Value"

    @pytest.mark.unit
    def test_name_key_checked_before_fallback(self):
        """When 'name' key exists but no 'en', recurse into 'name' before fallback."""
        result = localized({"name": {"en": "Resolved"}, "de": "Fallback"})
        # 'en' is not at top level, but 'name' sub-key has 'en'
        # Since "en" not in value, and "name" in value, it recurses
        assert result == "Resolved"

    @pytest.mark.unit
    def test_name_sub_key_with_plain_string(self):
        """name sub-key is a plain string -- recursion delegates to localized(str)."""
        assert localized({"name": "Simple Name"}) == "Simple Name"

    @pytest.mark.unit
    def test_name_sub_key_with_none(self):
        """name sub-key is None -- recursion into localized(None) returns empty."""
        assert localized({"name": None}) == ""

    @pytest.mark.unit
    def test_single_non_en_language(self):
        assert localized({"ja": "Presentation"}) == "Presentation"


# ---------------------------------------------------------------------------
# resolve_id_or_localized()
# ---------------------------------------------------------------------------


class TestResolveIdOrLocalized:
    """Tests for the resolve_id_or_localized() normalization helper."""

    @pytest.mark.unit
    def test_none_returns_empty_string(self):
        assert resolve_id_or_localized(None) == ""

    @pytest.mark.unit
    def test_none_with_mapping_returns_empty_string(self):
        assert resolve_id_or_localized(None, {1: "Room A"}) == ""

    @pytest.mark.unit
    def test_integer_with_mapping_returns_mapped_name(self):
        mapping = {7: "Tutorial", 12: "Talk"}
        assert resolve_id_or_localized(7, mapping) == "Tutorial"

    @pytest.mark.unit
    def test_integer_without_mapping_returns_str_of_int(self):
        assert resolve_id_or_localized(42) == "42"

    @pytest.mark.unit
    def test_integer_with_none_mapping_returns_str_of_int(self):
        assert resolve_id_or_localized(42, None) == "42"

    @pytest.mark.unit
    def test_integer_with_empty_mapping_returns_str_of_int(self):
        assert resolve_id_or_localized(42, {}) == "42"

    @pytest.mark.unit
    def test_mapping_with_missing_key_returns_str_of_int(self):
        mapping = {7: "Tutorial"}
        assert resolve_id_or_localized(99, mapping) == "99"

    @pytest.mark.unit
    def test_string_value_delegates_to_localized(self):
        assert resolve_id_or_localized("Talk") == "Talk"

    @pytest.mark.unit
    def test_empty_string_delegates_to_localized(self):
        assert resolve_id_or_localized("") == ""

    @pytest.mark.unit
    def test_dict_value_delegates_to_localized(self):
        assert resolve_id_or_localized({"en": "Workshop"}) == "Workshop"

    @pytest.mark.unit
    def test_dict_with_name_sub_key(self):
        assert resolve_id_or_localized({"name": {"en": "Poster"}}) == "Poster"

    @pytest.mark.unit
    def test_dict_without_en_falls_back(self):
        result = resolve_id_or_localized({"de": "Vortrag"})
        assert result == "Vortrag"

    @pytest.mark.unit
    def test_integer_zero_with_mapping(self):
        """Zero is a valid integer ID; should be looked up in mapping."""
        mapping = {0: "Default Room"}
        assert resolve_id_or_localized(0, mapping) == "Default Room"

    @pytest.mark.unit
    def test_integer_zero_without_mapping(self):
        """Zero without mapping should return '0'."""
        assert resolve_id_or_localized(0) == "0"

    @pytest.mark.unit
    def test_negative_integer_without_mapping(self):
        assert resolve_id_or_localized(-1) == "-1"

    @pytest.mark.unit
    def test_string_with_mapping_ignores_mapping(self):
        """String values should go through localized(), not the mapping path."""
        mapping = {7: "Tutorial"}
        assert resolve_id_or_localized("Talk", mapping) == "Talk"

    @pytest.mark.unit
    def test_dict_with_mapping_ignores_mapping(self):
        """Dict values should go through localized(), not the mapping path."""
        mapping = {7: "Tutorial"}
        assert resolve_id_or_localized({"en": "Workshop"}, mapping) == "Workshop"
