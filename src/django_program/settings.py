"""Typed configuration for django-program.

Reads a single ``DJANGO_PROGRAM`` dict from Django settings and exposes it as
composed, frozen dataclasses with sensible defaults.

Usage::

    from django_program.settings import get_config

    config = get_config()
    config.stripe.secret_key
    config.pretalx.base_url
    config.currency
"""

import functools
from collections.abc import Mapping
from dataclasses import dataclass, field

from django.conf import settings
from django.test.signals import setting_changed


@dataclass(frozen=True, slots=True)
class StripeConfig:
    """Stripe payment gateway configuration."""

    secret_key: str | None = None
    publishable_key: str | None = None
    webhook_secret: str | None = None
    api_version: str = "2024-12-18"
    webhook_tolerance: int = 300


@dataclass(frozen=True, slots=True)
class PretalxConfig:
    """Pretalx schedule API configuration."""

    base_url: str = "https://pretalx.com/api"
    token: str | None = None


@dataclass(frozen=True, slots=True)
class ProgramConfig:
    """Top-level django-program configuration."""

    stripe: StripeConfig = field(default_factory=StripeConfig)
    pretalx: PretalxConfig = field(default_factory=PretalxConfig)
    cart_expiry_minutes: int = 30
    pending_order_expiry_minutes: int = 15
    order_reference_prefix: str = "ORD"
    currency: str = "USD"
    currency_symbol: str = "$"


@functools.lru_cache(maxsize=1)
def get_config() -> ProgramConfig:
    """Build and return the program configuration.

    Reads ``settings.DJANGO_PROGRAM`` (a plain dict) and returns a frozen
    :class:`ProgramConfig`.  The result is cached; the cache is cleared
    automatically when Django's ``setting_changed`` signal fires (e.g. inside
    ``override_settings``).
    """
    raw = getattr(settings, "DJANGO_PROGRAM", {})
    if not isinstance(raw, Mapping):
        msg = "DJANGO_PROGRAM must be a mapping (dict-like object)"
        raise TypeError(msg)
    raw_data = dict(raw)

    stripe_data = raw_data.pop("stripe", {})
    pretalx_data = raw_data.pop("pretalx", {})
    if not isinstance(stripe_data, Mapping):
        msg = "DJANGO_PROGRAM['stripe'] must be a mapping (dict-like object)"
        raise TypeError(msg)
    if not isinstance(pretalx_data, Mapping):
        msg = "DJANGO_PROGRAM['pretalx'] must be a mapping (dict-like object)"
        raise TypeError(msg)

    config = ProgramConfig(
        stripe=StripeConfig(**dict(stripe_data)),
        pretalx=PretalxConfig(**dict(pretalx_data)),
        **raw_data,
    )
    _validate_program_config(config)
    return config


def _validate_program_config(config: ProgramConfig) -> None:
    """Validate high-impact configuration values with clear error messages."""
    if not isinstance(config.cart_expiry_minutes, int) or config.cart_expiry_minutes <= 0:
        msg = "DJANGO_PROGRAM['cart_expiry_minutes'] must be a positive integer"
        raise ValueError(msg)
    if not isinstance(config.pending_order_expiry_minutes, int) or config.pending_order_expiry_minutes <= 0:
        msg = "DJANGO_PROGRAM['pending_order_expiry_minutes'] must be a positive integer"
        raise ValueError(msg)
    if not isinstance(config.currency, str) or not config.currency.strip():
        msg = "DJANGO_PROGRAM['currency'] must be a non-empty string"
        raise ValueError(msg)
    if not isinstance(config.currency_symbol, str) or not config.currency_symbol.strip():
        msg = "DJANGO_PROGRAM['currency_symbol'] must be a non-empty string"
        raise ValueError(msg)


def _clear_config_cache(*, setting: str, **kwargs: object) -> None:  # noqa: ARG001
    """Clear the cached config when Django settings change during tests."""
    if setting == "DJANGO_PROGRAM":
        get_config.cache_clear()


setting_changed.connect(_clear_config_cache, dispatch_uid="django_program.settings.clear_config_cache")
