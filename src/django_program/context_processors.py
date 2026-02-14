"""Django context processors for django-program."""

from typing import TYPE_CHECKING

from django_program.settings import FeaturesConfig, get_config

if TYPE_CHECKING:
    from django.http import HttpRequest


def program_features(request: HttpRequest) -> dict[str, FeaturesConfig]:  # noqa: ARG001
    """Expose feature toggle flags to templates.

    Add ``"django_program.context_processors.program_features"`` to the
    ``context_processors`` list in your ``TEMPLATES`` setting.

    Usage in templates::

        {% if program_features.registration_enabled %}
            <a href="{% url 'registration:ticket-list' %}">Registration</a>
        {% endif %}
    """
    return {"program_features": get_config().features}
