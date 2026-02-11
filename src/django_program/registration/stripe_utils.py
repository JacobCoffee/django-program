"""Currency conversion helpers for Stripe API integration and key obfuscation for logging.

Stripe represents monetary amounts as integers in the smallest currency unit (e.g. cents
for USD). Most currencies are "normal-decimal" where 1 unit = 100 smallest units, but
a subset of currencies are "zero-decimal" where the integer amount *is* the unit amount.

This module provides bidirectional conversion between :class:`~decimal.Decimal` values
used in Django models and the integer representation expected by the Stripe API, as well
as a helper to safely obfuscate API keys for log output.
"""

from decimal import Decimal

_OBFUSCATE_VISIBLE_CHARS = 4

ZERO_DECIMAL_CURRENCIES: frozenset[str] = frozenset(
    {
        "BIF",
        "CLP",
        "DJF",
        "GNF",
        "JPY",
        "KMF",
        "KRW",
        "MGA",
        "PYG",
        "RWF",
        "UGX",
        "VND",
        "VUV",
        "XAF",
        "XOF",
        "XPF",
    }
)


def convert_amount_for_api(amount: Decimal, currency: str) -> int:
    """Convert a Decimal amount to the integer representation expected by the Stripe API.

    For most currencies the smallest unit is 1/100 of the standard unit (e.g. cents for
    USD), so ``Decimal("10.00")`` becomes ``1000``.  Zero-decimal currencies such as JPY
    are returned as ``int(amount)`` directly because one unit already *is* the smallest
    unit.

    Args:
        amount: The monetary amount as a :class:`~decimal.Decimal`.
        currency: An ISO 4217 currency code (case-insensitive).

    Returns:
        The amount as an integer in the smallest currency unit suitable for Stripe.
    """
    if currency.upper() in ZERO_DECIMAL_CURRENCIES:
        return int(amount)
    return int(amount * 100)


def convert_amount_for_db(amount: int, currency: str) -> Decimal:
    """Convert an integer amount from the Stripe API back to a Decimal for database storage.

    This is the inverse of :func:`convert_amount_for_api`.  For normal-decimal currencies
    the integer is divided by 100 (e.g. ``1000`` becomes ``Decimal("10.00")``).  For
    zero-decimal currencies the integer is returned as-is wrapped in a Decimal.

    Args:
        amount: The integer amount in the smallest currency unit as returned by Stripe.
        currency: An ISO 4217 currency code (case-insensitive).

    Returns:
        The amount as a :class:`~decimal.Decimal` suitable for a Django ``DecimalField``.
    """
    if currency.upper() in ZERO_DECIMAL_CURRENCIES:
        return Decimal(str(amount))
    return Decimal(str(amount)) / 100


def obfuscate_key(key: str) -> str:
    """Obfuscate an API key so it can be safely written to logs.

    Returns the last four characters of the key prefixed with ``"****"``.  If the key is
    shorter than four characters the entire value is masked and only ``"****"`` is
    returned.

    Args:
        key: The secret key to obfuscate.

    Returns:
        A partially masked string safe for log output.
    """
    if len(key) < _OBFUSCATE_VISIBLE_CHARS:
        return "****"
    return "****" + key[-_OBFUSCATE_VISIBLE_CHARS:]
