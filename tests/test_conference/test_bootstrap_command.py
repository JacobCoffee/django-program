import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


def test_bootstrap_wraps_loader_type_errors_as_command_error(tmp_path):
    config_file = tmp_path / "bad.toml"
    config_file.write_text("""[conference]
name = "PyCon Test"
start = 2027-05-01
end = 2027-05-03
timezone = "UTC"

sections = ["invalid"]
""")

    with pytest.raises(CommandError, match=r"conference\.sections\[0\] must be a mapping"):
        call_command("bootstrap", config=str(config_file))
