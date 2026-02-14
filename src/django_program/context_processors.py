"""Django context processors for django-program."""

from typing import TYPE_CHECKING

from django_program.features import is_feature_enabled
from django_program.settings import FeaturesConfig, get_config

if TYPE_CHECKING:
    from django.http import HttpRequest


# Feature names that correspond to FeaturesConfig boolean attributes.
_FEATURE_NAMES = (
    "registration",
    "sponsors",
    "travel_grants",
    "programs",
    "pretalx_sync",
    "public_ui",
    "manage_ui",
    "all_ui",
)


def program_features(request: HttpRequest) -> dict[str, FeaturesConfig | dict[str, bool]]:
    """Expose feature toggle flags to templates.

    When the request carries a ``conference`` attribute (set by middleware
    or the view), the context processor resolves per-conference DB
    overrides via :func:`~django_program.features.is_feature_enabled`.
    Otherwise it returns the static ``FeaturesConfig`` from settings.

    Add ``"django_program.context_processors.program_features"`` to the
    ``context_processors`` list in your ``TEMPLATES`` setting.

    Usage in templates::

        {% if program_features.registration_enabled %}
            <a href="{% url 'registration:ticket-list' %}">Registration</a>
        {% endif %}
    """
    conference = getattr(request, "conference", None)

    if conference is not None:
        resolved = {f"{name}_enabled": is_feature_enabled(name, conference=conference) for name in _FEATURE_NAMES}
        return {"program_features": resolved}

    return {"program_features": get_config().features}
