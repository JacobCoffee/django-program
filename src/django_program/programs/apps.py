"""Django app configuration for the programs app."""

from django.apps import AppConfig


class DjangoProgramProgramsConfig(AppConfig):
    """Configuration for the programs app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "django_program.programs"
    label = "program_programs"
    verbose_name = "Programs"
