"""Tests for the configurable manage nav registry and shell templatetag."""

from datetime import date

import pytest
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ImproperlyConfigured
from django.template.loader import get_template
from django.test import RequestFactory
from django.urls import reverse

from django_program.conference.models import Conference
from django_program.manage.nav import (
    NavItem,
    NavRegistry,
    build_nav,
    get_registry,
    nav_uses_badges,
)
from django_program.settings import get_config

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(username="admin", password="password", email="admin@test.com")


@pytest.fixture
def conference_perm_user(db):
    """A user with only the ``view_program`` permission."""
    user = User.objects.create_user(username="program-only", password="password", email="program@test.com")
    ct = ContentType.objects.get(app_label="program_conference", model="conference")
    perm = Permission.objects.get(content_type=ct, codename="view_program")
    user.user_permissions.add(perm)
    return user


@pytest.fixture
def change_conference_user(db):
    """A user with the legacy full-access ``change_conference`` permission."""
    user = User.objects.create_user(username="full-access", password="password", email="full@test.com")
    ct = ContentType.objects.get(app_label="program_conference", model="conference")
    perm = Permission.objects.get(content_type=ct, codename="change_conference")
    user.user_permissions.add(perm)
    return user


@pytest.fixture
def anon_user(db):
    return User.objects.create_user(username="nobody", password="password", email="nobody@test.com")


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
# Host nav hook + render helper (used by the "plain host page" tests)
# ---------------------------------------------------------------------------


def register_host_section(registry: NavRegistry) -> None:
    """A host ``nav`` hook: adds one plain section with one item."""
    registry.section("host-tools", "Host Tools", order=5)
    registry.add(
        "host-tools",
        NavItem(key="host-widgets", label="Widgets", url="/host/widgets/"),
    )


def _render_base(request_factory: RequestFactory, user, *, conference=None, active_nav: str = "", path: str = "/"):
    request = request_factory.get(path)
    request.user = user
    template = get_template("django_program/manage/base.html")
    context: dict[str, object] = {"active_nav": active_nav}
    if conference is not None:
        context["conference"] = conference
    return template.render(context, request)


# ---------------------------------------------------------------------------
# NavRegistry: keep / remove / duplicate key
# ---------------------------------------------------------------------------


class TestNavRegistry:
    def test_keep_filters_sections_and_items(self):
        registry = NavRegistry()
        registry.section("a", "A")
        registry.add("a", NavItem(key="a1", label="A1", url="/a1/"), NavItem(key="a2", label="A2", url="/a2/"))
        registry.section("b", "B")
        registry.add("b", NavItem(key="b1", label="B1", url="/b1/"))

        registry.keep(["a1"])

        entries = registry.entries()
        assert [section.key for section, _ in entries] == ["a"]
        assert [item.key for item in entries[0][1]] == ["a1"]

    def test_remove_drops_section_with_its_items(self):
        registry = NavRegistry()
        registry.section("a", "A")
        registry.add("a", NavItem(key="a1", label="A1", url="/a1/"))
        registry.section("b", "B")
        registry.add("b", NavItem(key="b1", label="B1", url="/b1/"))

        registry.remove("a")

        assert "a" not in registry
        assert "a1" not in registry
        assert [section.key for section, _ in registry.entries()] == ["b"]

    def test_remove_drops_single_item(self):
        registry = NavRegistry()
        registry.section("a", "A")
        registry.add("a", NavItem(key="a1", label="A1", url="/a1/"), NavItem(key="a2", label="A2", url="/a2/"))

        registry.remove("a1")

        assert "a1" not in registry
        assert [item.key for item in registry.entries()[0][1]] == ["a2"]

    def test_duplicate_item_key_raises(self):
        registry = NavRegistry()
        registry.section("a", "A")
        registry.add("a", NavItem(key="dup", label="A1", url="/a1/"))

        with pytest.raises(ImproperlyConfigured, match="Duplicate manage nav key 'dup'"):
            registry.add("a", NavItem(key="dup", label="A2", url="/a2/"))

    def test_add_to_unknown_section_raises(self):
        registry = NavRegistry()
        with pytest.raises(ImproperlyConfigured, match="Unknown manage nav section"):
            registry.add("missing", NavItem(key="x", label="X", url="/x/"))


# ---------------------------------------------------------------------------
# get_registry(): builtin_nav / hide_nav / host hooks
# ---------------------------------------------------------------------------


class TestGetRegistry:
    def test_builtin_nav_list_keeps_only_listed_keys(self, settings):
        settings.DJANGO_PROGRAM = {"manage": {"builtin_nav": ["conference", "dashboard", "conference-edit"]}}
        registry = get_registry()
        assert [section.key for section, _ in registry.entries()] == ["conference"]

    def test_builtin_nav_false_drops_everything(self, settings):
        settings.DJANGO_PROGRAM = {"manage": {"builtin_nav": False}}
        registry = get_registry()
        assert registry.entries() == []

    def test_hide_nav_removes_after_builtin(self, settings):
        settings.DJANGO_PROGRAM = {"manage": {"hide_nav": ["activities"]}}
        registry = get_registry()
        all_item_keys = {item.key for _, items in registry.entries() for item in items}
        assert "activities" not in all_item_keys
        assert "sections" in all_item_keys  # rest of "program" section untouched

    def test_host_nav_hook_adds_section(self, settings):
        settings.DJANGO_PROGRAM = {"manage": {"nav": ["tests.test_manage.test_nav.register_host_section"]}}
        registry = get_registry()
        assert "host-tools" in registry
        assert "host-widgets" in registry

    def test_bad_nav_hook_path_raises(self, settings):
        settings.DJANGO_PROGRAM = {"manage": {"nav": ["tests.test_manage.test_nav.does_not_exist"]}}
        with pytest.raises(ImproperlyConfigured, match="could not be imported"):
            get_registry()


# ---------------------------------------------------------------------------
# build_nav(): features, permissions, active-state
# ---------------------------------------------------------------------------


class TestBuildNav:
    def test_feature_off_hides_items(self, rf, superuser, conference, settings):
        request = rf.get("/")
        request.user = superuser
        sections = build_nav(request, conference=conference, active_nav="")
        keys = {item.key for section in sections for item in section.items}
        assert "sponsor-levels" in keys

        settings.DJANGO_PROGRAM = {"features": {"sponsors_enabled": False}}
        request = rf.get("/")
        request.user = superuser
        sections = build_nav(request, conference=conference, active_nav="")
        keys = {item.key for section in sections for item in section.items}
        assert "sponsor-levels" not in keys

    def test_permission_gating_restricts_to_users_sections(self, rf, conference_perm_user, conference):
        request = rf.get("/")
        request.user = conference_perm_user
        sections = build_nav(request, conference=conference, active_nav="")
        assert [section.key for section in sections] == ["program"]
        item_keys = {item.key for item in sections[0].items}
        assert item_keys == {"sections", "rooms", "speakers", "talks", "schedule"}

    def test_change_conference_permission_sees_every_section(self, rf, change_conference_user, conference):
        request = rf.get("/")
        request.user = change_conference_user
        sections = build_nav(request, conference=conference, active_nav="")
        section_keys = {section.key for section in sections}
        assert {"conference", "program", "registration", "sponsors", "onsite", "finance", "sync-overrides"} <= (
            section_keys
        )

    def test_superuser_sees_every_section(self, rf, superuser, conference):
        request = rf.get("/")
        request.user = superuser
        sections = build_nav(request, conference=conference, active_nav="")
        section_keys = {section.key for section in sections}
        assert {"conference", "program", "registration", "sponsors", "onsite", "finance", "sync-overrides"} <= (
            section_keys
        )

    def test_user_with_no_permissions_sees_nothing(self, rf, anon_user, conference):
        request = rf.get("/")
        request.user = anon_user
        sections = build_nav(request, conference=conference, active_nav="")
        assert sections == []

    def test_path_prefix_marks_active_without_matching_active_nav(self, rf, superuser, conference):
        path = reverse("manage:talk-list", kwargs={"conference_slug": conference.slug})
        request = rf.get(path)
        request.user = superuser
        sections = build_nav(request, conference=conference, active_nav="")
        talks_item = next(item for section in sections for item in section.items if item.key == "talks")
        assert talks_item.is_active is True
        other_items = [
            item for section in sections for item in section.items if item.key != "talks" and item.method == "get"
        ]
        assert all(not item.is_active for item in other_items)

    @pytest.mark.parametrize(
        ("url_name", "active_key"),
        [("manage:room-override-list", "overrides-rooms"), ("manage:override-list", "overrides")],
    )
    def test_shared_active_nav_highlights_one_family_member(self, rf, superuser, conference, url_name, active_key):
        request = rf.get(reverse(url_name, kwargs={"conference_slug": conference.slug}))
        request.user = superuser
        sections = build_nav(request, conference=conference, active_nav="overrides")
        overrides = next(item for section in sections for item in section.items if item.key == "overrides")
        active = [entry.key for entry in (overrides, *overrides.children) if entry.is_active]
        assert active == [active_key]

    def test_nav_uses_badges_false_by_default(self):
        assert nav_uses_badges() is False


# ---------------------------------------------------------------------------
# Rendering base.html on a plain host page
# ---------------------------------------------------------------------------


class TestManageShellRendering:
    def test_host_hook_section_rendered_on_plain_page(self, rf, superuser, settings):
        settings.DJANGO_PROGRAM = {"manage": {"nav": ["tests.test_manage.test_nav.register_host_section"]}}
        html = _render_base(rf, superuser)
        assert "Host Tools" in html
        assert "Widgets" in html
        assert "/host/widgets/" in html

    def test_feature_off_hides_item_in_rendered_sidebar(self, rf, superuser, conference, settings):
        html = _render_base(rf, superuser, conference=conference)
        assert "Levels" in html  # sponsor-levels item label

        settings.DJANGO_PROGRAM = {"features": {"sponsors_enabled": False}}
        html = _render_base(rf, superuser, conference=conference)
        assert "Levels" not in html

    def test_single_conference_config_shows_conference_items_without_context(self, rf, superuser, conference, settings):
        settings.DJANGO_PROGRAM = {"manage": {"conference": conference.slug}}
        # No "conference" key in context at all -- host page using the shared shell.
        html = _render_base(rf, superuser)
        dashboard_url = reverse("manage:dashboard", kwargs={"conference_slug": conference.slug})
        assert dashboard_url in html
        assert conference.name in html

    def test_no_conference_and_no_manage_conference_hides_conference_items(self, rf, superuser):
        html = _render_base(rf, superuser)
        assert 'id="manage-sidebar"' not in html
