"""Django app configuration for the conference management app."""

from django.apps import AppConfig


class DjangoProgramManageConfig(AppConfig):
    """Configuration for the conference management dashboard app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "django_program.manage"
    label = "program_manage"
    verbose_name = "Conference Management"
