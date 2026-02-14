"""Model forms for Pretalx talk overrides and submission type defaults."""

from django import forms

from django_program.pretalx.models import Room, SubmissionTypeDefault, Talk, TalkOverride


class TalkOverrideForm(forms.ModelForm):
    """Form for creating or editing a talk override.

    Provides dropdowns for room and talk selection scoped to the current
    conference.  The ``talk`` field is only editable during creation; on
    edit, it is rendered as disabled.
    """

    class Meta:
        model = TalkOverride
        fields = [
            "talk",
            "override_room",
            "override_title",
            "override_state",
            "override_slot_start",
            "override_slot_end",
            "override_abstract",
            "is_cancelled",
            "note",
        ]
        widgets = {
            "override_slot_start": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "override_slot_end": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "override_abstract": forms.Textarea(attrs={"rows": 4}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args: object, conference: object = None, is_edit: bool = False, **kwargs: object) -> None:
        """Initialize with conference-scoped querysets.

        Args:
            conference: The conference to scope talk/room choices to.
            is_edit: When True, the talk field is rendered as disabled.
            *args: Positional arguments passed to ModelForm.
            **kwargs: Keyword arguments passed to ModelForm.
        """
        super().__init__(*args, **kwargs)
        if conference is not None:
            self.fields["talk"].queryset = Talk.objects.filter(conference=conference)
            self.fields["override_room"].queryset = Room.objects.filter(conference=conference)

        if is_edit:
            self.fields["talk"].disabled = True


class SubmissionTypeDefaultForm(forms.ModelForm):
    """Form for creating or editing submission type default assignments.

    Provides a text input for the submission type name and dropdowns for
    room selection scoped to the current conference.
    """

    class Meta:
        model = SubmissionTypeDefault
        fields = [
            "submission_type",
            "default_room",
            "default_date",
            "default_start_time",
            "default_end_time",
        ]
        widgets = {
            "default_date": forms.DateInput(attrs={"type": "date"}),
            "default_start_time": forms.TimeInput(attrs={"type": "time"}),
            "default_end_time": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args: object, conference: object = None, **kwargs: object) -> None:
        """Initialize with conference-scoped querysets.

        Args:
            conference: The conference to scope room choices to.
            *args: Positional arguments passed to ModelForm.
            **kwargs: Keyword arguments passed to ModelForm.
        """
        super().__init__(*args, **kwargs)
        if conference is not None:
            self.fields["default_room"].queryset = Room.objects.filter(conference=conference)
