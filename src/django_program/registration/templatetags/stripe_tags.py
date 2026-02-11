"""Template tags for Stripe integration."""

from django import template

from django_program.conference.models import Conference

register = template.Library()


@register.simple_tag
def stripe_public_key(conference: Conference) -> str:
    """Return the Stripe publishable key for a conference.

    Usage in templates::

        {% load stripe_tags %}
        {% stripe_public_key conference as stripe_key %}
        <script>
            const stripe = Stripe('{{ stripe_key }}');
        </script>

    Args:
        conference: A Conference model instance with ``stripe_publishable_key``.

    Returns:
        The publishable key string, or empty string if not configured.
    """
    key = getattr(conference, "stripe_publishable_key", None)
    return key or ""
