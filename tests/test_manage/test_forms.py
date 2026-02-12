"""Tests for management dashboard forms."""

import pytest

from django_program.manage.forms import (
    ConferenceForm,
    ImportFromPretalxForm,
    RoomForm,
    ScheduleSlotForm,
    SectionForm,
    TalkForm,
)


class TestImportFromPretalxForm:
    """Form behavior for Pretalx import."""

    def test_api_token_widget_uses_anti_autofill_attributes(self):
        form = ImportFromPretalxForm()
        widget_attrs = form.fields["api_token"].widget.attrs

        assert widget_attrs["autocomplete"] == "new-password"
        assert widget_attrs["autocapitalize"] == "none"
        assert widget_attrs["spellcheck"] == "false"
        assert widget_attrs["data-lpignore"] == "true"

    def test_valid_slug(self):
        form = ImportFromPretalxForm(data={"pretalx_event_slug": "pycon2027"})
        assert form.is_valid()

    def test_invalid_slug_with_spaces(self):
        form = ImportFromPretalxForm(data={"pretalx_event_slug": "bad slug"})
        assert not form.is_valid()
        assert "pretalx_event_slug" in form.errors

    def test_empty_slug(self):
        form = ImportFromPretalxForm(data={"pretalx_event_slug": ""})
        assert not form.is_valid()

    def test_optional_conference_slug(self):
        form = ImportFromPretalxForm(data={"pretalx_event_slug": "pycon2027", "conference_slug": "custom"})
        assert form.is_valid()
        assert form.cleaned_data["conference_slug"] == "custom"

    def test_optional_api_token(self):
        form = ImportFromPretalxForm(data={"pretalx_event_slug": "pycon2027", "api_token": "tok123"})
        assert form.is_valid()
        assert form.cleaned_data["api_token"] == "tok123"


@pytest.mark.django_db
class TestConferenceForm:
    """ConferenceForm field coverage."""

    def test_meta_fields(self):
        form = ConferenceForm()
        expected = [
            "name",
            "start_date",
            "end_date",
            "timezone",
            "venue",
            "website_url",
            "pretalx_event_slug",
            "is_active",
        ]
        assert list(form.fields.keys()) == expected

    def test_valid_data(self):
        form = ConferenceForm(
            data={
                "name": "Conf",
                "start_date": "2027-05-01",
                "end_date": "2027-05-03",
                "timezone": "UTC",
                "is_active": True,
            }
        )
        assert form.is_valid()


@pytest.mark.django_db
class TestSectionForm:
    """SectionForm field and widget coverage."""

    def test_meta_fields(self):
        form = SectionForm()
        expected = ["name", "slug", "start_date", "end_date", "order"]
        assert list(form.fields.keys()) == expected

    def test_date_widgets_are_date_input(self):
        form = SectionForm()
        assert form.fields["start_date"].widget.input_type == "date"
        assert form.fields["end_date"].widget.input_type == "date"


@pytest.mark.django_db
class TestRoomForm:
    """RoomForm with is_synced behavior."""

    def test_not_synced_fields_editable(self):
        form = RoomForm(is_synced=False)
        for field in form.fields.values():
            assert not field.disabled

    def test_synced_fields_disabled(self):
        form = RoomForm(is_synced=True)
        for field_name, field in form.fields.items():
            assert field.disabled, f"Field {field_name} should be disabled when is_synced=True"

    def test_default_is_synced_false(self):
        form = RoomForm()
        assert form.is_synced is False
        for field in form.fields.values():
            assert not field.disabled

    def test_meta_fields(self):
        form = RoomForm()
        expected = ["name", "description", "capacity", "position"]
        assert list(form.fields.keys()) == expected


@pytest.mark.django_db
class TestTalkForm:
    """TalkForm with is_synced behavior."""

    def test_not_synced_fields_editable(self):
        form = TalkForm(is_synced=False)
        for field_name in TalkForm.SYNCED_FIELDS:
            if field_name in form.fields:
                assert not form.fields[field_name].disabled

    def test_synced_fields_disabled(self):
        form = TalkForm(is_synced=True)
        for field_name in TalkForm.SYNCED_FIELDS:
            if field_name in form.fields:
                assert form.fields[field_name].disabled, f"Synced field {field_name} should be disabled"

    def test_default_is_synced_false(self):
        form = TalkForm()
        assert form.is_synced is False

    def test_synced_fields_list(self):
        expected = [
            "pretalx_code",
            "title",
            "abstract",
            "description",
            "submission_type",
            "track",
            "duration",
            "state",
            "speakers",
            "room",
            "slot_start",
            "slot_end",
        ]
        assert TalkForm.SYNCED_FIELDS == expected

    def test_meta_fields(self):
        form = TalkForm()
        expected = [
            "pretalx_code",
            "title",
            "abstract",
            "description",
            "submission_type",
            "track",
            "duration",
            "state",
            "speakers",
            "room",
            "slot_start",
            "slot_end",
        ]
        assert list(form.fields.keys()) == expected


@pytest.mark.django_db
class TestScheduleSlotForm:
    """ScheduleSlotForm with is_synced behavior."""

    def test_not_synced_fields_editable(self):
        form = ScheduleSlotForm(is_synced=False)
        for field_name in ScheduleSlotForm.SYNCED_FIELDS:
            if field_name in form.fields:
                assert not form.fields[field_name].disabled

    def test_synced_fields_disabled(self):
        form = ScheduleSlotForm(is_synced=True)
        for field_name in ScheduleSlotForm.SYNCED_FIELDS:
            if field_name in form.fields:
                assert form.fields[field_name].disabled, f"Synced field {field_name} should be disabled"

    def test_default_is_synced_false(self):
        form = ScheduleSlotForm()
        assert form.is_synced is False

    def test_synced_fields_list(self):
        expected = ["talk", "title", "room", "start", "end", "slot_type"]
        assert ScheduleSlotForm.SYNCED_FIELDS == expected

    def test_meta_fields(self):
        form = ScheduleSlotForm()
        expected = ["talk", "title", "room", "start", "end", "slot_type"]
        assert list(form.fields.keys()) == expected
