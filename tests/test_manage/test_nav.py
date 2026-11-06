"""Tests for the configurable manage nav registry and shell templatetag."""

import re
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


def register_host_section_with_children(registry: NavRegistry) -> None:
    """A host ``nav`` hook: a grouped parent item with a GET and a POST child."""
    registry.section("host-grouped", "Host Grouped", order=6)
    registry.add(
        "host-grouped",
        NavItem(
            key="host-parent",
            label="Parent",
            url="/host/parent/",
            group="Group A",
            children=lambda ctx: [
                NavItem(key="host-child-link", label="Child Link", url="/host/parent/child/"),
                NavItem(
                    key="host-child-post",
                    label="Child Post",
                    url="/host/parent/child-post/",
                    method="post",
                ),
            ],
        ),
    )


def register_cross_origin_post_item(registry: NavRegistry) -> None:
    """A host ``nav`` hook: a POST item whose action is an absolute external URL."""
    registry.section("host-external", "Host External")
    registry.add(
        "host-external",
        NavItem(
            key="host-external-post",
            label="External Action",
            url="https://evil.example.com/steal/",
            method="post",
        ),
    )


def register_badged_child(registry: NavRegistry) -> None:
    """A host ``nav`` hook: the only badge sits on a dynamic child."""
    registry.section("host-queues", "Queues")
    registry.add(
        "host-queues",
        NavItem(
            key="host-queues-parent",
            label="Queues",
            url="/host/queues/",
            children=lambda ctx: [NavItem(key="host-queue", label="Queue", url="/host/queues/q/", badge="queue")],
        ),
    )


def register_feature_gated_parent(registry: NavRegistry) -> None:
    """A host ``nav`` hook: a feature-gated parent with children that are not gated."""
    registry.section("host-feature", "Host Feature")
    registry.add(
        "host-feature",
        NavItem(
            key="host-feature-parent",
            label="Parent",
            url="/host/feature/",
            feature="sponsors",
            children=lambda ctx: [
                NavItem(key="host-feature-child", label="Child", url="/host/feature/child/"),
            ],
        ),
    )


def register_promoted_children(registry: NavRegistry) -> None:
    """A host ``nav`` hook: a parent whose URL never reverses, with two tabs sharing ``active``."""
    registry.section("host-tabs", "Host Tabs")
    registry.add(
        "host-tabs",
        NavItem(
            key="host-tabs-parent",
            label="Tabs",
            url="host:not-mounted",
            children=lambda ctx: [
                NavItem(key="host-tab-a", label="A", url="/host/tabs/a/", active=("tabs",)),
                NavItem(key="host-tab-b", label="B", url="/host/tabs/b/", active=("tabs",)),
            ],
        ),
    )


def test_promoted_children_sharing_active_nav_keep_one_current(rf, superuser, settings):
    settings.DJANGO_PROGRAM = {
        "manage": {"builtin_nav": False, "nav": ["tests.test_manage.test_nav.register_promoted_children"]}
    }
    request = rf.get("/host/tabs/b/")
    request.user = superuser
    (section,) = build_nav(request, active_nav="tabs")
    assert [(item.key, item.is_active) for item in section.items] == [("host-tab-a", False), ("host-tab-b", True)]


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

    def test_hide_nav_removes_dynamic_children(self, rf, superuser, conference, settings):
        settings.DJANGO_PROGRAM = {"manage": {"hide_nav": ["overrides-rooms"]}}
        request = rf.get("/")
        request.user = superuser
        sections = build_nav(request, conference=conference)
        overrides = next(item for section in sections for item in section.items if item.key == "overrides")
        child_keys = {child.key for child in overrides.children}
        assert "overrides-rooms" not in child_keys
        assert "overrides-speakers" in child_keys

    def test_children_outlive_a_parent_whose_module_is_off(self, rf, superuser, settings):
        settings.DJANGO_PROGRAM = {
            "features": {"sponsors_enabled": False},
            "manage": {"builtin_nav": False, "nav": ["tests.test_manage.test_nav.register_feature_gated_parent"]},
        }
        request = rf.get("/")
        request.user = superuser
        (section,) = build_nav(request)
        assert [item.key for item in section.items] == ["host-feature-child"]

    def test_children_stay_hidden_when_the_parent_permission_fails(self, rf, conference_perm_user, conference):
        request = rf.get("/")
        request.user = conference_perm_user
        keys = {item.key for section in build_nav(request, conference=conference) for item in section.items}
        assert not any(key.startswith("overrides") for key in keys)

    def test_badge_on_a_dynamic_child_gets_its_count(self, rf, superuser, settings):
        settings.DJANGO_PROGRAM = {
            "manage": {"builtin_nav": False, "nav": ["tests.test_manage.test_nav.register_badged_child"]}
        }
        request = rf.get("/")
        request.user = superuser
        (section,) = build_nav(request, badges=lambda: {"queue": 4})
        (parent,) = section.items
        assert [(child.key, child.badge_count) for child in parent.children] == [("host-queue", 4)]

    def test_badge_counts_are_not_loaded_without_badged_items(self, rf, superuser, conference):
        request = rf.get("/")
        request.user = superuser

        def explode() -> dict[str, int]:
            raise AssertionError

        assert build_nav(request, conference=conference, badges=explode)


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

    def test_palette_post_navigation_has_csrf_form(self, rf, superuser):
        html = _render_base(rf, superuser)
        assert 'id="manage-palette-post-form"' in html
        assert "csrfmiddlewaretoken" in html

    def test_grouped_item_renders_its_children(self, rf, superuser, settings):
        """Regression: grouped items used to render without their subnav children."""
        settings.DJANGO_PROGRAM = {
            "manage": {"nav": ["tests.test_manage.test_nav.register_host_section_with_children"]}
        }
        html = _render_base(rf, superuser, active_nav="host-child-link")
        assert "Child Link" in html
        assert "Child Post" in html
        assert 'data-subsection-target="host-grouped-group-a"' in html

    def test_post_child_item_renders_as_csrf_form_not_a_link(self, rf, superuser, settings):
        """Regression: POST children used to always render as plain GET links."""
        settings.DJANGO_PROGRAM = {
            "manage": {"nav": ["tests.test_manage.test_nav.register_host_section_with_children"]}
        }
        html = _render_base(rf, superuser, active_nav="host-child-link")
        assert '<form method="post" action="/host/parent/child-post/"' in html
        assert '<a href="/host/parent/child-post/"' not in html

    def test_cross_origin_post_item_omits_csrf_token(self, rf, superuser, settings):
        """Regression: a POST item pointing off-site must not leak the CSRF token."""
        settings.DJANGO_PROGRAM = {"manage": {"nav": ["tests.test_manage.test_nav.register_cross_origin_post_item"]}}
        html = _render_base(rf, superuser)
        assert '<form method="post" action="https://evil.example.com/steal/"' in html
        form_start = html.index('<form method="post" action="https://evil.example.com/steal/"')
        form_end = html.index("</form>", form_start)
        assert "csrfmiddlewaretoken" not in html[form_start:form_end]

    def test_same_origin_post_item_keeps_csrf_token(self, rf, superuser, settings):
        settings.DJANGO_PROGRAM = {
            "manage": {"nav": ["tests.test_manage.test_nav.register_host_section_with_children"]}
        }
        html = _render_base(rf, superuser, active_nav="host-child-link")
        form_start = html.index('<form method="post" action="/host/parent/child-post/"')
        form_end = html.index("</form>", form_start)
        assert "csrfmiddlewaretoken" in html[form_start:form_end]

    def test_submenu_expands_when_child_is_active(self, rf, superuser, settings):
        """Regression: the subnav only opened for an active parent, hiding an active child."""
        settings.DJANGO_PROGRAM = {
            "manage": {"nav": ["tests.test_manage.test_nav.register_host_section_with_children"]}
        }
        html = _render_base(rf, superuser, active_nav="host-child-link")
        assert 'id="manage-subnav-host-parent"' in html
        subnav_start = html.index('id="manage-subnav-host-parent"')
        subnav_tag = html[max(0, subnav_start - 200) : subnav_start]
        assert "sidebar-subnav open" in subnav_tag or 'class="sidebar-subnav open"' in subnav_tag
        assert 'aria-expanded="true"' in html[max(0, subnav_start - 400) : subnav_start]

    def test_home_href_is_conference_list_when_not_single_conference(self, rf, superuser, conference):
        """Regression: home_href used to link the dashboard for any conference in context."""
        html = _render_base(rf, superuser, conference=conference)
        match = re.search(r'<a href="([^"]+)" class="top-bar-title">', html)
        assert match is not None
        assert match.group(1) == reverse("manage:conference-list")

    def test_home_href_is_dashboard_in_single_conference_mode(self, rf, superuser, conference, settings):
        settings.DJANGO_PROGRAM = {"manage": {"conference": conference.slug}}
        html = _render_base(rf, superuser, conference=conference)
        match = re.search(r'<a href="([^"]+)" class="top-bar-title">', html)
        assert match is not None
        assert match.group(1) == reverse("manage:dashboard", kwargs={"conference_slug": conference.slug})

    def test_single_conference_home_skips_a_dashboard_the_user_cannot_open(
        self, rf, conference_perm_user, conference, settings
    ):
        settings.DJANGO_PROGRAM = {"manage": {"conference": conference.slug}}
        html = _render_base(rf, conference_perm_user, conference=conference)
        match = re.search(r'<a href="([^"]+)" class="top-bar-title">', html)
        assert match is not None
        assert match.group(1) == reverse("manage:section-list", kwargs={"conference_slug": conference.slug})

    def test_host_conference_object_in_context_is_ignored(self, rf, superuser, settings):
        settings.DJANGO_PROGRAM = {"manage": {"nav": ["tests.test_manage.test_nav.register_host_section"]}}
        html = _render_base(rf, superuser, conference="pycon-us-2027")
        assert "/host/widgets/" in html
        assert reverse("manage:conference-list") in html

    def test_shell_renders_without_the_request_context_processor(self, superuser):
        html = get_template("django_program/manage/base.html").render({"user": superuser})
        assert 'id="manage-sidebar"' not in html

    def test_logout_is_a_post_form(self, rf, superuser):
        html = _render_base(rf, superuser)
        assert f'<form method="post" action="{reverse("admin:logout")}" class="top-bar-logout">' in html

    def test_cross_origin_logout_renders_a_plain_link(self, rf, superuser, settings):
        """Regression: an off-site logout_url must not leak the CSRF token."""
        settings.DJANGO_PROGRAM = {"manage": {"logout_url": "https://sso.example.com/logout/"}}
        html = _render_base(rf, superuser)
        assert '<a href="https://sso.example.com/logout/" class="top-bar-link">Log out</a>' in html
        assert '<form method="post" action="https://sso.example.com/logout/"' not in html

    def test_focus_layout_has_no_drawer_toggle(self, rf, superuser, conference):
        request = rf.get("/")
        request.user = superuser
        html = get_template("django_program/manage/focus.html").render({"conference": conference}, request)
        assert 'id="manage-sidebar-toggle"' not in html
        assert 'id="manage-sidebar"' not in html

    def test_purchase_orders_follow_their_full_access_gate(self, rf, conference, db):
        user = User.objects.create_user(username="finance", password="password", email="finance@test.com")
        user.user_permissions.add(Permission.objects.get(codename="view_finance"))
        request = rf.get("/")
        request.user = User.objects.get(pk=user.pk)
        keys = {item.key for section in build_nav(request, conference=conference) for item in section.items}
        assert "financial" in keys
        assert "purchase-orders" not in keys

    def test_home_url_setting_wins_for_the_title_link(self, rf, superuser, conference, settings):
        settings.DJANGO_PROGRAM = {"manage": {"home_url": "/staff/", "conference": conference.slug}}
        html = _render_base(rf, superuser, conference=conference)
        assert '<a href="/staff/" class="top-bar-title">' in html
