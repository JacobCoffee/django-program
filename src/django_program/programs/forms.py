"""Forms for the programs app."""

import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from django import forms

from django_program.conference.models import Section
from django_program.programs.models import PaymentInfo, Receipt, TravelGrant, TravelGrantMessage
from django_program.settings import get_config

if TYPE_CHECKING:
    from django_program.conference.models import Conference


class TravelGrantApplicationForm(forms.ModelForm):
    """Public-facing form for applying for a travel grant.

    Mirrors PyCon US's travel grant application flow.  Collects
    request type, travel plan breakdowns (airfare + lodging), applicant
    profile, and community involvement.  The ``conference`` and ``user``
    fields are set by the view, not the form.
    """

    days_attending = forms.MultipleChoiceField(
        choices=[],
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Which days do you plan to attend?",
    )

    class Meta:
        model = TravelGrant
        fields = [
            "request_type",
            "application_type",
            "travel_from",
            "international",
            "first_time",
            "days_attending",
            "travel_plans_airfare_description",
            "travel_plans_airfare_amount",
            "travel_plans_lodging_description",
            "travel_plans_lodging_amount",
            "requested_amount",
            "sharing_expenses",
            "traveling_with",
            "experience_level",
            "occupation",
            "involvement",
            "reason",
        ]
        widgets = {
            "request_type": forms.RadioSelect,
            "application_type": forms.Select,
            "experience_level": forms.Select,
            "first_time": forms.Select(
                choices=[(None, "---"), (True, "Yes"), (False, "No")],
            ),
            "international": forms.CheckboxInput,
            "sharing_expenses": forms.CheckboxInput,
            "travel_plans_airfare_amount": forms.NumberInput(
                attrs={"step": "0.01", "min": "0", "class": "amount-input"},
            ),
            "travel_plans_lodging_amount": forms.NumberInput(
                attrs={"step": "0.01", "min": "0", "class": "amount-input"},
            ),
            "requested_amount": forms.NumberInput(
                attrs={"step": "0.01", "min": "0.01"},
            ),
            "travel_plans_airfare_description": forms.TextInput(
                attrs={"placeholder": "e.g. Round-trip flight from Chicago, IL to Pittsburgh, PA"},
            ),
            "travel_plans_lodging_description": forms.TextInput(
                attrs={"placeholder": "e.g. 4 nights at the conference hotel"},
            ),
            "reason": forms.Textarea(attrs={"rows": 4}),
            "involvement": forms.Textarea(attrs={"rows": 3}),
            "occupation": forms.Textarea(attrs={"rows": 2}),
            "traveling_with": forms.Textarea(attrs={"rows": 2}),
        }
        labels = {
            "request_type": "What are you requesting?",
            "application_type": "Application type",
            "travel_from": "Traveling from",
            "international": "International travel",
            "first_time": "First time attending this conference?",
            "days_attending": "Which days do you plan to attend?",
            "travel_plans_airfare_description": "Airfare details",
            "travel_plans_airfare_amount": "Airfare amount (USD)",
            "travel_plans_lodging_description": "Lodging details",
            "travel_plans_lodging_amount": "Lodging amount (USD)",
            "requested_amount": "Total amount requested (USD)",
            "sharing_expenses": "Sharing travel expenses with another applicant?",
            "traveling_with": "Who are you traveling with?",
            "experience_level": "Python experience level",
            "occupation": "Current occupation or situation",
            "involvement": "Community involvement",
            "reason": "Why do you need a travel grant?",
        }

    def __init__(self, *args: object, conference: Conference | None = None, **kwargs: object) -> None:
        """Set required fields, placeholders, and dynamic day choices."""
        super().__init__(*args, **kwargs)
        self.fields["experience_level"].required = True
        self.fields["occupation"].required = True
        self.fields["involvement"].required = True

        self.fields["travel_from"].widget.attrs["placeholder"] = "City, State/Country"

        # Build day choices from conference sections (e.g. Tutorials, Talks, Sprints)
        if conference and conference.start_date and conference.end_date:
            day_choices = self._build_day_choices(conference)
            self.fields["days_attending"].choices = day_choices

        # Pre-populate days_attending checkboxes from comma-separated model value
        if self.instance and self.instance.pk and self.instance.days_attending:
            self.initial["days_attending"] = [d.strip() for d in self.instance.days_attending.split(",") if d.strip()]

    def clean_days_attending(self) -> str:
        """Serialize checkbox selections to comma-separated string for storage."""
        values = self.cleaned_data.get("days_attending", [])
        return ",".join(values)

    def clean_requested_amount(self) -> Decimal:
        """Validate that the requested amount is positive."""
        amount = self.cleaned_data["requested_amount"]
        if amount is not None and amount <= 0:
            msg = "Requested amount must be greater than zero."
            raise forms.ValidationError(msg)
        return amount

    def clean(self) -> dict[str, object]:
        """Cross-field validation matching PyCon's patterns."""
        cleaned = super().clean()

        request_type = cleaned.get("request_type")
        amount = cleaned.get("requested_amount", Decimal(0))

        if request_type == TravelGrant.RequestType.TICKET_AND_GRANT:
            if amount is not None and amount < 1:
                self.add_error(
                    "requested_amount",
                    "You must specify an amount when requesting a travel grant. "
                    'If you only need a ticket, select "In-Person Ticket Only".',
                )
            max_amount = get_config().max_grant_amount
            if amount is not None and amount > max_amount:
                self.add_error(
                    "requested_amount",
                    f"Total requested amount must be less than ${max_amount:,} USD.",
                )

            airfare_amount = cleaned.get("travel_plans_airfare_amount", Decimal(0))
            airfare_desc = cleaned.get("travel_plans_airfare_description", "")
            if airfare_amount and not airfare_desc:
                self.add_error(
                    "travel_plans_airfare_description",
                    "Please describe your airfare plans when requesting airfare funds.",
                )

            lodging_amount = cleaned.get("travel_plans_lodging_amount", Decimal(0))
            lodging_desc = cleaned.get("travel_plans_lodging_description", "")
            if lodging_amount and not lodging_desc:
                self.add_error(
                    "travel_plans_lodging_description",
                    "Please describe your lodging plans when requesting lodging funds.",
                )

        return cleaned

    @staticmethod
    def _build_day_choices(conference: Conference) -> list[tuple[str, str]]:
        """Build labeled day choices from conference sections.

        Uses sections (Tutorials, Talks, Sprints, etc.) to label each day.
        Falls back to generic "Day N" labels for days not covered by any section.
        """
        sections = list(Section.objects.filter(conference=conference).order_by("order", "start_date"))

        # Map each date to its section
        date_section: dict[datetime.date, tuple[str, int]] = {}
        for section in sections:
            day_num = 1
            current = section.start_date
            while current <= section.end_date:
                if current not in date_section:
                    date_section[current] = (str(section.name), day_num)
                day_num += 1
                current += datetime.timedelta(days=1)

        day_choices: list[tuple[str, str]] = []
        current = conference.start_date
        generic_num = 1
        while current <= conference.end_date:
            date_str = current.strftime("%A, %B %-d")
            if current in date_section:
                section_name, section_day = date_section[current]
                label = f"{section_name} Day {section_day} — {date_str}"
            else:
                label = f"Day {generic_num} — {date_str}"
            day_choices.append((current.isoformat(), label))
            current += datetime.timedelta(days=1)
            generic_num += 1
        return day_choices


class TravelGrantMessageForm(forms.ModelForm):
    """Form for applicants to send a message on their grant."""

    class Meta:
        model = TravelGrantMessage
        fields = ["message"]
        widgets = {
            "message": forms.Textarea(attrs={"rows": 3, "placeholder": "Write a message..."}),
        }


class ReceiptForm(forms.ModelForm):
    """Form for uploading an expense receipt."""

    class Meta:
        model = Receipt
        fields = ["receipt_type", "date", "amount", "description", "receipt_file"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "description": forms.TextInput(attrs={"placeholder": "Brief description of expense"}),
        }

    def clean_receipt_file(self) -> object:
        """Enforce a 10 MB file size limit."""
        f = self.cleaned_data.get("receipt_file")
        if f and hasattr(f, "size") and f.size > 10 * 1024 * 1024:
            msg = "File size must be under 10 MB."
            raise forms.ValidationError(msg)
        return f


class PaymentInfoForm(forms.ModelForm):
    """Form for submitting payment details for reimbursement."""

    class Meta:
        model = PaymentInfo
        fields = [
            "payment_method",
            "legal_name",
            "address_street",
            "address_city",
            "address_state",
            "address_zip",
            "address_country",
            "paypal_email",
            "zelle_email",
            "wise_email",
            "bank_name",
            "bank_account_number",
            "bank_routing_number",
            "bank_holder_name",
            "bank_holder_address",
            "bank_address",
            "bank_additional",
        ]
        widgets = {
            "bank_holder_address": forms.Textarea(attrs={"rows": 2}),
            "bank_address": forms.Textarea(attrs={"rows": 2}),
            "bank_additional": forms.Textarea(attrs={"rows": 2, "placeholder": "Sort code, IBAN, SWIFT/BIC, etc."}),
        }

    def clean(self) -> dict[str, object]:
        """Validate that method-specific fields are provided."""
        cleaned = super().clean()
        method = cleaned.get("payment_method")
        if method == PaymentInfo.PaymentMethod.PAYPAL and not cleaned.get("paypal_email"):
            self.add_error("paypal_email", "PayPal email is required for PayPal payments.")
        elif method == PaymentInfo.PaymentMethod.ZELLE and not cleaned.get("zelle_email"):
            self.add_error("zelle_email", "Zelle email is required for Zelle payments.")
        elif method == PaymentInfo.PaymentMethod.WISE and not cleaned.get("wise_email"):
            self.add_error("wise_email", "Wise email is required for Wise payments.")
        elif method in (PaymentInfo.PaymentMethod.ACH, PaymentInfo.PaymentMethod.WIRE):
            if not cleaned.get("bank_name"):
                self.add_error("bank_name", "Bank name is required for bank transfers.")
            if not cleaned.get("bank_account_number"):
                self.add_error("bank_account_number", "Account number is required for bank transfers.")
            if not cleaned.get("bank_routing_number"):
                self.add_error("bank_routing_number", "Routing number is required for bank transfers.")
        return cleaned
