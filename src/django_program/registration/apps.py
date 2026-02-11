"""Django app configuration for the registration app."""

from django.apps import AppConfig


class DjangoProgramRegistrationConfig(AppConfig):
    """Configuration for the registration app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "django_program.registration"
    label = "program_registration"
    verbose_name = "Registration"
