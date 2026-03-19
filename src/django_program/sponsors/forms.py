"""Forms for the sponsor self-service portal."""

from django import forms


class BulkPurchaseRequestForm(forms.Form):
    """Form for sponsors to request a new bulk voucher purchase.

    Captures the desired quantity, ticket type preference, and any
    additional notes for the organizer to review.
    """

    quantity = forms.IntegerField(
        min_value=1,
        max_value=500,
        help_text="Number of voucher codes to request.",
    )
    ticket_type_preference = forms.CharField(
        max_length=300,
        required=False,
        help_text="Preferred ticket type (e.g. 'Corporate', 'Tutorial Only'). Leave blank if no preference.",
    )
    notes = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4}),
        required=False,
        help_text="Additional notes for the conference organizers.",
    )
