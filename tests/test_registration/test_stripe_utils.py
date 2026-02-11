from decimal import Decimal

import pytest

from django_program.registration.stripe_utils import (
    ZERO_DECIMAL_CURRENCIES,
    convert_amount_for_api,
    convert_amount_for_db,
    obfuscate_key,
)

# ---------------------------------------------------------------------------
# ZERO_DECIMAL_CURRENCIES constant
# ---------------------------------------------------------------------------


def test_zero_decimal_currencies_is_frozenset():
    assert isinstance(ZERO_DECIMAL_CURRENCIES, frozenset)


def test_zero_decimal_currencies_contains_expected_codes():
    expected = {
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
    assert ZERO_DECIMAL_CURRENCIES == expected


# ---------------------------------------------------------------------------
# convert_amount_for_api
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        (Decimal("10.00"), "USD", 1000),
        (Decimal("0.50"), "USD", 50),
        (Decimal("99.99"), "EUR", 9999),
        (Decimal("0.01"), "GBP", 1),
        (Decimal("0.00"), "USD", 0),
        (Decimal("1000.00"), "EUR", 100000),
    ],
    ids=["usd-10", "usd-half", "eur-99.99", "gbp-penny", "zero-amount", "eur-large"],
)
def test_convert_amount_for_api_normal_decimal(amount, currency, expected):
    assert convert_amount_for_api(amount, currency) == expected


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        (Decimal(500), "JPY", 500),
        (Decimal(1000), "KRW", 1000),
        (Decimal(0), "JPY", 0),
        (Decimal(1), "VND", 1),
    ],
    ids=["jpy-500", "krw-1000", "jpy-zero", "vnd-1"],
)
def test_convert_amount_for_api_zero_decimal(amount, currency, expected):
    assert convert_amount_for_api(amount, currency) == expected


@pytest.mark.parametrize(
    "currency_pair",
    [("usd", "USD"), ("jpy", "JPY"), ("Eur", "EUR"), ("krw", "KRW")],
    ids=["usd-lower", "jpy-lower", "eur-mixed", "krw-lower"],
)
def test_convert_amount_for_api_case_insensitive(currency_pair):
    lower, upper = currency_pair
    amount = Decimal(100)
    assert convert_amount_for_api(amount, lower) == convert_amount_for_api(amount, upper)


def test_convert_amount_for_api_rejects_fractional_zero_decimal_currency():
    with pytest.raises(ValueError, match="zero-decimal currency"):
        convert_amount_for_api(Decimal("1.9"), "JPY")


def test_convert_amount_for_api_rejects_more_than_two_decimals():
    with pytest.raises(ValueError, match="more than 2 decimal places"):
        convert_amount_for_api(Decimal("10.999"), "USD")


# ---------------------------------------------------------------------------
# convert_amount_for_db
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        (1000, "USD", Decimal(10)),
        (50, "USD", Decimal("0.5")),
        (9999, "EUR", Decimal("99.99")),
        (1, "GBP", Decimal("0.01")),
        (0, "USD", Decimal(0)),
    ],
    ids=["usd-1000", "usd-50", "eur-9999", "gbp-1", "zero-amount"],
)
def test_convert_amount_for_db_normal_decimal(amount, currency, expected):
    assert convert_amount_for_db(amount, currency) == expected


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        (500, "JPY", Decimal(500)),
        (1000, "KRW", Decimal(1000)),
        (0, "JPY", Decimal(0)),
    ],
    ids=["jpy-500", "krw-1000", "jpy-zero"],
)
def test_convert_amount_for_db_zero_decimal(amount, currency, expected):
    assert convert_amount_for_db(amount, currency) == expected


@pytest.mark.parametrize(
    "currency_pair",
    [("usd", "USD"), ("jpy", "JPY")],
    ids=["usd-lower", "jpy-lower"],
)
def test_convert_amount_for_db_case_insensitive(currency_pair):
    lower, upper = currency_pair
    assert convert_amount_for_db(1000, lower) == convert_amount_for_db(1000, upper)


# ---------------------------------------------------------------------------
# Roundtrip: api -> db -> api
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "currency"),
    [
        (Decimal("42.50"), "USD"),
        (Decimal(500), "JPY"),
        (Decimal("0.01"), "EUR"),
        (Decimal(9999), "KRW"),
    ],
    ids=["usd-roundtrip", "jpy-roundtrip", "eur-roundtrip", "krw-roundtrip"],
)
def test_roundtrip_api_then_db(amount, currency):
    api_val = convert_amount_for_api(amount, currency)
    restored = convert_amount_for_db(api_val, currency)
    assert restored == amount


# ---------------------------------------------------------------------------
# obfuscate_key
# ---------------------------------------------------------------------------


def test_obfuscate_key_empty_string():
    assert obfuscate_key("") == "****"


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("a", "****"),
        ("ab", "****"),
        ("abc", "****"),
    ],
    ids=["1-char", "2-char", "3-char"],
)
def test_obfuscate_key_short_keys(key, expected):
    assert obfuscate_key(key) == expected


def test_obfuscate_key_exactly_four_chars():
    assert obfuscate_key("abcd") == "****abcd"


def test_obfuscate_key_long_key():
    assert obfuscate_key("sk_live_abc123xyz") == "****3xyz"


def test_obfuscate_key_preserves_last_four():
    assert obfuscate_key("supersecretkey") == "****tkey"
