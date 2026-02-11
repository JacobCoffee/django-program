import datetime

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from django_program.conference.models import Conference, Section


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
        call_command("bootstrap", config=str(config_file))


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

    call_command("bootstrap", config=config_path)

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
    call_command("bootstrap", config=initial_config)

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
    call_command("bootstrap", config=updated_config, update=True)

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
