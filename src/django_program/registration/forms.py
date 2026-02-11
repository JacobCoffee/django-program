"""Forms for the registration app."""

from decimal import Decimal

from django import forms


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
