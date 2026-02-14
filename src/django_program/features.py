"""Feature toggle utilities for django-program.

Provides functions to check whether specific features are enabled
in the current configuration, and a mixin for views that require
specific features.
"""

from django.http import Http404, HttpRequest, HttpResponse

from django_program.settings import get_config


def is_feature_enabled(feature: str) -> bool:
    """Check if a feature is enabled.

    Args:
        feature: Feature name (e.g., ``"registration"``, ``"sponsors"``,
            ``"public_ui"``).

    Returns:
        ``True`` if the feature is enabled, ``False`` otherwise.

    Raises:
        ValueError: If the feature name is not recognized.
    """
    config = get_config().features
    if not config.all_ui_enabled and feature in ("public_ui", "manage_ui"):
        return False
    attr = f"{feature}_enabled"
    if not hasattr(config, attr):
        msg = f"Unknown feature: {feature!r}"
        raise ValueError(msg)
    return getattr(config, attr)


def require_feature(feature: str) -> None:
    """Raise :class:`~django.http.Http404` if a feature is disabled.

    Args:
        feature: Feature name to check.

    Raises:
        Http404: If the feature is disabled.
    """
    if not is_feature_enabled(feature):
        raise Http404(f"Feature {feature!r} is not enabled")


class FeatureRequiredMixin:
    """View mixin that returns 404 when a required feature is disabled.

    Set ``required_feature`` on the view class to the feature name.

    Example::

        class TicketListView(FeatureRequiredMixin, ListView):
            required_feature = "registration"
    """

    required_feature: str = ""

    def dispatch(self, request: HttpRequest, *args: str, **kwargs: str) -> HttpResponse:
        """Check the feature toggle before dispatching the view."""
        if self.required_feature:
            require_feature(self.required_feature)
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]
