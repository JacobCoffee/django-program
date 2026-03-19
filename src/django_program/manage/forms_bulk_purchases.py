"""Forms for bulk purchase management in the organizer dashboard."""

from typing import override

from django import forms

from django_program.sponsors.models import BulkPurchase


class BulkPurchaseCreateForm(forms.ModelForm):
    """Form for organizers to create a bulk purchase deal.

    Product-first layout: what's being sold, how many codes, what discount,
    who gets it (optionally a sponsor), and validity window.
    """

    voucher_type = forms.ChoiceField(
        label="Discount type",
        choices=[
            ("comp", "Complimentary (100% off)"),
            ("percentage", "Percentage discount"),
            ("fixed_amount", "Fixed amount off"),
        ],
        initial="comp",
        help_text="How the discount is applied to each voucher code.",
    )
    discount_value = forms.DecimalField(
        label="Discount amount",
        max_digits=10,
        decimal_places=2,
        initial=0,
        help_text="Percentage (0-100) or fixed dollar amount, depending on the discount type above.",
        widget=forms.NumberInput(attrs={"placeholder": "0.00", "step": "0.01", "min": "0"}),
    )
    max_uses_per_voucher = forms.IntegerField(
        label="Uses per code",
        min_value=1,
        initial=1,
        help_text="How many times each generated code can be redeemed (usually 1).",
        widget=forms.NumberInput(attrs={"min": "1", "placeholder": "1"}),
    )
    valid_from = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"},
            format="%Y-%m-%dT%H:%M",
        ),
        help_text="Start of voucher validity window (leave blank for immediately valid).",
    )
    valid_until = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"},
            format="%Y-%m-%dT%H:%M",
        ),
        help_text="End of voucher validity window (leave blank for no expiry).",
    )

    class Meta:
        model = BulkPurchase
        fields = [
            "product_description",
            "ticket_type",
            "addon",
            "quantity",
            "unit_price",
            "sponsor",
        ]
        labels = {
            "product_description": "Deal name",
            "quantity": "Number of codes",
            "unit_price": "Price per unit",
            "sponsor": "Sponsor",
            "ticket_type": "Ticket type",
            "addon": "Add-on",
        }
        help_texts = {
            "product_description": (
                "A short name for this deal, e.g. 'PyCon 2077 Tutorial Bundle', 'Staff T-Shirt Pack'."
            ),
            "quantity": "How many unique voucher codes to generate.",
            "unit_price": "The price the buyer pays per item (before any voucher discount).",
            "sponsor": "Optionally associate this deal with a sponsor. Leave blank for non-sponsor deals.",
            "ticket_type": "The ticket type these voucher codes apply to.",
            "addon": "The add-on these voucher codes apply to (e.g. tutorials, t-shirts).",
        }
        widgets = {
            "product_description": forms.TextInput(
                attrs={"placeholder": "e.g. Gold Sponsor Comp Tickets"},
            ),
            "quantity": forms.NumberInput(attrs={"min": "1", "placeholder": "10"}),
            "unit_price": forms.NumberInput(attrs={"step": "0.01", "min": "0", "placeholder": "0.00"}),
        }

    def clean(self) -> dict[str, object]:
        """Compute total_amount and pack voucher_config from extra fields."""
        cleaned = super().clean()
        quantity = cleaned.get("quantity")
        unit_price = cleaned.get("unit_price")
        if quantity and unit_price:
            cleaned["total_amount"] = unit_price * quantity
        return cleaned

    @override
    def save(self, commit: bool = True) -> BulkPurchase:
        """Populate computed fields before saving."""
        instance = super().save(commit=False)
        data = self.cleaned_data
        instance.total_amount = data.get("total_amount", instance.unit_price * instance.quantity)
        instance.voucher_config = {
            "voucher_type": data["voucher_type"],
            "discount_value": str(data["discount_value"]),
            "max_uses": data["max_uses_per_voucher"],
            "valid_from": data["valid_from"].isoformat() if data.get("valid_from") else None,
            "valid_until": data["valid_until"].isoformat() if data.get("valid_until") else None,
        }
        if commit:
            instance.save()
        return instance
