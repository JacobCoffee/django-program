"""Model forms for the conference management dashboard.

Each form that wraps a pretalx-synced model accepts an ``is_synced`` flag.
When the record has been synced from Pretalx (``synced_at`` is not None),
all fields are rendered as disabled so organizers cannot accidentally
overwrite upstream data.
"""

from django import forms
from django.core.validators import RegexValidator

from django_program.conference.models import Conference, Section
from django_program.pretalx.models import Room, ScheduleSlot, Talk


class ImportFromPretalxForm(forms.Form):
    """Form for importing a new conference from a Pretalx event slug.

    Accepts a Pretalx event slug and optional conference slug override.
    The event slug is used to fetch event metadata from the Pretalx API
    and bootstrap a new Conference object with a full data sync.
    """

    pretalx_event_slug = forms.CharField(
        max_length=200,
        label="Pretalx Event Slug",
        help_text='The event identifier from the Pretalx URL, e.g. "pyconus2025".',
        validators=[
            RegexValidator(
                regex=r"^[a-zA-Z0-9_-]+$",
                message="Slug may only contain letters, numbers, hyphens, and underscores.",
            ),
        ],
    )
    conference_slug = forms.SlugField(
        max_length=200,
        required=False,
        label="Conference Slug (optional)",
        help_text="Override the URL slug for this conference. Defaults to the Pretalx event slug.",
    )
    api_token = forms.CharField(
        max_length=500,
        required=False,
        label="API Token (optional)",
        help_text="Pretalx API token. Overrides the configured token for this import.",
        widget=forms.PasswordInput(
            render_value=True,
            attrs={
                # Prevent browser password managers from autofilling account passwords.
                "autocomplete": "new-password",
                "autocapitalize": "none",
                "spellcheck": "false",
                "data-lpignore": "true",
            },
        ),
    )


class ConferenceForm(forms.ModelForm):
    """Form for editing conference details.

    Stripe secret keys are excluded for security, along with auto-managed
    timestamp fields.  The slug is excluded because it serves as the URL
    identifier and should not be casually changed.
    """

    class Meta:
        model = Conference
        fields = [
            "name",
            "start_date",
            "end_date",
            "timezone",
            "venue",
            "website_url",
            "pretalx_event_slug",
            "is_active",
        ]


class SectionForm(forms.ModelForm):
    """Form for editing a conference section."""

    class Meta:
        model = Section
        fields = ["name", "slug", "start_date", "end_date", "order"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }


class RoomForm(forms.ModelForm):
    """Form for editing a room.

    When the room has been synced from Pretalx, all fields are disabled
    to prevent overwriting upstream data.
    """

    class Meta:
        model = Room
        fields = ["name", "description", "capacity", "position"]

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialise the form and disable fields when synced from Pretalx."""
        self.is_synced: bool = kwargs.pop("is_synced", False)  # type: ignore[arg-type]
        super().__init__(*args, **kwargs)
        if self.is_synced:
            for field_name in self.fields:
                self.fields[field_name].disabled = True


class TalkForm(forms.ModelForm):
    """Form for editing a talk.

    Pretalx-synced fields are disabled when the record was last synced
    from the upstream API.
    """

    SYNCED_FIELDS: list[str] = [
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

    class Meta:
        model = Talk
        fields = [
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

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialise the form and disable synced fields when locked by Pretalx."""
        self.is_synced: bool = kwargs.pop("is_synced", False)  # type: ignore[arg-type]
        super().__init__(*args, **kwargs)
        if self.is_synced:
            for field_name in self.SYNCED_FIELDS:
                if field_name in self.fields:
                    self.fields[field_name].disabled = True


class ScheduleSlotForm(forms.ModelForm):
    """Form for editing a schedule slot.

    Pretalx-synced fields are disabled when the slot has been synced
    from the upstream Pretalx API.
    """

    SYNCED_FIELDS: list[str] = [
        "talk",
        "title",
        "room",
        "start",
        "end",
        "slot_type",
    ]

    class Meta:
        model = ScheduleSlot
        fields = ["talk", "title", "room", "start", "end", "slot_type"]

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialise the form and disable synced fields when locked by Pretalx."""
        self.is_synced: bool = kwargs.pop("is_synced", False)  # type: ignore[arg-type]
        super().__init__(*args, **kwargs)
        if self.is_synced:
            for field_name in self.SYNCED_FIELDS:
                if field_name in self.fields:
                    self.fields[field_name].disabled = True
