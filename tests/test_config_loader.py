from decimal import Decimal

import pytest

from django_program.config_loader import load_conference_config


def test_load_conference_config_parses_prices_as_decimal(tmp_path):
    config_file = tmp_path / "conference.toml"
    config_file.write_text("""[conference]
name = "PyCon Test"
start = 2027-05-01
end = 2027-05-03
timezone = "UTC"

[[conference.sections]]
name = "Talks"
start = 2027-05-01
end = 2027-05-03

[[conference.tickets]]
name = "Standard"
price = 99.95
quantity = 10

[[conference.sponsor_levels]]
name = "Gold"
cost = 1500.50
""")

    conf = load_conference_config(config_file)

    assert isinstance(conf["tickets"][0]["price"], Decimal)
    assert conf["tickets"][0]["price"] == Decimal("99.95")
    assert isinstance(conf["sponsor_levels"][0]["cost"], Decimal)
    assert conf["sponsor_levels"][0]["cost"] == Decimal("1500.50")


def test_load_conference_config_rejects_duplicate_generated_slugs(tmp_path):
    config_file = tmp_path / "conference.toml"
    config_file.write_text("""[conference]
name = "PyCon Test"
start = 2027-05-01
end = 2027-05-03
timezone = "UTC"

[[conference.sections]]
name = "Talks"
start = 2027-05-01
end = 2027-05-01

[[conference.sections]]
name = "Talks"
start = 2027-05-02
end = 2027-05-02
""")

    with pytest.raises(ValueError, match="duplicate slugs: talks"):
        load_conference_config(config_file)


def test_load_conference_config_file_not_found(tmp_path):
    """Lines 122-123: FileNotFoundError when config path does not exist."""
    missing = tmp_path / "does_not_exist.toml"

    with pytest.raises(FileNotFoundError, match="Conference config file not found"):
        load_conference_config(missing)


def test_load_conference_config_invalid_toml(tmp_path):
    """Lines 128-130: ValueError when the file contains invalid TOML syntax."""
    config_file = tmp_path / "conference.toml"
    config_file.write_text("this is [[[not valid toml")

    with pytest.raises(ValueError, match="Invalid TOML in"):
        load_conference_config(config_file)


def test_load_conference_config_missing_conference_table(tmp_path):
    """Lines 133-134: ValueError when [conference] table is absent."""
    config_file = tmp_path / "conference.toml"
    config_file.write_text("""[something_else]
name = "Not a conference"
""")

    with pytest.raises(ValueError, match="Missing required \\[conference\\] table"):
        load_conference_config(config_file)


def test_load_conference_config_missing_required_conference_fields(tmp_path):
    """Lines 167-168: ValueError when required conference fields are missing."""
    config_file = tmp_path / "conference.toml"
    config_file.write_text("""[conference]
name = "PyCon Test"

[[conference.sections]]
name = "Talks"
start = 2027-05-01
end = 2027-05-01
""")

    with pytest.raises(ValueError, match="is missing required fields"):
        load_conference_config(config_file)


def test_load_conference_config_sections_missing_when_required(tmp_path):
    """Lines 89-90: ValueError when sections key is absent (must_exist=True)."""
    config_file = tmp_path / "conference.toml"
    config_file.write_text("""[conference]
name = "PyCon Test"
start = 2027-05-01
end = 2027-05-03
timezone = "UTC"
""")

    with pytest.raises(ValueError, match=r"conference\.sections must be a non-empty list"):
        load_conference_config(config_file)


def test_load_conference_config_sections_not_a_list(tmp_path):
    """Lines 94-95: ValueError when sections is not a list (e.g. a string)."""
    config_file = tmp_path / "conference.toml"
    config_file.write_text("""[conference]
name = "PyCon Test"
start = 2027-05-01
end = 2027-05-03
timezone = "UTC"
sections = "not a list"
""")

    with pytest.raises(ValueError, match=r"conference\.sections must be a non-empty list"):
        load_conference_config(config_file)


def test_load_conference_config_section_missing_required_fields(tmp_path):
    """Lines 167-168 (via sections): ValueError when a section is missing required fields."""
    config_file = tmp_path / "conference.toml"
    config_file.write_text("""[conference]
name = "PyCon Test"
start = 2027-05-01
end = 2027-05-03
timezone = "UTC"

[[conference.sections]]
start = 2027-05-01
end = 2027-05-01
""")

    with pytest.raises(ValueError, match="is missing required fields: name"):
        load_conference_config(config_file)


def test_load_conference_config_addon_missing_name_for_slug(tmp_path):
    """Lines 45-46: ValueError when an addon has no slug and no name to generate one.

    Addons are validated without required_fields, so _validate_mapping passes,
    but _ensure_slugs fails because there is no name to derive a slug from.
    """
    config_file = tmp_path / "conference.toml"
    config_file.write_text("""[conference]
name = "PyCon Test"
start = 2027-05-01
end = 2027-05-03
timezone = "UTC"

[[conference.sections]]
name = "Talks"
start = 2027-05-01
end = 2027-05-01

[[conference.addons]]
description = "An addon without a name"
""")

    with pytest.raises(ValueError, match="is missing required field: name"):
        load_conference_config(config_file)


def test_load_conference_config_list_item_not_a_mapping(tmp_path):
    """Lines 163-164: TypeError when a list item is not a dict/mapping."""
    config_file = tmp_path / "conference.toml"
    config_file.write_text("""[conference]
name = "PyCon Test"
start = 2027-05-01
end = 2027-05-03
timezone = "UTC"
addons = ["not-a-dict"]

[[conference.sections]]
name = "Talks"
start = 2027-05-01
end = 2027-05-01
""")

    with pytest.raises(TypeError, match="must be a mapping, got str"):
        load_conference_config(config_file)


def test_load_conference_config_slug_empty_string(tmp_path):
    """Lines 58-59: ValueError when an item's slug is an empty string."""
    config_file = tmp_path / "conference.toml"
    config_file.write_text("""[conference]
name = "PyCon Test"
start = 2027-05-01
end = 2027-05-03
timezone = "UTC"

[[conference.sections]]
name = "Talks"
slug = ""
start = 2027-05-01
end = 2027-05-01
""")

    with pytest.raises(ValueError, match="slug must be a non-empty string"):
        load_conference_config(config_file)
