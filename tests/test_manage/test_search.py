"""Tests for the manage shell's global search: config, shell exposure, and the palette feed.

Covers ``ManageConfig.search_url``/``search_placeholder`` parsing, the resolved
``shell.search_href``, ``NavSection.palette`` exclusion from ``palette_items``,
child items taking their parent's label as the palette section, and the
rendered ``base.html`` search affordances.
"""

from django.contrib.auth.models import AnonymousUser
from django.template import RequestContext
from django.template.loader import get_template
from django.test import RequestFactory, override_settings

from django_program.manage.nav import ResolvedItem, ResolvedSection
from django_program.manage.templatetags.manage_shell import _palette_items, manage_shell
from django_program.settings import get_config


def _item(key, label, *, children=()):
    return ResolvedItem(
        key=key,
        label=label,
        href=f"/{key}/",
        icon="",
        group="",
        method="get",
        description="",
        section_label="S",
        children=children,
    )


class TestManageConfigSearchSettings:
    def test_defaults(self):
        with override_settings(DJANGO_PROGRAM={}):
            manage = get_config().manage
        assert manage.search_url == ""
        assert manage.search_placeholder == "Search…"

    def test_explicit_values(self):
        with override_settings(
            DJANGO_PROGRAM={"manage": {"search_url": "manage:search", "search_placeholder": "Find a tool…"}}
        ):
            manage = get_config().manage
        assert manage.search_url == "manage:search"
        assert manage.search_placeholder == "Find a tool…"


class TestShellExposesSearchHref:
    def test_resolves_literal_path(self):
        with override_settings(DJANGO_PROGRAM={"manage": {"search_url": "/staff/search/"}}):
            get_config.cache_clear()
            request = RequestFactory().get("/")
            request.user = AnonymousUser()
            context = RequestContext(request, {"request": request})
            shell = manage_shell(context)
        assert shell.search_href == "/staff/search/"
        get_config.cache_clear()

    def test_empty_when_unset(self):
        with override_settings(DJANGO_PROGRAM={}):
            get_config.cache_clear()
            request = RequestFactory().get("/")
            request.user = AnonymousUser()
            context = RequestContext(request, {"request": request})
            shell = manage_shell(context)
        assert shell.search_href == ""
        get_config.cache_clear()

    def test_empty_without_request(self):
        with override_settings(DJANGO_PROGRAM={}):
            get_config.cache_clear()
            from django.template import Context

            shell = manage_shell(Context({}))
        assert shell.search_href == ""
        get_config.cache_clear()


class TestPaletteItemsExcludesNonPaletteSections:
    def test_section_with_palette_false_is_dropped(self):
        shown = ResolvedSection(key="shown", label="Shown", utility=False, items=(_item("a", "A"),))
        hidden = ResolvedSection(key="hidden", label="Hidden", utility=False, items=(_item("b", "B"),), palette=False)

        items = _palette_items([shown, hidden])

        assert [i["key"] for i in items] == ["a"]

    def test_default_palette_true_keeps_section(self):
        section = ResolvedSection(key="s", label="S", utility=False, items=(_item("a", "A"),))

        items = _palette_items([section])

        assert [i["key"] for i in items] == ["a"]


class TestPaletteItemsChildSectionLabel:
    def test_child_uses_parent_item_label_not_section_label(self):
        child = _item("check-in", "Check in attendees")
        parent = _item("desk", "Registration desk", children=(child,))
        section = ResolvedSection(key="all-tools", label="All tools", utility=False, items=(parent,))

        items = _palette_items([section])

        by_key = {i["key"]: i for i in items}
        assert by_key["desk"]["section"] == "All tools"
        assert by_key["check-in"]["section"] == "Registration desk"

    def test_grandchild_uses_its_immediate_parent_label(self):
        grandchild = _item("scan", "Scan QR")
        child = _item("check-in", "Check in attendees", children=(grandchild,))
        parent = _item("desk", "Registration desk", children=(child,))
        section = ResolvedSection(key="all-tools", label="All tools", utility=False, items=(parent,))

        items = _palette_items([section])

        by_key = {i["key"]: i for i in items}
        assert by_key["scan"]["section"] == "Check in attendees"


class TestBaseHtmlSearchRendering:
    def test_renders_search_data_attribute_and_placeholder(self):
        manage_config = {"search_url": "/staff/search/", "search_placeholder": "Find a tool…"}
        with override_settings(DJANGO_PROGRAM={"manage": manage_config}):
            get_config.cache_clear()
            request = RequestFactory().get("/")
            request.user = AnonymousUser()
            template = get_template("django_program/manage/base.html")
            html = template.render({}, request=request)
        get_config.cache_clear()

        assert 'data-search-url="/staff/search/"' in html
        assert "Find a tool…" in html
        assert html.count("Find a tool…") >= 2

    def test_omits_search_data_attribute_when_unset(self):
        with override_settings(DJANGO_PROGRAM={}):
            get_config.cache_clear()
            request = RequestFactory().get("/")
            request.user = AnonymousUser()
            template = get_template("django_program/manage/base.html")
            html = template.render({}, request=request)
        get_config.cache_clear()

        assert 'data-search-url=""' in html
