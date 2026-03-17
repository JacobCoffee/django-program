"""Django app configuration for the registration app."""

from django.apps import AppConfig


class DjangoProgramRegistrationConfig(AppConfig):
    """Configuration for the registration app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "django_program.registration"
    label = "program_registration"
    verbose_name = "Registration"

    def ready(self) -> None:
        """Connect signal handlers."""
        from django_program.registration.signal_handlers import create_attendee_on_order_paid  # noqa: PLC0415
        from django_program.registration.signals import order_paid  # noqa: PLC0415

        order_paid.connect(
            create_attendee_on_order_paid,
            dispatch_uid="registration.create_attendee_on_order_paid",
        )
