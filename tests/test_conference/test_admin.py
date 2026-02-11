"""Tests for SecretInput and SecretField admin widgets/fields."""

from django_program.conference.admin import SECRET_PLACEHOLDER, SecretField, SecretInput


class TestSecretInputFormatValue:
    """SecretInput.format_value masks stored secrets with a dot placeholder."""

    def test_returns_placeholder_when_value_exists(self):
        widget = SecretInput()
        assert widget.format_value("sk_live_abc123") == SECRET_PLACEHOLDER

    def test_returns_empty_string_when_value_is_none(self):
        widget = SecretInput()
        assert widget.format_value(None) == ""

    def test_returns_empty_string_when_value_is_empty(self):
        widget = SecretInput()
        assert widget.format_value("") == ""


class TestSecretFieldHasChanged:
    """SecretField.has_changed treats placeholder/blank as unchanged."""

    def test_returns_false_when_data_is_none(self):
        field = SecretField()
        assert field.has_changed("old_secret", None) is False

    def test_returns_false_when_data_is_empty_string(self):
        field = SecretField()
        assert field.has_changed("old_secret", "") is False

    def test_returns_false_when_data_is_placeholder(self):
        field = SecretField()
        assert field.has_changed("old_secret", SECRET_PLACEHOLDER) is False

    def test_returns_true_when_data_is_new_value(self):
        field = SecretField()
        assert field.has_changed("old_secret", "new_secret") is True

    def test_returns_true_when_initial_is_none_and_data_is_new_value(self):
        field = SecretField()
        assert field.has_changed(None, "brand_new_secret") is True


class TestSecretFieldClean:
    """SecretField.clean preserves stored value unless a real edit is submitted."""

    def test_returns_initial_when_value_is_none(self):
        field = SecretField()
        field.initial = "stored_secret"
        assert field.clean(None) == "stored_secret"

    def test_returns_initial_when_value_is_empty_string(self):
        field = SecretField()
        field.initial = "stored_secret"
        assert field.clean("") == "stored_secret"

    def test_returns_initial_when_value_is_placeholder(self):
        field = SecretField()
        field.initial = "stored_secret"
        assert field.clean(SECRET_PLACEHOLDER) == "stored_secret"

    def test_returns_new_value_when_real_input_provided(self):
        field = SecretField()
        field.initial = "stored_secret"
        assert field.clean("new_secret") == "new_secret"

    def test_returns_none_initial_when_value_is_blank_and_no_stored_value(self):
        field = SecretField()
        field.initial = None
        assert field.clean("") is None


class TestSecretFieldDefaults:
    """SecretField configures sensible defaults on construction."""

    def test_not_required_by_default(self):
        field = SecretField()
        assert field.required is False

    def test_autocomplete_off(self):
        field = SecretField()
        assert field.widget.attrs["autocomplete"] == "off"

    def test_uses_secret_input_widget(self):
        field = SecretField()
        assert isinstance(field.widget, SecretInput)
