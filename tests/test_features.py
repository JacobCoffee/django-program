"""Tests for the feature toggle system."""

import pytest
from django.contrib.admin.sites import site as admin_site
from django.db import IntegrityError
from django.http import Http404, HttpRequest, HttpResponse
from django.test import override_settings
from django.views import View

from django_program.conference.models import Conference, FeatureFlags
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
# is_feature_enabled (settings only, no conference)
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
# is_feature_enabled with conference (DB overrides)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestIsFeatureEnabledWithConference:
    """Tests for DB-backed feature flag overrides."""

    @pytest.fixture
    def conference(self):
        return Conference.objects.create(
            name="TestConf",
            slug="testconf",
            start_date="2026-07-01",
            end_date="2026-07-05",
        )

    def test_all_none_fields_use_settings_defaults(self, conference) -> None:
        for feature in ALL_MODULE_FEATURES:
            assert is_feature_enabled(feature, conference=conference) is True

    def test_explicit_false_overrides_settings_true(self, conference) -> None:
        flags = conference.feature_flags
        flags.registration_enabled = False
        flags.save()
        assert is_feature_enabled("registration", conference=conference) is False

    def test_explicit_true_overrides_settings_false(self, conference) -> None:
        with override_settings(
            DJANGO_PROGRAM={"features": {"sponsors_enabled": False}},
        ):
            flags = conference.feature_flags
            flags.sponsors_enabled = True
            flags.save()
            assert is_feature_enabled("sponsors", conference=conference) is True

    @pytest.mark.parametrize("feature", ALL_MODULE_FEATURES)
    def test_none_field_falls_back_to_settings(self, conference, feature) -> None:
        with override_settings(
            DJANGO_PROGRAM={"features": {f"{feature}_enabled": False}},
        ):
            assert is_feature_enabled(feature, conference=conference) is False

    def test_db_all_ui_false_blocks_public_ui(self, conference) -> None:
        flags = conference.feature_flags
        flags.all_ui_enabled = False
        flags.save()
        assert is_feature_enabled("public_ui", conference=conference) is False

    def test_db_all_ui_false_blocks_manage_ui(self, conference) -> None:
        flags = conference.feature_flags
        flags.all_ui_enabled = False
        flags.save()
        assert is_feature_enabled("manage_ui", conference=conference) is False

    def test_db_all_ui_true_overrides_settings_all_ui_false(self, conference) -> None:
        with override_settings(
            DJANGO_PROGRAM={"features": {"all_ui_enabled": False}},
        ):
            flags = conference.feature_flags
            flags.all_ui_enabled = True
            flags.save()
            assert is_feature_enabled("public_ui", conference=conference) is True

    def test_db_public_ui_false_with_all_ui_true(self, conference) -> None:
        flags = conference.feature_flags
        flags.all_ui_enabled = True
        flags.public_ui_enabled = False
        flags.save()
        assert is_feature_enabled("public_ui", conference=conference) is False

    def test_db_all_ui_false_does_not_affect_modules(self, conference) -> None:
        flags = conference.feature_flags
        flags.all_ui_enabled = False
        flags.save()
        assert is_feature_enabled("registration", conference=conference) is True

    def test_settings_all_ui_false_no_db_override_blocks_ui(self, conference) -> None:
        with override_settings(
            DJANGO_PROGRAM={"features": {"all_ui_enabled": False}},
        ):
            assert is_feature_enabled("public_ui", conference=conference) is False

    def test_falls_back_to_settings_when_feature_flags_row_missing(self, conference) -> None:
        FeatureFlags.objects.filter(conference=conference).delete()
        # Refresh to clear cached reverse relation
        conference.refresh_from_db()
        assert is_feature_enabled("registration", conference=conference) is True

    def test_db_override_absent_falls_back_for_ui_feature(self, conference) -> None:
        FeatureFlags.objects.filter(conference=conference).delete()
        conference.refresh_from_db()
        assert is_feature_enabled("public_ui", conference=conference) is True

    def test_unknown_feature_raises_with_conference(self, conference) -> None:
        with pytest.raises(ValueError, match="Unknown feature"):
            is_feature_enabled("bogus", conference=conference)

    def test_backward_compat_without_conference(self) -> None:
        assert is_feature_enabled("registration") is True
        assert is_feature_enabled("registration", conference=None) is True


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


@pytest.mark.django_db
class TestRequireFeatureWithConference:
    """Tests for ``require_feature`` with conference DB overrides."""

    @pytest.fixture
    def conference(self):
        return Conference.objects.create(
            name="TestConf",
            slug="testconf-rf",
            start_date="2026-07-01",
            end_date="2026-07-05",
        )

    def test_does_nothing_when_db_override_true(self, conference) -> None:
        with override_settings(
            DJANGO_PROGRAM={"features": {"registration_enabled": False}},
        ):
            flags = conference.feature_flags
            flags.registration_enabled = True
            flags.save()
            require_feature("registration", conference=conference)

    def test_raises_http404_when_db_override_false(self, conference) -> None:
        flags = conference.feature_flags
        flags.registration_enabled = False
        flags.save()
        with pytest.raises(Http404, match="registration"):
            require_feature("registration", conference=conference)


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


class _MultiFeatureView(FeatureRequiredMixin, View):
    """View requiring multiple features."""

    required_feature = ("registration", "public_ui")

    def get(self, request: HttpRequest) -> HttpResponse:
        return HttpResponse("OK")


class _ConferenceView(FeatureRequiredMixin, View):
    """View that provides a conference via get_conference()."""

    required_feature = "registration"
    _conference = None

    def get_conference(self):
        return self._conference

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

    def test_get_conference_returns_none_by_default(self) -> None:
        mixin = FeatureRequiredMixin()
        assert mixin.get_conference() is None

    def test_get_conference_returns_self_conference_attr(self) -> None:
        mixin = FeatureRequiredMixin()
        sentinel = object()
        mixin.conference = sentinel  # type: ignore[attr-defined]
        assert mixin.get_conference() is sentinel

    def test_multi_feature_dispatches_when_all_enabled(self) -> None:
        view = _MultiFeatureView.as_view()
        response = view(self._make_request())
        assert response.status_code == 200

    def test_multi_feature_returns_404_when_first_disabled(self) -> None:
        with override_settings(
            DJANGO_PROGRAM={"features": {"registration_enabled": False}},
        ):
            view = _MultiFeatureView.as_view()
            with pytest.raises(Http404):
                view(self._make_request())

    def test_multi_feature_returns_404_when_second_disabled(self) -> None:
        with override_settings(
            DJANGO_PROGRAM={"features": {"public_ui_enabled": False}},
        ):
            view = _MultiFeatureView.as_view()
            with pytest.raises(Http404):
                view(self._make_request())

    def test_required_feature_accepts_tuple(self) -> None:
        assert _MultiFeatureView.required_feature == ("registration", "public_ui")


@pytest.mark.django_db
class TestFeatureRequiredMixinWithConference:
    """Tests for ``FeatureRequiredMixin`` with per-conference DB overrides."""

    def _make_request(self) -> HttpRequest:
        request = HttpRequest()
        request.method = "GET"
        return request

    def test_mixin_uses_db_override(self) -> None:
        conference = Conference.objects.create(
            name="TestConf",
            slug="testconf-mixin",
            start_date="2026-07-01",
            end_date="2026-07-05",
        )
        flags = conference.feature_flags
        flags.registration_enabled = False
        flags.save()
        view = _ConferenceView.as_view(_conference=conference)
        with pytest.raises(Http404):
            view(self._make_request())


# ---------------------------------------------------------------------------
# Context processor
# ---------------------------------------------------------------------------


class TestProgramFeaturesContextProcessor:
    """Tests for the ``program_features`` context processor."""

    def test_returns_resolved_dict(self) -> None:
        request = HttpRequest()
        context = program_features(request)
        assert "program_features" in context
        assert isinstance(context["program_features"], dict)
        assert context["program_features"]["registration_enabled"] is True

    def test_reflects_current_settings(self) -> None:
        with override_settings(
            DJANGO_PROGRAM={"features": {"sponsors_enabled": False}},
        ):
            request = HttpRequest()
            context = program_features(request)
            assert context["program_features"]["sponsors_enabled"] is False
            assert context["program_features"]["registration_enabled"] is True

    def test_all_ui_disabled_reflected_in_context(self) -> None:
        with override_settings(
            DJANGO_PROGRAM={"features": {"all_ui_enabled": False}},
        ):
            request = HttpRequest()
            context = program_features(request)
            assert context["program_features"]["public_ui_enabled"] is False
            assert context["program_features"]["manage_ui_enabled"] is False
            assert context["program_features"]["registration_enabled"] is True


@pytest.mark.django_db
class TestProgramFeaturesContextProcessorWithConference:
    """Tests for context processor with per-conference DB overrides."""

    def test_returns_dict_when_conference_present(self) -> None:
        conference = Conference.objects.create(
            name="TestConf",
            slug="testconf-ctx",
            start_date="2026-07-01",
            end_date="2026-07-05",
        )
        flags = conference.feature_flags
        flags.registration_enabled = False
        flags.save()
        request = HttpRequest()
        request.conference = conference  # type: ignore[attr-defined]
        context = program_features(request)
        assert isinstance(context["program_features"], dict)
        assert context["program_features"]["registration_enabled"] is False
        assert context["program_features"]["sponsors_enabled"] is True

    def test_returns_resolved_dict_without_conference(self) -> None:
        request = HttpRequest()
        context = program_features(request)
        assert isinstance(context["program_features"], dict)
        assert context["program_features"]["registration_enabled"] is True


# ---------------------------------------------------------------------------
# FeatureFlags model
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFeatureFlagsModel:
    """Tests for the ``FeatureFlags`` model."""

    @pytest.fixture
    def conference(self):
        return Conference.objects.create(
            name="TestConf",
            slug="testconf-model",
            start_date="2026-07-01",
            end_date="2026-07-05",
        )

    def test_str_representation(self, conference) -> None:
        flags = conference.feature_flags
        assert str(flags) == f"Feature flags for {conference}"

    def test_all_fields_default_to_none(self, conference) -> None:
        flags = conference.feature_flags
        assert flags.registration_enabled is None
        assert flags.sponsors_enabled is None
        assert flags.travel_grants_enabled is None
        assert flags.programs_enabled is None
        assert flags.pretalx_sync_enabled is None
        assert flags.public_ui_enabled is None
        assert flags.manage_ui_enabled is None
        assert flags.all_ui_enabled is None

    def test_one_to_one_constraint(self, conference) -> None:
        assert FeatureFlags.objects.filter(conference=conference).exists()
        with pytest.raises(IntegrityError):
            FeatureFlags.objects.create(conference=conference)

    def test_cascade_delete(self, conference) -> None:
        assert FeatureFlags.objects.filter(conference=conference).exists()
        conference.delete()
        assert FeatureFlags.objects.count() == 0

    def test_updated_at_auto_set(self, conference) -> None:
        flags = conference.feature_flags
        assert flags.updated_at is not None

    def test_reverse_relation(self, conference) -> None:
        flags = FeatureFlags.objects.get(conference=conference)
        assert conference.feature_flags == flags

    def test_verbose_name(self) -> None:
        assert FeatureFlags._meta.verbose_name == "feature flags"
        assert FeatureFlags._meta.verbose_name_plural == "feature flags"


# ---------------------------------------------------------------------------
# Admin inline
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFeatureFlagsAdmin:
    """Tests for ``FeatureFlagsInline`` on ``ConferenceAdmin``."""

    def test_registered_standalone(self) -> None:
        assert FeatureFlags in admin_site._registry

    def test_inline_on_conference_admin(self) -> None:
        from django_program.conference.admin import ConferenceAdmin  # noqa: PLC0415

        inline_classes = [i.model for i in ConferenceAdmin.inlines]
        assert FeatureFlags in inline_classes

    def test_inline_max_num_is_one(self) -> None:
        from django_program.conference.admin import FeatureFlagsInline  # noqa: PLC0415

        assert FeatureFlagsInline.max_num == 1


# ---------------------------------------------------------------------------
# Auto-creation signal
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFeatureFlagsAutoCreation:
    """Tests for automatic FeatureFlags creation on Conference save."""

    def test_feature_flags_created_with_conference(self) -> None:
        conference = Conference.objects.create(
            name="NewConf",
            slug="newconf",
            start_date="2026-07-01",
            end_date="2026-07-05",
        )
        assert FeatureFlags.objects.filter(conference=conference).exists()

    def test_feature_flags_all_none_on_creation(self) -> None:
        conference = Conference.objects.create(
            name="NoneConf",
            slug="noneconf",
            start_date="2026-07-01",
            end_date="2026-07-05",
        )
        flags = conference.feature_flags
        assert flags.registration_enabled is None
        assert flags.sponsors_enabled is None
        assert flags.public_ui_enabled is None

    def test_update_does_not_create_duplicate(self) -> None:
        conference = Conference.objects.create(
            name="DupConf",
            slug="dupconf",
            start_date="2026-07-01",
            end_date="2026-07-05",
        )
        conference.name = "DupConf Updated"
        conference.save()
        assert FeatureFlags.objects.filter(conference=conference).count() == 1


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
