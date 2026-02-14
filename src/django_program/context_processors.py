"""Django context processors for django-program."""

from django.http import HttpRequest  # noqa: TC002 -- used in runtime annotation (PEP 649)

from django_program.features import is_feature_enabled

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


def program_features(request: HttpRequest) -> dict[str, dict[str, bool]]:
    """Expose resolved feature toggle flags to templates.

    Each flag is resolved through :func:`~django_program.features.is_feature_enabled`
    so that master-switch overrides (e.g. ``all_ui_enabled``) are applied.
    When the request carries a ``conference`` attribute (set by middleware
    or the view), per-conference DB overrides are included in the resolution.

    Add ``"django_program.context_processors.program_features"`` to the
    ``context_processors`` list in your ``TEMPLATES`` setting.

    Usage in templates::

        {% if program_features.registration_enabled %}
            <a href="{% url 'registration:ticket-list' %}">Registration</a>
        {% endif %}
    """
    conference = getattr(request, "conference", None)
    resolved = {f"{name}_enabled": is_feature_enabled(name, conference=conference) for name in _FEATURE_NAMES}
    return {"program_features": resolved}
