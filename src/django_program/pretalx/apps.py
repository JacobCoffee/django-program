"""Django app configuration for the pretalx integration app."""

from django.apps import AppConfig


class DjangoProgramPretalxConfig(AppConfig):
    """Configuration for the pretalx integration app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "django_program.pretalx"
    label = "program_pretalx"
    verbose_name = "Pretalx Integration"
