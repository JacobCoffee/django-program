"""Django app configuration for the sponsors app."""

from django.apps import AppConfig


class DjangoProgramSponsorsConfig(AppConfig):
    """Configuration for the sponsors app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "django_program.sponsors"
    label = "program_sponsors"
    verbose_name = "Sponsors"

    def ready(self) -> None:
        """Import signal handlers on app startup."""
        import django_program.sponsors.signals  # noqa: F401, PLC0415
