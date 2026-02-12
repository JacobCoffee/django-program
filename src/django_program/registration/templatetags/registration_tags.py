"""Template tags and filters for the registration app."""

from decimal import Decimal
from typing import TYPE_CHECKING

from django import template
from django.utils import timezone

from django_program.registration.stripe_utils import ZERO_DECIMAL_CURRENCIES

if TYPE_CHECKING:
    from django_program.registration.models import Cart, TicketType

register = template.Library()


@register.simple_tag
def cart_total(cart: Cart) -> Decimal:
    """Calculate the total price for all items in a cart.

    Sums the ``line_total`` of every :class:`~django_program.registration.models.CartItem`
    attached to the cart.

    Usage in templates::

        {% load registration_tags %}
        {% cart_total cart as total %}
        <p>Total: {{ total }}</p>

    Args:
        cart: A :class:`~django_program.registration.models.Cart` instance.

    Returns:
        The sum of all cart item line totals as a :class:`~decimal.Decimal`.
    """
    total = Decimal("0.00")
    for item in cart.items.all():
        total += item.line_total
    return total


@register.filter
def format_currency(amount: Decimal | None, currency: str = "USD") -> str:
    r"""Format a decimal amount as a human-readable currency string.

    Handles ``None`` gracefully by treating it as zero.  Zero-decimal currencies
    (e.g. JPY, KRW) are rendered without decimal places.

    Usage in templates::

        {% load registration_tags %}
        {{ amount|format_currency }}
        {{ amount|format_currency:"JPY" }}

    Args:
        amount: The monetary amount, or ``None``.
        currency: An ISO 4217 currency code (default ``"USD"``).

    Returns:
        A formatted string such as ``"$10.00"`` or ``"\u00a51000"``.
    """
    if amount is None:
        amount = Decimal("0.00")

    currency_upper = currency.upper()

    symbols: dict[str, str] = {
        "USD": "$",
        "EUR": "\u20ac",
        "GBP": "\u00a3",
        "JPY": "\u00a5",
        "KRW": "\u20a9",
        "CAD": "CA$",
        "AUD": "A$",
    }
    symbol = symbols.get(currency_upper, f"{currency_upper} ")

    if currency_upper in ZERO_DECIMAL_CURRENCIES:
        return f"{symbol}{int(amount)}"

    return f"{symbol}{amount:.2f}"


@register.simple_tag
def ticket_availability(ticket_type: TicketType) -> str:
    """Return a human-readable availability status for a ticket type.

    The logic considers the ticket's active state, sale window, and remaining
    inventory to produce one of the following labels:

    * ``"Sold Out"`` -- active and within window but no remaining inventory.
    * ``"Coming Soon"`` -- active but the sale window has not opened yet.
    * ``"Ended"`` -- active but the sale window has closed.
    * ``"X remaining"`` -- available with a limited quantity remaining.
    * ``"Available"`` -- available with unlimited quantity.

    Usage in templates::

        {% load registration_tags %}
        {% ticket_availability ticket_type as status %}
        <span class="badge">{{ status }}</span>

    Args:
        ticket_type: A :class:`~django_program.registration.models.TicketType` instance.

    Returns:
        A status string describing the ticket's current availability.
    """
    if not ticket_type.is_active:
        return "Unavailable"

    now = timezone.now()

    if ticket_type.available_from and now < ticket_type.available_from:
        return "Coming Soon"

    if ticket_type.available_until and now > ticket_type.available_until:
        return "Ended"

    remaining = ticket_type.remaining_quantity
    if remaining is not None:
        if remaining <= 0:
            return "Sold Out"
        return f"{remaining} remaining"

    return "Available"
