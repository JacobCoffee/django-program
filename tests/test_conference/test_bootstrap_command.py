import datetime
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from django_program.conference.management.commands.bootstrap_conference import Command
from django_program.conference.models import Conference, Section
from django_program.registration.models import AddOn


def _write_config(path, contents):
    path.write_text(contents)
    return str(path)


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
        call_command("bootstrap_conference", config=str(config_file))


@pytest.mark.django_db
def test_bootstrap_creates_records_with_date_fields_and_default_section_order(tmp_path):
    config_file = tmp_path / "conference.toml"
    config_path = _write_config(
        config_file,
        """[conference]
name = "PyCon Test"
start = 2027-05-01
end = 2027-05-03
timezone = "UTC"

[[conference.sections]]
name = "Tutorials"
start = 2027-05-01
end = 2027-05-01

[[conference.sections]]
name = "Talks"
start = 2027-05-02
end = 2027-05-02

[[conference.sections]]
name = "Sprints"
start = 2027-05-03
end = 2027-05-03
""",
    )

    call_command("bootstrap_conference", config=config_path)

    conference = Conference.objects.get(slug="pycon-test")
    assert isinstance(conference.start_date, datetime.date)
    assert isinstance(conference.end_date, datetime.date)

    sections = list(Section.objects.filter(conference=conference).order_by("order", "start_date"))
    assert [section.slug for section in sections] == ["tutorials", "talks", "sprints"]
    assert [section.order for section in sections] == [0, 1, 2]
    assert all(isinstance(section.start_date, datetime.date) for section in sections)
    assert all(isinstance(section.end_date, datetime.date) for section in sections)


@pytest.mark.django_db
def test_bootstrap_update_respects_explicit_and_default_section_order(tmp_path):
    initial_config = _write_config(
        tmp_path / "initial.toml",
        """[conference]
name = "PyCon Test"
start = 2027-05-01
end = 2027-05-03
timezone = "UTC"

[[conference.sections]]
name = "Tutorials"
start = 2027-05-01
end = 2027-05-01

[[conference.sections]]
name = "Talks"
start = 2027-05-02
end = 2027-05-02
""",
    )
    call_command("bootstrap_conference", config=initial_config)

    updated_config = _write_config(
        tmp_path / "updated.toml",
        """[conference]
name = "PyCon Test Updated"
slug = "pycon-test"
start = 2027-05-05
end = 2027-05-08
timezone = "UTC"

[[conference.sections]]
name = "Talks Updated"
slug = "talks"
start = 2027-05-06
end = 2027-05-06
order = 7

[[conference.sections]]
name = "Tutorials Updated"
slug = "tutorials"
start = 2027-05-05
end = 2027-05-05

[[conference.sections]]
name = "Sprints"
start = 2027-05-08
end = 2027-05-08
""",
    )
    call_command("bootstrap_conference", config=updated_config, update=True)

    conference = Conference.objects.get(slug="pycon-test")
    assert conference.name == "PyCon Test Updated"
    assert isinstance(conference.start_date, datetime.date)
    assert isinstance(conference.end_date, datetime.date)
    assert conference.start_date == datetime.date(2027, 5, 5)
    assert conference.end_date == datetime.date(2027, 5, 8)

    tutorials = Section.objects.get(conference=conference, slug="tutorials")
    talks = Section.objects.get(conference=conference, slug="talks")
    sprints = Section.objects.get(conference=conference, slug="sprints")

    assert tutorials.order == 1
    assert talks.order == 7
    assert sprints.order == 2
    assert isinstance(tutorials.start_date, datetime.date)
    assert isinstance(talks.start_date, datetime.date)
    assert isinstance(sprints.start_date, datetime.date)

    ordered_slugs = list(
        Section.objects.filter(conference=conference).order_by("order", "start_date").values_list("slug", flat=True),
    )
    assert ordered_slugs == ["tutorials", "sprints", "talks"]


@pytest.mark.django_db
def test_bootstrap_sets_addon_availability_window(tmp_path):
    config_path = _write_config(
        tmp_path / "addons.toml",
        """[conference]
name = "PyCon Test"
start = 2027-05-01
end = 2027-05-03
timezone = "UTC"

[[conference.sections]]
name = "Talks"
start = 2027-05-02
end = 2027-05-02

[[conference.tickets]]
name = "Individual"
price = 100.00
quantity = 100

[[conference.addons]]
name = "Workshop"
price = 50.00
quantity = 25
available = { opens = 2027-04-01, closes = 2027-04-15 }
""",
    )

    call_command("bootstrap_conference", config=config_path)

    conference = Conference.objects.get(slug="pycon-test")
    addon = AddOn.objects.get(conference=conference, slug="workshop")
    assert addon.available_from is not None
    assert addon.available_until is not None
    assert addon.available_from.date() == datetime.date(2027, 4, 1)
    assert addon.available_until.date() == datetime.date(2027, 4, 15)
    assert addon.available_from.tzinfo is not None
    assert addon.available_until.tzinfo is not None


@pytest.mark.django_db
def test_bootstrap_fails_when_addon_requires_unknown_ticket_slug(tmp_path):
    config_path = _write_config(
        tmp_path / "bad_requires.toml",
        """[conference]
name = "PyCon Test"
start = 2027-05-01
end = 2027-05-03
timezone = "UTC"

[[conference.sections]]
name = "Talks"
start = 2027-05-02
end = 2027-05-02

[[conference.tickets]]
name = "Individual"
price = 100.00
quantity = 100

[[conference.addons]]
name = "Workshop"
price = 50.00
quantity = 25
requires = ["individual", "missing-ticket"]
""",
    )

    with pytest.raises(CommandError, match=r"unknown required ticket slug\(s\): missing-ticket"):
        call_command("bootstrap_conference", config=config_path)


@pytest.mark.django_db
def test_bootstrap_duplicate_slug_without_update_raises_command_error(tmp_path):
    """Creating a conference with an existing slug without --update raises CommandError."""
    config_path = _write_config(
        tmp_path / "conf.toml",
        """[conference]
name = "PyCon Dupe"
start = 2027-05-01
end = 2027-05-03
timezone = "UTC"

[[conference.sections]]
name = "Talks"
start = 2027-05-02
end = 2027-05-02
""",
    )

    call_command("bootstrap_conference", config=config_path)

    with pytest.raises(CommandError, match=r"already exists\. Use --update"):
        call_command("bootstrap_conference", config=config_path)


@pytest.mark.django_db
def test_bootstrap_existing_section_without_update_skips(tmp_path):
    """Calling _bootstrap_sections with update=False skips sections that already exist.

    This branch is defensive: in normal CLI usage the conference-level
    duplicate check fires first.  We exercise it directly to prove the
    per-section skip works.
    """
    config_path = _write_config(
        tmp_path / "conf.toml",
        """[conference]
name = "PyCon Sections"
start = 2027-05-01
end = 2027-05-03
timezone = "UTC"

[[conference.sections]]
name = "Tutorials"
start = 2027-05-01
end = 2027-05-01

[[conference.sections]]
name = "Talks"
start = 2027-05-02
end = 2027-05-02
""",
    )
    call_command("bootstrap_conference", config=config_path)

    conference = Conference.objects.get(slug="pycon-sections")

    cmd = Command(stdout=StringIO())
    sections_data = [
        {"name": "Tutorials", "slug": "tutorials", "start": "2027-05-01", "end": "2027-05-01"},
        {"name": "Talks", "slug": "talks", "start": "2027-05-02", "end": "2027-05-02"},
    ]
    created, updated = cmd._bootstrap_sections(conference, sections_data, update=False)
    output = cmd.stdout.getvalue()

    assert created == []
    assert updated == []
    assert "already exists for this conference, skipping" in output
    assert Section.objects.filter(conference=conference).count() == 2


def test_bootstrap_dry_run_with_venue_and_website_url(tmp_path):
    """Dry-run prints venue and website_url when present in the config."""
    config_path = _write_config(
        tmp_path / "conf.toml",
        """[conference]
name = "PyCon Venue"
start = 2027-05-01
end = 2027-05-03
timezone = "UTC"
venue = "Pittsburgh Convention Center"
website_url = "https://us.pycon.org/2027"

[[conference.sections]]
name = "Talks"
start = 2027-05-02
end = 2027-05-02
""",
    )

    out = StringIO()
    call_command("bootstrap_conference", config=config_path, dry_run=True, stdout=out)
    output = out.getvalue()

    assert "[DRY RUN]" in output
    assert "Pittsburgh Convention Center" in output
    assert "https://us.pycon.org/2027" in output
    assert "Venue:" in output
    assert "Website:" in output


def test_bootstrap_dry_run_without_venue_and_website_url(tmp_path):
    """Dry-run omits venue and website lines when not present in the config."""
    config_path = _write_config(
        tmp_path / "conf.toml",
        """[conference]
name = "PyCon Minimal"
start = 2027-05-01
end = 2027-05-03
timezone = "UTC"

[[conference.sections]]
name = "Talks"
start = 2027-05-02
end = 2027-05-02
""",
    )

    out = StringIO()
    call_command("bootstrap_conference", config=config_path, dry_run=True, stdout=out)
    output = out.getvalue()

    assert "[DRY RUN]" in output
    assert "Venue:" not in output
    assert "Website:" not in output


@pytest.mark.django_db
def test_bootstrap_verbose_summary_lists_created_and_updated_sections(tmp_path):
    """With verbosity=2, the summary lists individual created and updated sections."""
    initial_config = _write_config(
        tmp_path / "initial.toml",
        """[conference]
name = "PyCon Verbose"
start = 2027-05-01
end = 2027-05-03
timezone = "UTC"

[[conference.sections]]
name = "Tutorials"
start = 2027-05-01
end = 2027-05-01
""",
    )
    call_command("bootstrap_conference", config=initial_config)

    update_config = _write_config(
        tmp_path / "update.toml",
        """[conference]
name = "PyCon Verbose"
slug = "pycon-verbose"
start = 2027-05-01
end = 2027-05-03
timezone = "UTC"

[[conference.sections]]
name = "Tutorials Revised"
slug = "tutorials"
start = 2027-05-01
end = 2027-05-01

[[conference.sections]]
name = "Sprints"
start = 2027-05-03
end = 2027-05-03
""",
    )

    out = StringIO()
    call_command("bootstrap_conference", config=update_config, update=True, verbosity=2, stdout=out)
    output = out.getvalue()

    assert "Bootstrap summary:" in output
    assert "+ Sprints (sprints)" in output
    assert "~ Tutorials Revised (tutorials)" in output


@pytest.mark.django_db
def test_bootstrap_default_verbosity_omits_section_details(tmp_path):
    """With default verbosity (1), the summary does not list individual sections."""
    config_path = _write_config(
        tmp_path / "conf.toml",
        """[conference]
name = "PyCon Default"
start = 2027-05-01
end = 2027-05-03
timezone = "UTC"

[[conference.sections]]
name = "Talks"
start = 2027-05-02
end = 2027-05-02
""",
    )

    out = StringIO()
    call_command("bootstrap_conference", config=config_path, verbosity=1, stdout=out)
    output = out.getvalue()

    assert "Bootstrap summary:" in output
    assert "Sections created:  1" in output
    assert "+ Talks (talks)" not in output


def test_bootstrap_deferred_keys_prints_notice(tmp_path):
    """Config keys handled by other apps produce a notice about deferral."""
    config_path = _write_config(
        tmp_path / "conf.toml",
        """[conference]
name = "PyCon Deferred"
start = 2027-05-01
end = 2027-05-03
timezone = "UTC"

[[conference.sections]]
name = "Talks"
start = 2027-05-02
end = 2027-05-02

[[conference.sponsor_levels]]
name = "Gold"
""",
    )

    out = StringIO()
    call_command("bootstrap_conference", config=config_path, dry_run=True, stdout=out)
    output = out.getvalue()

    assert "Skipping 'sponsor_levels'" in output
    assert "sponsors app" in output
