# Customizing the Management UI

The management dashboard (`django_program.manage`) is a shell (top bar, sidebar,
Cmd/Ctrl-K jump palette, "needs attention" panel) plus a set of built-in modules.
Both halves are configurable, so a host project can:

- adopt django-program one module at a time and hide the rest,
- render its own staff pages inside the same shell,
- add its own sidebar sections, badges, and attention counts.

All options live under `DJANGO_PROGRAM["manage"]`.

## Settings reference

| Key | Default | Purpose |
|---|---|---|
| `title` | `"Conference Management"` | Top-bar title. |
| `home_url` | `""` | URL name or path for the title link. Empty: the conference list, or the single conference's dashboard when `conference` is set. |
| `conference` | `""` | Conference slug for single-conference sites. The conference list redirects to its dashboard, and pages without a `conference` in context still show the conference's nav. |
| `logout_url` | `"admin:logout"` | URL name or path for "Log out". |
| `public_schedule_link` | `True` | Show "View Public Schedule" when a conference is in scope. |
| `builtin_nav` | `True` | `True` keeps every built-in sidebar entry, `False` drops them all, a list keeps only those section or top-level item keys (dynamic children follow their parent). |
| `hide_nav` | `[]` | Section, item, or dynamic child keys to remove, applied after host hooks. |
| `nav` | `[]` | Dotted paths to `register(registry)` callables that add sections and items. |
| `attention` | `["django_program.manage.attention_builtin.builtin_attention"]` | Dotted paths to attention providers. |
| `stylesheets` | `[]` | Extra static stylesheets loaded after `django_program/manage/manage.css`. |
| `scripts` | `[]` | Extra static scripts loaded after `django_program/manage/manage.js`. |
| `palette` | `True` | Enable the Cmd/Ctrl-K jump palette. |
| `search_url` | `""` | URL name or path for the host's global search endpoint. Empty disables remote palette search; the palette still filters its built-in local items. |
| `search_placeholder` | `"Search…"` | Placeholder text shown on the top-bar search trigger and inside the palette input. |

Module toggles in `DJANGO_PROGRAM["features"]` apply to the manage UI as well: a
disabled module's sidebar entries disappear and its manage URLs return 404.

## Built-in sidebar keys

Sections: `conference`, `program`, `registration`, `sponsors`, `onsite`, `finance`,
`sync-overrides`.

Items: `dashboard`, `conference-edit`, `sections`, `rooms`, `speakers`, `talks`,
`schedule`, `activities`, `travel-grants`, `attendees`, `orders`, `letters`, `badges`,
`ticket-types`, `addons`, `vouchers`, `conditions`, `bulk-purchases`,
`sponsor-levels`, `sponsor-list`, `checkin`, `terminal`, `financial`, `purchase-orders`,
`expenses`, `analytics`, `reports`, `overrides`. Talk-type and override sub-tabs are
dynamic children of `talks` and `overrides` (`overrides-speakers`, `overrides-rooms`,
`overrides-sponsors`, `overrides-type-defaults`).

```python
DJANGO_PROGRAM = {
    "manage": {
        # Keep the conference dashboard and the whole Program section only
        "builtin_nav": ["dashboard", "program"],
        # ...but not rooms
        "hide_nav": ["rooms"],
    },
}
```

## Adding sidebar sections

A nav hook receives the {class}`~django_program.manage.nav.NavRegistry`:

```python
# myproject/staff/nav.py
from django_program.manage.nav import NavItem


def register(registry):
    registry.section("desk", "Registration desk", order=5)
    registry.add(
        "desk",
        NavItem(
            key="desk-check-in",
            label="Check in attendees",
            url="registration:check_in",          # URL name or literal path
            icon="check-square",
            permission="registration.check_in",   # str, list (any of), or callable(user)
            group="At the desk",                  # optional sub-heading
            description="scan badge qr",          # extra palette search text
        ),
        NavItem(
            key="desk-sync",
            label="Sync Pretalx now",
            url="schedule:trigger_sync_pretalx",
            method="post",                        # renders a CSRF form button
            permission=lambda user: user.is_staff,
        ),
    )
```

```python
DJANGO_PROGRAM = {"manage": {"nav": ["myproject.staff.nav.register"]}}
```

`NavItem` fields:

| Field | Meaning |
|---|---|
| `key` | Unique across all sections; also the default `active_nav` value. |
| `label` | Text, or a callable receiving the `NavContext`. |
| `url` | URL name (reversed) or literal path/URL (contains `/`). |
| `conference_url` | Reverse with `conference_slug`; hidden when no conference is in scope. |
| `icon` | Sprite name (`dp-i-<name>` in `django_program/manage/_icons.html`) or raw `<svg>` markup. |
| `permission` | `None`, a permission string, a list (any of), or `callable(user) -> bool`. |
| `feature` | django-program feature name; hidden when that module is off. |
| `active` | `active_nav` values that mark the item current. |
| `group` | Sub-heading inside the section. |
| `method` | `"get"` (link) or `"post"` (CSRF form button). |
| `description` | Extra palette search text. |
| `badge` | Attention item key whose count shows next to the label. |
| `children` | Callable returning dynamic child items. |
| `order` | Sort order inside the section. |

`NavSection` fields:

| Field | Meaning |
|---|---|
| `key` | Unique section key. |
| `label` | Section title, or a callable receiving the `NavContext`. |
| `order` | Sort order among sections; ties keep registration order. |
| `permission` | Extra visibility check for the whole section. |
| `feature` | django-program feature name; hidden when that module is off. |
| `utility` | Render below a separator at the end of the sidebar. |
| `palette` | `False` keeps the section in the sidebar but excludes its items from `palette_items`, e.g. a "shortcuts" section that duplicates tools listed elsewhere. Defaults to `True`. |

Items whose URL name does not reverse are skipped, so unmounted modules never
produce broken links. When an item is unavailable because its module is off, it
needs a conference, or its URL does not reverse, its visible children take its
place; when its permission check fails, its children are hidden too. When no item
matches the page's `active_nav`, the item whose URL is the longest prefix of the
request path is highlighted, so host sub-pages keep their section open.

Use `django_program.manage.nav.manage_perm("view_registration")` to reuse the
built-in permission rule (superuser, `program_conference.change_conference`, or
the listed permission).

## Attention counts

Providers return {class}`~django_program.manage.attention.AttentionItem` objects:

```python
# myproject/staff/attention.py
from django.urls import reverse

from django_program.manage.attention import AttentionItem


def pending_receipts(request, conference):
    if not request.user.has_perm("travel_grants.can_review_receipts"):
        return []
    count = Receipt.objects.filter(approved=False, flagged=False).count()
    return [AttentionItem(key="receipts", label="Receipts to review", count=count, url=reverse("receipts_review"))]
```

```python
DJANGO_PROGRAM = {
    "manage": {
        "attention": [
            "django_program.manage.attention_builtin.builtin_attention",
            "myproject.staff.attention.pending_receipts",
        ],
    },
}
```

Items show on the conference dashboard; a nav item with `badge="receipts"` shows
the count in the sidebar. Providers run at most once per request.

## Rendering host pages in the shell

Any template can extend the shell; no django-program view mixin is needed:

```django
{% extends "django_program/manage/base.html" %}

{% block title %}Generate vouchers{% endblock %}
{% block page_title %}<h1>Generate vouchers</h1>{% endblock %}
{% block content %}
  ...
{% endblock %}
```

Blocks: `title`, `extra_head`, `body_class`, `main_class`, `sidebar_toggle`,
`sidebar`, `topbar_actions`, `breadcrumb`, `messages`, `page_header`, `page_title`,
`page_actions`, `content`, `extra_js`.

The shell needs the `django.template.context_processors.request` context
processor to build navigation; without it pages render without the sidebar.
A `conference` context value that is not a django-program `Conference` is
ignored. "Log out" submits a POST to `logout_url`.

For kiosk-style pages without a sidebar, extend
`django_program/manage/focus.html`.

Set `active_nav` in the context to pin the highlighted item; otherwise the
path-prefix match applies. The shell's data comes from
`{% load manage_shell %}{% manage_shell as shell %}`, which host templates can use
directly to build their own home pages from the same nav (`shell.nav`,
`shell.palette_items`, `shell.search_href`).
