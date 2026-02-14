"""Model forms for Pretalx overrides and submission type defaults."""

from django import forms
from django.core.exceptions import ValidationError

from django_program.pretalx.models import (
    Room,
    RoomOverride,
    Speaker,
    SpeakerOverride,
    SubmissionTypeDefault,
    Talk,
    TalkOverride,
)
from django_program.sponsors.models import Sponsor, SponsorLevel, SponsorOverride


class TalkLabelMixin:
    """Format Talk choices as 'Title [Type] (state)' for searchability."""

    def label_from_instance(self, obj: Talk) -> str:
        """Return a descriptive label for the talk option."""
        parts: list[str] = [str(obj.title)]
        if obj.submission_type:
            parts.append(f"[{obj.submission_type}]")
        if obj.state:
            parts.append(f"({obj.state})")
        return " ".join(parts)


class TalkChoiceField(TalkLabelMixin, forms.ModelChoiceField):
    """ModelChoiceField that renders Talk options with type and state."""


class SpeakerLabelMixin:
    """Format Speaker choices as 'Name (email)' for searchability."""

    def label_from_instance(self, obj: Speaker) -> str:
        """Return a descriptive label for the speaker option."""
        parts: list[str] = [str(obj.name)]
        if obj.email:
            parts.append(f"({obj.email})")
        return " ".join(parts)


class SpeakerChoiceField(SpeakerLabelMixin, forms.ModelChoiceField):
    """ModelChoiceField that renders Speaker options with email."""


class RoomLabelMixin:
    """Format Room choices as 'Name [capacity]' for searchability."""

    def label_from_instance(self, obj: Room) -> str:
        """Return a descriptive label for the room option."""
        parts: list[str] = [str(obj.name)]
        if obj.capacity:
            parts.append(f"[{obj.capacity}]")
        return " ".join(parts)


class RoomChoiceField(RoomLabelMixin, forms.ModelChoiceField):
    """ModelChoiceField that renders Room options with capacity."""


class SponsorLabelMixin:
    """Format Sponsor choices as 'Name (Level)' for searchability."""

    def label_from_instance(self, obj: Sponsor) -> str:
        """Return a descriptive label for the sponsor option."""
        return f"{obj.name} ({obj.level.name})"


class SponsorChoiceField(SponsorLabelMixin, forms.ModelChoiceField):
    """ModelChoiceField that renders Sponsor options with level."""


class TalkOverrideForm(forms.ModelForm):
    """Form for creating or editing a talk override."""

    talk = TalkChoiceField(queryset=Talk.objects.none())

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
        """Scope choice querysets to the given conference."""
        super().__init__(*args, **kwargs)
        if conference is not None:
            self.fields["talk"].queryset = Talk.objects.filter(conference=conference).order_by(
                "submission_type", "title"
            )
            self.fields["override_room"].queryset = Room.objects.filter(conference=conference)

        if is_edit:
            self.fields["talk"].disabled = True


class SpeakerOverrideForm(forms.ModelForm):
    """Form for creating or editing a speaker override."""

    speaker = SpeakerChoiceField(queryset=Speaker.objects.none())

    class Meta:
        model = SpeakerOverride
        fields = [
            "speaker",
            "override_name",
            "override_biography",
            "override_avatar_url",
            "override_email",
            "note",
        ]
        widgets = {
            "override_biography": forms.Textarea(attrs={"rows": 4}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args: object, conference: object = None, is_edit: bool = False, **kwargs: object) -> None:
        """Scope choice querysets to the given conference."""
        super().__init__(*args, **kwargs)
        if conference is not None:
            self.fields["speaker"].queryset = Speaker.objects.filter(conference=conference).order_by("name")

        if is_edit:
            self.fields["speaker"].disabled = True


class RoomOverrideForm(forms.ModelForm):
    """Form for creating or editing a room override."""

    room = RoomChoiceField(queryset=Room.objects.none())

    class Meta:
        model = RoomOverride
        fields = [
            "room",
            "override_name",
            "override_description",
            "override_capacity",
            "note",
        ]
        widgets = {
            "override_description": forms.Textarea(attrs={"rows": 4}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args: object, conference: object = None, is_edit: bool = False, **kwargs: object) -> None:
        """Scope choice querysets to the given conference."""
        super().__init__(*args, **kwargs)
        if conference is not None:
            self.fields["room"].queryset = Room.objects.filter(conference=conference).order_by("position", "name")

        if is_edit:
            self.fields["room"].disabled = True


class SponsorOverrideForm(forms.ModelForm):
    """Form for creating or editing a sponsor override."""

    sponsor = SponsorChoiceField(queryset=Sponsor.objects.none())

    class Meta:
        model = SponsorOverride
        fields = [
            "sponsor",
            "override_name",
            "override_description",
            "override_website_url",
            "override_logo_url",
            "override_contact_name",
            "override_contact_email",
            "override_is_active",
            "override_level",
            "note",
        ]
        widgets = {
            "override_description": forms.Textarea(attrs={"rows": 4}),
            "note": forms.Textarea(attrs={"rows": 3}),
            "override_is_active": forms.Select(
                choices=((None, "Unknown"), (True, "Yes"), (False, "No")),
            ),
        }

    def __init__(self, *args: object, conference: object = None, is_edit: bool = False, **kwargs: object) -> None:
        """Scope choice querysets to the given conference."""
        super().__init__(*args, **kwargs)
        if conference is not None:
            self.fields["sponsor"].queryset = (
                Sponsor.objects.filter(conference=conference).select_related("level").order_by("name")
            )
            self.fields["override_level"].queryset = SponsorLevel.objects.filter(conference=conference).order_by(
                "order"
            )

        if is_edit:
            self.fields["sponsor"].disabled = True

    def clean_override_is_active(self) -> bool | None:
        """Convert Select widget string values to Python None/True/False."""
        value = self.data.get("override_is_active", "")
        if value == "" or value is None:
            return None
        if value == "True" or value is True:
            return True
        if value == "False" or value is False:
            return False
        return None


class SubmissionTypeDefaultForm(forms.ModelForm):
    """Form for creating or editing submission type default assignments."""

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
        """Scope choice querysets to the given conference."""
        super().__init__(*args, **kwargs)
        if conference is not None:
            self.fields["default_room"].queryset = Room.objects.filter(conference=conference)

    def clean(self) -> dict[str, object]:
        """Validate time field consistency.

        Ensures that:
        - ``default_date`` is required when either time field is set (times
          without a date are silently ignored by ``apply_type_defaults``).
        - ``default_start_time`` and ``default_end_time`` must be provided as
          a pair or not at all (partial time ranges are invalid).
        """
        cleaned = super().clean()
        start_time = cleaned.get("default_start_time")
        end_time = cleaned.get("default_end_time")
        has_date = cleaned.get("default_date") is not None

        if (start_time or end_time) and not has_date:
            raise ValidationError(
                {"default_date": "A date is required when start or end time is set."},
            )

        if bool(start_time) != bool(end_time):
            msg = "Both start and end time are required when either is set."
            errors: dict[str, str] = {}
            if not start_time:
                errors["default_start_time"] = msg
            if not end_time:
                errors["default_end_time"] = msg
            raise ValidationError(errors)

        return cleaned
