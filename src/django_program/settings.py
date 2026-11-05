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

    base_url: str = "https://pretalx.com"
    token: str | None = None
    schedule_delete_guard_enabled: bool = True
    schedule_delete_guard_min_existing_slots: int = 5
    schedule_delete_guard_max_fraction_removed: float = 0.4


@dataclass(frozen=True, slots=True)
class PSFSponsorConfig:
    """PSF sponsorship API configuration for PyCon US conferences."""

    api_url: str = "https://www.python.org/api/v2"
    token: str | None = None
    auth_scheme: str = "Token"
    publisher: str = "pycon"
    flight: str = "sponsors"


@dataclass(frozen=True, slots=True)
class FeaturesConfig:
    """Feature toggles for enabling/disabling django-program modules and UIs.

    Module toggles control backend functionality (registration, sponsors, etc.)
    while UI toggles control the public-facing and management interfaces.
    The ``all_ui_enabled`` flag acts as a master switch for all UI toggles.

    All features are enabled by default. Set to ``False`` in
    ``DJANGO_PROGRAM['features']`` to disable.
    """

    registration_enabled: bool = True
    sponsors_enabled: bool = True
    travel_grants_enabled: bool = True
    programs_enabled: bool = True
    pretalx_sync_enabled: bool = True
    visa_letters_enabled: bool = True

    public_ui_enabled: bool = True
    manage_ui_enabled: bool = True
    all_ui_enabled: bool = True


@dataclass(frozen=True, slots=True)
class ManageConfig:
    """Management dashboard shell configuration.

    Lets a host project reuse the manage UI (sidebar, top bar, palette,
    attention panel) for its own staff pages and trim the built-in modules.

    Attributes:
        title: Top-bar title text.
        home_url: URL name or path the top-bar title links to. Empty means
            the conference list (or the single conference's dashboard).
        conference: Conference slug for single-conference sites. When set,
            the conference list redirects to that conference's dashboard and
            host pages without a ``conference`` in context still get the
            built-in conference nav.
        logout_url: URL name or path for the top-bar "Log out" link.
        public_schedule_link: Show the "View Public Schedule" top-bar link.
        builtin_nav: ``True`` keeps every built-in nav entry, ``False`` drops
            them all. A list keeps only the listed section or item keys.
        hide_nav: Section or item keys to remove (applied after ``builtin_nav``).
        nav: Dotted paths to callables ``(registry: NavRegistry) -> None``
            that add host sections and items.
        attention: Dotted paths to callables
            ``(request, conference) -> Iterable[AttentionItem]``.
        stylesheets: Extra static stylesheet paths loaded after ``manage.css``.
        scripts: Extra static script paths loaded after ``manage.js``.
        palette: Enable the Cmd/Ctrl-K jump palette.
    """

    title: str = "Conference Management"
    home_url: str = ""
    conference: str = ""
    logout_url: str = "admin:logout"
    public_schedule_link: bool = True
    builtin_nav: bool | tuple[str, ...] = True
    hide_nav: tuple[str, ...] = ()
    nav: tuple[str, ...] = ()
    attention: tuple[str, ...] = ("django_program.manage.attention_builtin.builtin_attention",)
    stylesheets: tuple[str, ...] = ()
    scripts: tuple[str, ...] = ()
    palette: bool = True


@dataclass(frozen=True, slots=True)
class ProgramConfig:
    """Top-level django-program configuration."""

    stripe: StripeConfig = field(default_factory=StripeConfig)
    pretalx: PretalxConfig = field(default_factory=PretalxConfig)
    psf_sponsors: PSFSponsorConfig = field(default_factory=PSFSponsorConfig)
    features: FeaturesConfig = field(default_factory=FeaturesConfig)
    manage: ManageConfig = field(default_factory=ManageConfig)
    cart_expiry_minutes: int = 30
    pending_order_expiry_minutes: int = 15
    order_reference_prefix: str = "ORD"
    currency: str = "USD"
    currency_symbol: str = "$"
    max_grant_amount: int = 3000
    attendee_profile_model: str = ""


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
    psf_sponsors_data = raw_data.pop("psf_sponsors", {})
    features_data = raw_data.pop("features", {})
    manage_data = raw_data.pop("manage", {})
    if not isinstance(stripe_data, Mapping):
        msg = "DJANGO_PROGRAM['stripe'] must be a mapping (dict-like object)"
        raise TypeError(msg)
    if not isinstance(pretalx_data, Mapping):
        msg = "DJANGO_PROGRAM['pretalx'] must be a mapping (dict-like object)"
        raise TypeError(msg)
    if not isinstance(psf_sponsors_data, Mapping):
        msg = "DJANGO_PROGRAM['psf_sponsors'] must be a mapping (dict-like object)"
        raise TypeError(msg)
    if not isinstance(features_data, Mapping):
        msg = "DJANGO_PROGRAM['features'] must be a mapping (dict-like object)"
        raise TypeError(msg)
    if not isinstance(manage_data, Mapping):
        msg = "DJANGO_PROGRAM['manage'] must be a mapping (dict-like object)"
        raise TypeError(msg)

    config = ProgramConfig(
        stripe=StripeConfig(**dict(stripe_data)),
        pretalx=PretalxConfig(**dict(pretalx_data)),
        psf_sponsors=PSFSponsorConfig(**dict(psf_sponsors_data)),
        features=FeaturesConfig(**dict(features_data)),
        manage=_build_manage_config(manage_data),
        **raw_data,
    )
    _validate_program_config(config)
    return config


_MANAGE_SEQUENCE_KEYS = ("hide_nav", "nav", "attention", "stylesheets", "scripts")


def _as_str_tuple(key: str, value: object) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        msg = f"DJANGO_PROGRAM['manage']['{key}'] must be a list of strings"
        raise TypeError(msg)
    items = tuple(item for item in value if isinstance(item, str) and item)
    if len(items) != len(value):
        msg = f"DJANGO_PROGRAM['manage']['{key}'] must contain only non-empty strings"
        raise TypeError(msg)
    return items


def _build_manage_config(manage_data: Mapping[str, object]) -> ManageConfig:
    data = dict(manage_data)
    for key in _MANAGE_SEQUENCE_KEYS:
        if key in data:
            data[key] = _as_str_tuple(key, data[key])
    builtin_nav = data.get("builtin_nav", True)
    if not isinstance(builtin_nav, bool):
        data["builtin_nav"] = _as_str_tuple("builtin_nav", builtin_nav)
    for key in ("title", "home_url", "conference", "logout_url"):
        if key in data and not isinstance(data[key], str):
            msg = f"DJANGO_PROGRAM['manage']['{key}'] must be a string"
            raise TypeError(msg)
    for key in ("public_schedule_link", "palette"):
        if key in data and not isinstance(data[key], bool):
            msg = f"DJANGO_PROGRAM['manage']['{key}'] must be a boolean"
            raise TypeError(msg)
    return ManageConfig(**data)


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
    if not isinstance(config.pretalx.schedule_delete_guard_enabled, bool):
        msg = "DJANGO_PROGRAM['pretalx']['schedule_delete_guard_enabled'] must be a boolean"
        raise TypeError(msg)
    if (
        not isinstance(config.pretalx.schedule_delete_guard_min_existing_slots, int)
        or config.pretalx.schedule_delete_guard_min_existing_slots < 0
    ):
        msg = "DJANGO_PROGRAM['pretalx']['schedule_delete_guard_min_existing_slots'] must be a non-negative integer"
        raise ValueError(msg)
    threshold = config.pretalx.schedule_delete_guard_max_fraction_removed
    if not isinstance(threshold, (int, float)) or not 0 <= float(threshold) <= 1:
        msg = "DJANGO_PROGRAM['pretalx']['schedule_delete_guard_max_fraction_removed'] must be between 0 and 1"
        raise ValueError(msg)


def _clear_config_cache(*, setting: str, **kwargs: object) -> None:  # noqa: ARG001
    """Clear the cached config when Django settings change during tests."""
    if setting == "DJANGO_PROGRAM":
        get_config.cache_clear()


setting_changed.connect(_clear_config_cache, dispatch_uid="django_program.settings.clear_config_cache")


def get_attendee_profile_model() -> type | None:
    """Return the custom attendee profile model class, or None if not configured.

    Reads ``attendee_profile_model`` from the ``DJANGO_PROGRAM`` configuration.
    When set to a non-empty app-label string (e.g. ``"myapp.AttendeeProfile"``),
    resolves and returns the model class via ``django.apps.apps.get_model``.

    Returns:
        The model class, or ``None`` if no custom profile model is configured.
    """
    config = get_config()
    if not config.attendee_profile_model:
        return None
    from django.apps import apps  # noqa: PLC0415

    return apps.get_model(config.attendee_profile_model)
