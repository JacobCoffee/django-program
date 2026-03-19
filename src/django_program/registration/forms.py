"""Forms for the registration app."""

from decimal import Decimal

from django import forms

from django_program.registration.letter import LetterRequest


class CartItemForm(forms.Form):
    """Form for adding an item to the cart.

    Validates that exactly one of ``ticket_type_id`` or ``addon_id`` is
    provided so each cart line references a single purchasable item.
    """

    ticket_type_id = forms.IntegerField(required=False)
    addon_id = forms.IntegerField(required=False)
    quantity = forms.IntegerField(min_value=1, initial=1)

    def clean(self) -> dict:
        """Ensure exactly one of ticket_type_id or addon_id is supplied."""
        cleaned = super().clean()
        ticket = cleaned.get("ticket_type_id")
        addon = cleaned.get("addon_id")

        has_ticket = ticket is not None
        has_addon = addon is not None

        if has_ticket == has_addon:
            raise forms.ValidationError("Provide exactly one of ticket_type_id or addon_id, not both or neither.")

        return cleaned


class VoucherApplyForm(forms.Form):
    """Form for applying a voucher code to the current cart."""

    code = forms.CharField(max_length=100, strip=True)


class CheckoutForm(forms.Form):
    """Billing information collected at checkout."""

    billing_name = forms.CharField(max_length=200)
    billing_email = forms.EmailField()
    billing_company = forms.CharField(max_length=200, required=False)


class RefundForm(forms.Form):
    """Admin form for issuing a full or partial refund on an order."""

    amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )
    reason = forms.CharField(widget=forms.Textarea, required=False)


class LetterRequestForm(forms.ModelForm):
    """Form for attendees to request a visa invitation letter.

    Collects passport details, travel dates, and destination information
    needed to produce a formal letter for embassy submission.
    """

    class Meta:
        model = LetterRequest
        fields = [
            "passport_name",
            "passport_number",
            "nationality",
            "date_of_birth",
            "travel_from",
            "travel_until",
            "destination_address",
            "embassy_name",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "travel_from": forms.DateInput(attrs={"type": "date"}),
            "travel_until": forms.DateInput(attrs={"type": "date"}),
            "destination_address": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self) -> dict:
        """Validate that travel_from is before travel_until."""
        cleaned = super().clean()
        travel_from = cleaned.get("travel_from")
        travel_until = cleaned.get("travel_until")

        if travel_from and travel_until and travel_from >= travel_until:
            raise forms.ValidationError("Travel start date must be before the end date.")

        return cleaned
