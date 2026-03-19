"""Stripe Terminal POS views for the manage app.

Provides the staff-facing Point of Sale interface for processing in-person
payments via Stripe Terminal hardware readers during on-site registration.
"""

from django.views.generic import TemplateView

from django_program.manage.views import ManagePermissionMixin


class TerminalPOSView(ManagePermissionMixin, TemplateView):
    """Staff-facing Point of Sale interface for Stripe Terminal payments.

    Renders the POS template with conference context. All payment processing,
    reader management, and cart logic is handled client-side via the terminal
    API endpoints and the Stripe Terminal JS SDK.
    """

    template_name = "django_program/manage/terminal_pos.html"
    required_permission = "use_terminal"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Add active navigation state to the template context.

        Args:
            **kwargs: Additional context data.

        Returns:
            Template context with conference and active navigation state.
        """
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "terminal"
        return context
