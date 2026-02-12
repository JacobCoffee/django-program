"""Forms for the programs app."""

from django import forms

from django_program.programs.models import TravelGrant


class TravelGrantApplicationForm(forms.ModelForm):
    """Public-facing form for applying for a travel grant.

    Validates that the requested amount is positive and that required
    text fields are non-empty.  The ``conference`` and ``user`` fields
    are set by the view, not the form.
    """

    class Meta:
        model = TravelGrant
        fields = ["requested_amount", "travel_from", "reason"]

    def clean_requested_amount(self) -> object:
        """Validate that the requested amount is positive."""
        amount = self.cleaned_data["requested_amount"]
        if amount is not None and amount <= 0:
            msg = "Requested amount must be greater than zero."
            raise forms.ValidationError(msg)
        return amount
