"""Edge-case tests for attention providers, nav internals, and the manage shell tag.

Covers error paths, request caching, and fallbacks that the main nav/attention
test suites don't exercise: bad provider/hook configuration, cache hits,
dynamic children whose URL never reverses, and URL resolution when the host
urlconf doesn't mount the manage app.
"""

from datetime import date
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory
from django.urls import NoReverseMatch

from django_program.conference.models import Conference
from django_program.manage.attention import AttentionItem, attention_counts, get_attention
from django_program.manage.nav import (
    NavContext,
    NavRegistry,
    ResolvedItem,
    ResolvedSection,
    _settle_active,
    check_permission,
    get_registry,
)
from django_program.manage.nav_builtin import _talk_type_children
from django_program.manage.templatetags.manage_shell import (
    _resolve_conference,
    _resolve_home_href,
    _resolve_url,
    nav_icon,
)
from django_program.pretalx.models import Talk
from django_program.settings import ManageConfig, get_config

# A deliberately empty urlconf: used to exercise URL-resolution fallbacks when
# the manage app (or anything else) isn't mounted on the host site.
urlpatterns = []


def provider_one(request, conference):
    """An attention provider used by dotted-path config in the tests below."""
    return [AttentionItem(key="x", label="X", count=3)]


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(username="admin", password="password", email="admin@test.com")


@pytest.fixture
def plain_user(db):
    return User.objects.create_user(username="plain", password="password")


@pytest.fixture
def conference(db):
    return Conference.objects.create(
        name="Test Conf",
        slug="test-conf",
        start_date=date(2027, 5, 1),
        end_date=date(2027, 5, 3),
        timezone="UTC",
        pretalx_event_slug="test-event",
        is_active=True,
    )


def _clear_caches():
    get_config.cache_clear()
    get_registry.cache_clear()


@pytest.fixture(autouse=True)
def _reset_caches():
    _clear_caches()
    yield
    _clear_caches()


# ---------------------------------------------------------------------------
# attention.py
# ---------------------------------------------------------------------------


class TestLoadProviders:
    def test_bad_provider_path_raises(self, settings):
        settings.DJANGO_PROGRAM = {"manage": {"attention": ["tests.test_manage.test_shell_edges.does_not_exist"]}}
        request = RequestFactory().get("/")
        with pytest.raises(ImproperlyConfigured, match="could not be imported"):
            get_attention(request, None)

    def test_non_callable_provider_raises(self, settings):
        settings.DJANGO_PROGRAM = {"manage": {"attention": ["django_program.manage.attention._REQUEST_CACHE_ATTR"]}}
        request = RequestFactory().get("/")
        with pytest.raises(ImproperlyConfigured, match="is not callable"):
            get_attention(request, None)


class TestGetAttentionCaching:
    def test_second_call_returns_cached_result(self, settings):
        settings.DJANGO_PROGRAM = {"manage": {"attention": ["tests.test_manage.test_shell_edges.provider_one"]}}
        request = RequestFactory().get("/")
        first = get_attention(request, None)
        second = get_attention(request, None)
        assert first is second
        assert [item.key for item in first] == ["x"]


class TestAttentionCounts:
    def test_maps_key_to_count(self, settings):
        settings.DJANGO_PROGRAM = {"manage": {"attention": ["tests.test_manage.test_shell_edges.provider_one"]}}
        request = RequestFactory().get("/")
        assert attention_counts(request, None) == {"x": 3}


# ---------------------------------------------------------------------------
# nav.py
# ---------------------------------------------------------------------------


class TestRegistrySectionUpdate:
    def test_calling_section_again_updates_label_and_options(self):
        registry = NavRegistry()
        first = registry.section("a", "A", order=1)
        updated = registry.section("a", "B", order=5)
        assert updated is not first
        assert updated.label == "B"
        assert updated.order == 5
        (stored_section, _items) = registry.entries()[0]
        assert stored_section.label == "B"
        assert stored_section.order == 5


class TestGetRegistryNavHook:
    def test_non_callable_nav_hook_raises(self, settings):
        settings.DJANGO_PROGRAM = {"manage": {"nav": ["django_program.manage.nav.Label"]}}
        with pytest.raises(ImproperlyConfigured, match="is not callable"):
            get_registry()


class TestCheckPermission:
    def test_string_permission_checks_user_has_perm(self, plain_user):
        assert check_permission(plain_user, "program_conference.change_conference") is False

    def test_sequence_of_permissions_is_any_of(self, plain_user):
        assert check_permission(plain_user, ("program_conference.a", "program_conference.b")) is False


class TestResolvedSectionIsActive:
    def test_is_active_true_when_an_item_is_active(self):
        item = ResolvedItem(
            key="i",
            label="I",
            href="/i/",
            icon="",
            group="",
            method="get",
            description="",
            section_label="S",
            is_active=True,
        )
        section = ResolvedSection(key="s", label="S", utility=False, items=(item,))
        assert section.is_active is True


class TestSettleActive:
    def test_several_active_entries_none_a_path_prefix_first_wins(self):
        def _item(key, href):
            return ResolvedItem(
                key=key,
                label=key,
                href=href,
                icon="",
                group="",
                method="get",
                description="",
                section_label="S",
                is_active=True,
            )

        item_a = _item("a", "/a/")
        item_b = _item("b", "/b/")
        section = ResolvedSection(key="s", label="S", utility=False, items=(item_a, item_b))

        result = _settle_active([section], "/nowhere-near-either/")

        marked = {item.key: item.is_active for item in result[0].items}
        assert marked == {"a": True, "b": False}


# ---------------------------------------------------------------------------
# nav_builtin.py
# ---------------------------------------------------------------------------


class TestTalkTypeChildren:
    def test_child_skipped_when_its_url_does_not_reverse(self, rf, conference, superuser):
        Talk.objects.create(conference=conference, pretalx_code="T1", title="Talk", submission_type="Talk")
        request = rf.get("/")
        request.user = superuser
        ctx = NavContext(request=request, conference=conference)

        with patch("django_program.manage.nav_builtin.reverse", side_effect=NoReverseMatch):
            children = list(_talk_type_children(ctx))

        assert children == []


# ---------------------------------------------------------------------------
# templatetags/manage_shell.py
# ---------------------------------------------------------------------------


class TestResolveUrl:
    def test_literal_path_is_returned_as_is(self):
        assert _resolve_url("/custom/path/") == "/custom/path/"

    def test_unresolvable_name_returns_empty_string(self):
        assert _resolve_url("does-not-exist:nothing") == ""


class TestResolveConference:
    def test_conference_app_not_installed_returns_none(self):
        config = ManageConfig()
        with patch("django_program.manage.templatetags.manage_shell.apps.is_installed", return_value=False):
            assert _resolve_conference(None, config) is None


class TestResolveHomeHref:
    def test_dashboard_not_mounted_falls_back_to_sections(self, settings, superuser, conference):
        settings.ROOT_URLCONF = "tests.test_manage.test_shell_edges"
        config = ManageConfig(conference=conference.slug)
        assert _resolve_home_href(config, conference, superuser, []) == ""

    def test_conference_list_not_mounted_returns_empty_string(self, settings, superuser):
        settings.ROOT_URLCONF = "tests.test_manage.test_shell_edges"
        config = ManageConfig(conference="")
        assert _resolve_home_href(config, None, superuser, []) == ""


class TestNavIcon:
    def test_empty_icon_returns_empty_string(self):
        assert nav_icon("") == ""

    def test_raw_svg_markup_is_returned_verbatim(self):
        svg = '<svg role="img"><use href="#x"/></svg>'
        assert str(nav_icon(svg)) == svg
