"""Forms for voucher bulk operations in the management dashboard."""

from django import forms

from django_program.registration.models import AddOn, TicketType, Voucher


class VoucherBulkGenerateForm(forms.Form):
    """Form for bulk-generating a batch of voucher codes.

    Accepts configuration for the code prefix, quantity, discount type, and
    optional constraints (validity window, applicable ticket types/add-ons).
    """

    prefix = forms.CharField(
        max_length=20,
        help_text="Fixed prefix for generated codes (e.g. SPEAKER-, SPONSOR-).",
    )
    count = forms.IntegerField(
        min_value=1,
        max_value=500,
        help_text="Number of voucher codes to generate (1-500).",
    )
    voucher_type = forms.ChoiceField(
        choices=Voucher.VoucherType.choices,
        help_text="Type of discount each voucher provides.",
    )
    discount_value = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        initial=0,
        help_text="Percentage (0-100) or fixed amount depending on voucher type. Ignored for comp vouchers.",
    )
    applicable_ticket_types = forms.ModelMultipleChoiceField(
        queryset=TicketType.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Restrict vouchers to these ticket types. Leave empty for all.",
    )
    applicable_addons = forms.ModelMultipleChoiceField(
        queryset=AddOn.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Restrict vouchers to these add-ons. Leave empty for all.",
    )
    max_uses = forms.IntegerField(
        min_value=1,
        initial=1,
        help_text="Maximum redemptions per voucher code.",
    )
    valid_from = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"},
            format="%Y-%m-%dT%H:%M",
        ),
        help_text="Optional start of validity window.",
    )
    valid_until = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"},
            format="%Y-%m-%dT%H:%M",
        ),
        help_text="Optional end of validity window.",
    )
    unlocks_hidden_tickets = forms.BooleanField(
        required=False,
        initial=False,
        help_text="When checked, these vouchers reveal ticket types that require a voucher.",
    )
