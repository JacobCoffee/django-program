"""Tests for the feature toggle system."""

import pytest
from django.http import Http404, HttpRequest, HttpResponse
from django.test import override_settings
from django.views import View

from django_program.context_processors import program_features
from django_program.features import FeatureRequiredMixin, is_feature_enabled, require_feature
from django_program.settings import FeaturesConfig, get_config

# ---------------------------------------------------------------------------
# FeaturesConfig defaults
# ---------------------------------------------------------------------------

ALL_MODULE_FEATURES = (
    "registration",
    "sponsors",
    "travel_grants",
    "programs",
    "pretalx_sync",
)

ALL_UI_FEATURES = (
    "public_ui",
    "manage_ui",
    "all_ui",
)

ALL_FEATURES = (*ALL_MODULE_FEATURES, *ALL_UI_FEATURES)


class TestFeaturesConfigDefaults:
    """All features are enabled by default."""

    def test_all_features_enabled_by_default(self) -> None:
        config = get_config().features
        for feature in ALL_FEATURES:
            assert getattr(config, f"{feature}_enabled") is True

    def test_features_config_is_frozen(self) -> None:
        config = get_config().features
        with pytest.raises(AttributeError):
            config.registration_enabled = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# is_feature_enabled
# ---------------------------------------------------------------------------


class TestIsFeatureEnabled:
    """Tests for the ``is_feature_enabled`` helper."""

    @pytest.mark.parametrize("feature", ALL_FEATURES)
    def test_returns_true_by_default(self, feature: str) -> None:
        assert is_feature_enabled(feature) is True

    @pytest.mark.parametrize("feature", ALL_MODULE_FEATURES)
    def test_returns_false_when_disabled(self, feature: str) -> None:
        with override_settings(
            DJANGO_PROGRAM={"features": {f"{feature}_enabled": False}},
        ):
            assert is_feature_enabled(feature) is False

    def test_unknown_feature_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown feature"):
            is_feature_enabled("nonexistent_module")

    def test_all_ui_disabled_overrides_public_ui(self) -> None:
        with override_settings(
            DJANGO_PROGRAM={"features": {"all_ui_enabled": False}},
        ):
            assert is_feature_enabled("public_ui") is False

    def test_all_ui_disabled_overrides_manage_ui(self) -> None:
        with override_settings(
            DJANGO_PROGRAM={"features": {"all_ui_enabled": False}},
        ):
            assert is_feature_enabled("manage_ui") is False

    def test_all_ui_disabled_does_not_affect_module_features(self) -> None:
        with override_settings(
            DJANGO_PROGRAM={"features": {"all_ui_enabled": False}},
        ):
            assert is_feature_enabled("registration") is True
            assert is_feature_enabled("sponsors") is True

    def test_public_ui_disabled_independently(self) -> None:
        with override_settings(
            DJANGO_PROGRAM={"features": {"public_ui_enabled": False}},
        ):
            assert is_feature_enabled("public_ui") is False
            assert is_feature_enabled("manage_ui") is True


# ---------------------------------------------------------------------------
# require_feature
# ---------------------------------------------------------------------------


class TestRequireFeature:
    """Tests for the ``require_feature`` helper."""

    def test_does_nothing_when_enabled(self) -> None:
        require_feature("registration")

    def test_raises_http404_when_disabled(self) -> None:
        with override_settings(
            DJANGO_PROGRAM={"features": {"registration_enabled": False}},
        ):
            with pytest.raises(Http404, match="registration"):
                require_feature("registration")

    def test_raises_value_error_for_unknown_feature(self) -> None:
        with pytest.raises(ValueError, match="Unknown feature"):
            require_feature("bogus")


# ---------------------------------------------------------------------------
# FeatureRequiredMixin
# ---------------------------------------------------------------------------


class _StubView(FeatureRequiredMixin, View):
    """Minimal view for testing the mixin."""

    required_feature = "registration"

    def get(self, request: HttpRequest) -> HttpResponse:
        return HttpResponse("OK")


class _NoFeatureView(FeatureRequiredMixin, View):
    """View with no required feature set."""

    def get(self, request: HttpRequest) -> HttpResponse:
        return HttpResponse("OK")


class TestFeatureRequiredMixin:
    """Tests for ``FeatureRequiredMixin``."""

    def _make_request(self) -> HttpRequest:
        request = HttpRequest()
        request.method = "GET"
        return request

    def test_dispatches_when_feature_enabled(self) -> None:
        view = _StubView.as_view()
        response = view(self._make_request())
        assert response.status_code == 200

    def test_returns_404_when_feature_disabled(self) -> None:
        with override_settings(
            DJANGO_PROGRAM={"features": {"registration_enabled": False}},
        ):
            view = _StubView.as_view()
            with pytest.raises(Http404):
                view(self._make_request())

    def test_dispatches_when_no_required_feature_set(self) -> None:
        view = _NoFeatureView.as_view()
        response = view(self._make_request())
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Context processor
# ---------------------------------------------------------------------------


class TestProgramFeaturesContextProcessor:
    """Tests for the ``program_features`` context processor."""

    def test_returns_features_config(self) -> None:
        request = HttpRequest()
        context = program_features(request)
        assert "program_features" in context
        assert isinstance(context["program_features"], FeaturesConfig)

    def test_reflects_current_settings(self) -> None:
        with override_settings(
            DJANGO_PROGRAM={"features": {"sponsors_enabled": False}},
        ):
            request = HttpRequest()
            context = program_features(request)
            assert context["program_features"].sponsors_enabled is False
            assert context["program_features"].registration_enabled is True


# ---------------------------------------------------------------------------
# Settings integration (get_config parsing)
# ---------------------------------------------------------------------------


class TestFeaturesSettingsIntegration:
    """Tests for features parsing inside ``get_config``."""

    def test_features_parsed_from_settings(self) -> None:
        with override_settings(
            DJANGO_PROGRAM={"features": {"registration_enabled": False}},
        ):
            config = get_config()
            assert config.features.registration_enabled is False
            assert config.features.sponsors_enabled is True

    def test_features_defaults_when_omitted(self) -> None:
        with override_settings(DJANGO_PROGRAM={}):
            config = get_config()
            assert config.features == FeaturesConfig()

    def test_features_rejects_non_mapping(self) -> None:
        with override_settings(DJANGO_PROGRAM={"features": ["bad"]}):
            with pytest.raises(TypeError, match=r"DJANGO_PROGRAM\['features'\] must be a mapping"):
                get_config()

    def test_features_rejects_unknown_field(self) -> None:
        with override_settings(
            DJANGO_PROGRAM={"features": {"unknown_toggle": True}},
        ):
            with pytest.raises(TypeError):
                get_config()
