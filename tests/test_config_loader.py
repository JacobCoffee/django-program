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
