"""Signals for the conference app."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from django_program.conference.models import Conference, FeatureFlags


@receiver(post_save, sender=Conference)
def create_feature_flags(
    sender: type[Conference],  # noqa: ARG001
    instance: Conference,
    *,
    created: bool,
    **kwargs: object,  # noqa: ARG001
) -> None:
    """Auto-create a FeatureFlags row when a new Conference is saved."""
    if created:
        FeatureFlags.objects.get_or_create(conference=instance)
