"""Model forms for the conference management dashboard.

Each form that wraps a pretalx-synced model accepts an ``is_synced`` flag.
When the record has been synced from Pretalx (``synced_at`` is not None),
all fields are rendered as disabled so organizers cannot accidentally
overwrite upstream data.
"""

import datetime

from django import forms
from django.core.validators import RegexValidator

from django_program.conference.models import Conference, Section
from django_program.pretalx.models import Room, ScheduleSlot, Talk
from django_program.programs.models import Activity, TravelGrant, TravelGrantMessage
from django_program.sponsors.models import Sponsor, SponsorLevel


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
        fields = ["name", "start_date", "end_date", "order"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args: object, conference: Conference | None = None, **kwargs: object) -> None:
        """Build date select choices from the conference date range."""
        super().__init__(*args, **kwargs)
        if conference and conference.start_date and conference.end_date:
            day_choices = self._build_date_choices(conference.start_date, conference.end_date)
            self.fields["start_date"] = forms.TypedChoiceField(
                choices=[("", "---"), *day_choices],
                coerce=datetime.date.fromisoformat,
                label="Start date",
            )
            self.fields["end_date"] = forms.TypedChoiceField(
                choices=[("", "---"), *day_choices],
                coerce=datetime.date.fromisoformat,
                label="End date",
            )
            if self.instance and self.instance.pk:
                if self.instance.start_date:
                    self.initial["start_date"] = self.instance.start_date.isoformat()
                if self.instance.end_date:
                    self.initial["end_date"] = self.instance.end_date.isoformat()

    @staticmethod
    def _build_date_choices(start: datetime.date, end: datetime.date) -> list[tuple[str, str]]:
        """Build a list of (iso_date, label) for each day in the range."""
        choices: list[tuple[str, str]] = []
        current = start
        while current <= end:
            label = current.strftime("%A, %B %-d, %Y")
            choices.append((current.isoformat(), label))
            current += datetime.timedelta(days=1)
        return choices


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


class SponsorLevelForm(forms.ModelForm):
    """Form for editing a sponsor level."""

    class Meta:
        model = SponsorLevel
        fields = ["name", "cost", "description", "benefits_summary", "comp_ticket_count", "order"]


class SponsorForm(forms.ModelForm):
    """Form for editing a sponsor.

    When the sponsor has an ``external_id`` (synced from the PSF API),
    fields that come from the upstream API are disabled to prevent
    overwriting synced data.
    """

    SYNCED_FIELDS: list[str] = [
        "name",
        "level",
        "website_url",
        "logo_url",
        "description",
    ]

    class Meta:
        model = Sponsor
        fields = [
            "name",
            "level",
            "website_url",
            "logo",
            "logo_url",
            "description",
            "contact_name",
            "contact_email",
            "is_active",
        ]

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialise the form and disable synced fields when locked by PSF sync."""
        self.is_synced: bool = kwargs.pop("is_synced", False)  # type: ignore[arg-type]
        super().__init__(*args, **kwargs)
        if self.is_synced:
            for field_name in self.SYNCED_FIELDS:
                if field_name in self.fields:
                    self.fields[field_name].disabled = True


class ActivityForm(forms.ModelForm):
    """Form for editing a conference activity.

    The ``slug`` field is excluded because it is auto-generated from
    the activity name.  The ``room`` field provides an optional link to
    a Pretalx-synced room for venue assignment.
    """

    class Meta:
        model = Activity
        fields = [
            "name",
            "activity_type",
            "description",
            "room",
            "location",
            "pretalx_submission_type",
            "start_time",
            "end_time",
            "max_participants",
            "requires_ticket",
            "external_url",
            "is_active",
        ]
        widgets = {
            "start_time": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "end_time": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }


class TravelGrantForm(forms.ModelForm):
    """Form for reviewing a travel grant application."""

    class Meta:
        model = TravelGrant
        fields = [
            "status",
            "approved_amount",
            "promo_code",
            "reviewer_notes",
        ]
        widgets = {
            "status": forms.Select(attrs={"autocomplete": "off"}),
        }


class ReviewerMessageForm(forms.ModelForm):
    """Form for reviewers to send a message on a travel grant."""

    class Meta:
        model = TravelGrantMessage
        fields = ["message", "visible"]
        widgets = {
            "message": forms.Textarea(attrs={"rows": 3, "placeholder": "Write a message..."}),
        }
        labels = {
            "visible": "Visible to applicant",
        }


class ReceiptFlagForm(forms.Form):
    """Form for flagging a receipt with a reason."""

    reason = forms.CharField(
        max_length=1024,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Reason for flagging this receipt..."}),
    )


class DisbursementForm(forms.Form):
    """Form for marking a travel grant as disbursed."""

    disbursed_amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Actual amount disbursed to the grantee.",
    )
