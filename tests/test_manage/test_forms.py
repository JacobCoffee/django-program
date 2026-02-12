"""Tests for management dashboard forms."""

from django_program.manage.forms import ImportFromPretalxForm


class TestImportFromPretalxForm:
    """Form behavior for Pretalx import."""

    def test_api_token_widget_uses_anti_autofill_attributes(self):
        form = ImportFromPretalxForm()
        widget_attrs = form.fields["api_token"].widget.attrs

        assert widget_attrs["autocomplete"] == "new-password"
        assert widget_attrs["autocapitalize"] == "none"
        assert widget_attrs["spellcheck"] == "false"
        assert widget_attrs["data-lpignore"] == "true"
