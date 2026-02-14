"""Feature toggle utilities for django-program.

Provides functions to check whether specific features are enabled
in the current configuration, and a mixin for views that require
specific features.

Features can be configured at two levels:

1. **Settings defaults** -- ``DJANGO_PROGRAM["features"]`` in Django settings.
   These require a server restart to change.
2. **Per-conference DB overrides** -- The ``FeatureFlags`` model stores
   nullable booleans. When a value is not ``None`` it takes precedence
   over the settings default.
"""

from typing import TYPE_CHECKING

from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404, HttpRequest, HttpResponse

from django_program.settings import get_config

if TYPE_CHECKING:
    from django_program.conference.models import Conference


def _get_db_flag(conference: Conference, attr: str) -> bool | None:
    """Return the DB override for *attr*, or ``None`` when absent.

    Args:
        conference: The conference instance to look up flags for.
        attr: The attribute name on ``FeatureFlags`` (e.g.
            ``"registration_enabled"``).

    Returns:
        The explicit ``True``/``False`` override, or ``None`` if there
        is no ``FeatureFlags`` row or the field is not set.
    """
    try:
        flags = conference.feature_flags  # type: ignore[union-attr]
    except ObjectDoesNotExist:
        return None
    return getattr(flags, attr, None)


def is_feature_enabled(feature: str, conference: object | None = None) -> bool:
    """Check if a feature is enabled, with optional per-conference DB override.

    Resolution order:

    1. If a *conference* is provided and has a ``FeatureFlags`` row with an
       explicit value for the feature, that value wins.
    2. Otherwise the default from ``DJANGO_PROGRAM["features"]`` is used.
    3. The ``all_ui_enabled`` master switch is checked first for UI
       features (``public_ui``, ``manage_ui``).

    Args:
        feature: Feature name (e.g., ``"registration"``, ``"sponsors"``,
            ``"public_ui"``).
        conference: Optional conference instance. When provided the
            database ``FeatureFlags`` row is consulted for overrides.

    Returns:
        ``True`` if the feature is enabled, ``False`` otherwise.

    Raises:
        ValueError: If the feature name is not recognized.
    """
    config = get_config().features
    attr = f"{feature}_enabled"

    if not hasattr(config, attr):
        msg = f"Unknown feature: {feature!r}"
        raise ValueError(msg)

    default: bool = getattr(config, attr)

    if conference is not None:
        db_all_ui = _get_db_flag(conference, "all_ui_enabled")
        db_value = _get_db_flag(conference, attr)

        # Master UI switch (DB override or settings fallback)
        if feature in ("public_ui", "manage_ui"):
            all_ui = db_all_ui if db_all_ui is not None else config.all_ui_enabled
            if not all_ui:
                return False

        if db_value is not None:
            return db_value

        # The master UI switch was already evaluated above (using DB
        # override when present, settings fallback otherwise). If we
        # reached this point the master switch is on, so just return
        # the settings default for this specific feature.
        return default

    # No conference -- settings only
    if not config.all_ui_enabled and feature in ("public_ui", "manage_ui"):
        return False
    return default


def require_feature(feature: str, conference: object | None = None) -> None:
    """Raise :class:`~django.http.Http404` if a feature is disabled.

    Args:
        feature: Feature name to check.
        conference: Optional conference for per-conference DB override.

    Raises:
        Http404: If the feature is disabled.
    """
    if not is_feature_enabled(feature, conference=conference):
        raise Http404(f"Feature {feature!r} is not enabled")


class FeatureRequiredMixin:
    """View mixin that returns 404 when a required feature is disabled.

    Set ``required_feature`` on the view class to the feature name or a
    tuple of feature names (all must be enabled).  When used alongside
    ``ConferenceMixin`` (placed *before* this mixin in the MRO), the
    already-resolved ``self.conference`` is picked up automatically for
    per-conference DB overrides.

    Example::

        class TicketListView(ConferenceMixin, FeatureRequiredMixin, ListView):
            required_feature = ("registration", "public_ui")
    """

    required_feature: str | tuple[str, ...] = ""

    def get_conference(self) -> object | None:
        """Return the conference for per-conference feature lookups.

        When ``ConferenceMixin`` runs before this mixin it sets
        ``self.conference``; the default implementation returns that
        attribute if present, falling back to ``None``.
        """
        return getattr(self, "conference", None)

    def dispatch(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        """Check the feature toggle(s) before dispatching the view."""
        features = self.required_feature
        if isinstance(features, str):
            features = (features,) if features else ()
        conference = self.get_conference()
        for feature in features:
            require_feature(feature, conference=conference)
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]
