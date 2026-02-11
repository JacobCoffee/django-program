"""Django app configuration for the conference app."""

from django.apps import AppConfig


class DjangoProgramConferenceConfig(AppConfig):
    """Configuration for the conference app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "django_program.conference"
    label = "program_conference"
    verbose_name = "Conference"
