"""Integration tests that exercise the example Django app entrypoint."""

import os
import subprocess
import sys
from pathlib import Path

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"
REPO_ROOT = EXAMPLES_DIR.parent


def _run_example_manage(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DJANGO_SETTINGS_MODULE"] = "settings"
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "manage.py", *args],
        cwd=EXAMPLES_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_example_app_django_check_passes() -> None:
    result = _run_example_manage("check")
    assert result.returncode == 0, result.stderr


def test_example_app_loads_and_renders_stripe_template_tag() -> None:
    result = _run_example_manage(
        "shell",
        "-c",
        (
            "from django.template import Context, Template; "
            "conference = type('C', (), {'stripe_publishable_key': 'pk_test_example'})(); "
            "output = Template('{% load stripe_tags %}{% stripe_public_key conference as key %}{{ key }}')"
            ".render(Context({'conference': conference})); "
            "print(output)"
        ),
    )
    assert result.returncode == 0, result.stderr
    assert "pk_test_example" in result.stdout
