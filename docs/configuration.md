# Configuration

django-program reads its settings from a single `DJANGO_PROGRAM` dictionary in your
Django settings module. Internally this dict gets parsed into frozen dataclasses with
validation, so you get clear error messages if something is wrong.

## Django Settings (`DJANGO_PROGRAM`)

### Full example

```python
DJANGO_PROGRAM = {
    # Stripe payment gateway
    "stripe": {
        "secret_key": "sk_test_...",
        "publishable_key": "pk_test_...",
        "webhook_secret": "whsec_...",
        "api_version": "2024-12-18",       # default
        "webhook_tolerance": 300,           # seconds, default
    },
    # Pretalx schedule sync
    "pretalx": {
        "base_url": "https://pretalx.com",  # default
        "token": "your-api-token",
        "schedule_delete_guard_enabled": True,    # default
        "schedule_delete_guard_min_existing_slots": 5,  # default
        "schedule_delete_guard_max_fraction_removed": 0.4,  # default
    },
    # PSF sponsor API (PyCon US specific)
    "psf_sponsors": {
        "api_url": "https://www.python.org/api/v2",  # default
        "token": "your-psf-token",
        "auth_scheme": "Token",         # default
        "publisher": "pycon",           # default
        "flight": "sponsors",           # default
    },
    # Feature toggles (all default to True)
    "features": {
        "registration_enabled": True,
        "sponsors_enabled": True,
        "travel_grants_enabled": True,
        "programs_enabled": True,
        "pretalx_sync_enabled": True,
        "public_ui_enabled": True,
        "manage_ui_enabled": True,
        "all_ui_enabled": True,
    },
    # General
    "cart_expiry_minutes": 30,          # default
    "pending_order_expiry_minutes": 15, # default
    "order_reference_prefix": "ORD",    # default
    "currency": "USD",                  # default
    "currency_symbol": "$",             # default
    "max_grant_amount": 3000,           # default, for travel grants
}
```

### Stripe settings

| Key | Type | Default | Description |
|---|---|---|---|
| `secret_key` | `str \| None` | `None` | Stripe secret API key. Required for payment processing. |
| `publishable_key` | `str \| None` | `None` | Stripe publishable key for client-side checkout. |
| `webhook_secret` | `str \| None` | `None` | Webhook signing secret for verifying Stripe events. |
| `api_version` | `str` | `"2024-12-18"` | Stripe API version to pin against. |
| `webhook_tolerance` | `int` | `300` | Maximum age (seconds) of a webhook event before it is rejected. |

### Pretalx settings

| Key | Type | Default | Description |
|---|---|---|---|
| `base_url` | `str` | `"https://pretalx.com"` | Base URL of your Pretalx instance. |
| `token` | `str \| None` | `None` | Pretalx API token for authenticated requests. |
| `schedule_delete_guard_enabled` | `bool` | `True` | When `True`, prevents accidental mass-deletion of schedule slots during sync. |
| `schedule_delete_guard_min_existing_slots` | `int` | `5` | Minimum existing slots before the guard kicks in. |
| `schedule_delete_guard_max_fraction_removed` | `float` | `0.4` | Maximum fraction of slots that can be removed in a single sync before the guard aborts. |

The delete guard exists because the Pretalx `/talks/` endpoint occasionally returns
404 on some instances. Without the guard, a sync would delete every existing slot in
the database. With the guard enabled (the default), the sync aborts if more than 40%
of existing slots would be removed when at least 5 slots already exist.

### PSF sponsor settings

These are specific to PyCon US and the Python Software Foundation's sponsor data API.
Most conferences can ignore this section entirely.

| Key | Type | Default | Description |
|---|---|---|---|
| `api_url` | `str` | `"https://www.python.org/api/v2"` | PSF API base URL. |
| `token` | `str \| None` | `None` | PSF API token. |
| `auth_scheme` | `str` | `"Token"` | HTTP auth scheme prefix. |
| `publisher` | `str` | `"pycon"` | Publisher identifier for the PSF API. |
| `flight` | `str` | `"sponsors"` | Flight identifier for the PSF API. |

### General settings

| Key | Type | Default | Description |
|---|---|---|---|
| `cart_expiry_minutes` | `int` | `30` | Minutes before an inactive cart expires and releases its inventory hold. |
| `pending_order_expiry_minutes` | `int` | `15` | Minutes before a pending (unpaid) order expires. |
| `order_reference_prefix` | `str` | `"ORD"` | Prefix for generated order reference codes (e.g. `ORD-A1B2C3D4`). |
| `currency` | `str` | `"USD"` | ISO 4217 currency code used throughout the system. |
| `currency_symbol` | `str` | `"$"` | Display symbol for the currency. |
| `max_grant_amount` | `int` | `3000` | Maximum travel grant amount in the configured currency. |

### Feature toggles

Feature toggles disable entire modules and UI sections per-conference. Every toggle
defaults to `True` (enabled). Disable a module by setting its flag to `False` in
settings, or override it per-conference through the database.

#### Settings defaults

Add a `features` dict to `DJANGO_PROGRAM` in your Django settings:

```python
DJANGO_PROGRAM = {
    "features": {
        "registration_enabled": True,
        "sponsors_enabled": True,
        "travel_grants_enabled": False,   # disable travel grants globally
        "programs_enabled": True,
        "pretalx_sync_enabled": True,
        "public_ui_enabled": True,
        "manage_ui_enabled": True,
        "all_ui_enabled": True,           # master switch for all UI
    },
    # ... other settings ...
}
```

Changing these values requires a server restart.

#### Available toggles

**Module toggles** control backend functionality:

| Key | Default | Controls |
|---|---|---|
| `registration_enabled` | `True` | Ticket types, cart, checkout, orders |
| `sponsors_enabled` | `True` | Sponsor levels, benefits, comp vouchers |
| `travel_grants_enabled` | `True` | Travel grant applications and review |
| `programs_enabled` | `True` | Activities and signups |
| `pretalx_sync_enabled` | `True` | Speaker/talk/room sync from Pretalx |

**UI toggles** control interface visibility:

| Key | Default | Controls |
|---|---|---|
| `public_ui_enabled` | `True` | Public-facing conference pages |
| `manage_ui_enabled` | `True` | Organizer management dashboard |
| `all_ui_enabled` | `True` | Master switch -- when `False`, both `public_ui` and `manage_ui` are forced off regardless of their individual values |

#### Per-conference database overrides

Each conference can override the global defaults through a `FeatureFlags` row in the
database. These overrides take effect immediately without a server restart.

The `FeatureFlags` model uses nullable booleans with three states:

- **`None`** (blank) -- use the default from `DJANGO_PROGRAM["features"]`
- **`True`** -- force the feature on for this conference
- **`False`** -- force the feature off for this conference

Resolution order for each flag:

1. If the conference has a `FeatureFlags` row with an explicit `True` or `False`, that value wins.
2. Otherwise, the default from `DJANGO_PROGRAM["features"]` is used.
3. For `public_ui` and `manage_ui`, the `all_ui_enabled` master switch is evaluated first.

#### Django admin

Open the Conference admin page. The **Feature flags** inline appears below the
conference fields, grouped into "Module Toggles" and "UI Toggles". Each dropdown
offers three choices:

- **Default (enabled)** -- inherit from settings
- **Yes -- force ON** -- override to enabled
- **No -- force OFF** -- override to disabled

Feature flags are also available as a standalone admin model at
**Conference > Feature flags** for a cross-conference overview.

#### Checking features in Python code

Use `is_feature_enabled()` to check a toggle at runtime:

```python
from django_program.features import is_feature_enabled

# Check against global settings only
if is_feature_enabled("registration"):
    ...

# Check with per-conference DB override
if is_feature_enabled("sponsors", conference=my_conference):
    ...
```

Raise a 404 when a feature is disabled:

```python
from django_program.features import require_feature

def my_view(request):
    require_feature("registration", conference=request.conference)
    # ... view logic ...
```

Guard a class-based view with the `FeatureRequiredMixin`:

```python
from django_program.features import FeatureRequiredMixin

class TicketListView(ConferenceMixin, FeatureRequiredMixin, ListView):
    required_feature = ("registration", "public_ui")
```

The mixin checks all listed features during `dispatch()`. If the view also uses
`ConferenceMixin` (placed before `FeatureRequiredMixin` in the MRO), per-conference
overrides are picked up automatically from `self.conference`.

#### Using features in templates

Add the context processor to your `TEMPLATES` setting:

```python
TEMPLATES = [
    {
        "OPTIONS": {
            "context_processors": [
                # ... existing processors ...
                "django_program.context_processors.program_features",
            ],
        },
    },
]
```

Then use `program_features` in your templates to conditionally render sections:

```html+django
{% if program_features.registration_enabled %}
    <a href="{% url 'registration:ticket-list' %}">Buy Tickets</a>
{% endif %}

{% if program_features.sponsors_enabled %}
    <a href="{% url 'sponsors:sponsor-list' %}">Our Sponsors</a>
{% endif %}
```

The context processor resolves each flag through `is_feature_enabled()`, so master
switch logic and per-conference DB overrides are applied. When the request has a
`conference` attribute (set by middleware or the view), that conference's `FeatureFlags`
row is consulted automatically.

### Accessing config in code

```python
from django_program.settings import get_config

config = get_config()
config.stripe.secret_key       # str | None
config.pretalx.base_url        # str
config.cart_expiry_minutes      # int
config.currency                 # str
```

`get_config()` returns a frozen `ProgramConfig` dataclass. The result is cached and
the cache automatically clears when Django's `setting_changed` signal fires (which
happens inside `override_settings` in tests).

## TOML Bootstrap

The `bootstrap_conference` management command creates a full conference from a single
TOML file. Sections, ticket types, add-ons, and sponsor levels in one shot.

### Running the command

```bash
# Create a new conference
uv run python manage.py bootstrap_conference --config conference.toml

# Update an existing conference (matched by slug)
uv run python manage.py bootstrap_conference --config conference.toml --update

# Preview without touching the database
uv run python manage.py bootstrap_conference --config conference.toml --dry-run

# Create conference + generate demo data (vouchers, users, orders, carts)
uv run python manage.py bootstrap_conference --config conference.toml --seed-demo
```

The entire operation runs inside a single database transaction. If anything fails,
nothing is committed.

### `[conference]` table (required)

```toml
[conference]
name = "PyCon US 2027"           # required
start = 2027-05-14               # required, TOML native date
end = 2027-05-22                 # required, TOML native date
timezone = "America/New_York"    # required, IANA timezone
slug = "pycon-us-2027"           # optional, auto-generated from name
venue = "Convention Center"      # optional
pretalx_event_slug = "pycon-us"  # optional, for Pretalx sync
website_url = "https://..."      # optional
total_capacity = 2500            # optional, 0 = unlimited (default)
```

`total_capacity` sets the maximum number of tickets sold across all ticket types for the
entire conference. Add-ons do not count toward this limit. Set to `0` or omit entirely
for unlimited capacity. See [Global Ticket Capacity](registration-flow.md#global-ticket-capacity)
for enforcement details.

### Sections (required, at least one)

```toml
[[conference.sections]]
name = "Tutorials"
start = 2027-05-14
end = 2027-05-15
slug = "tutorials"    # optional, auto-generated from name
```

### Tickets (optional)

```toml
[[conference.tickets]]
name = "Individual"
price = 100.00                          # parsed as Decimal
quantity = 2500                         # total_quantity
per_user = 1                            # limit_per_user
voucher_required = false                # optional, default false
available = { opens = 2025-01-15, closes = 2027-05-13 }  # optional
```

### Add-ons (optional)

```toml
[[conference.addons]]
name = "Tutorial: Intro to Django"
price = 150.00
quantity = 40
requires = ["individual", "corporate"]  # ticket type slugs
```

### Sponsor levels (optional)

```toml
[[conference.sponsor_levels]]
name = "Visionary"
cost = 150_000.00
comp_tickets = 25    # comp vouchers auto-generated per sponsor
```

### Validation

The TOML loader validates:

- All required fields are present in each table
- Slugs are auto-generated from `name` if not provided
- Slugs are unique within their list (no duplicate section slugs, etc.)
- Prices are parsed as `Decimal` for exact arithmetic
- Dates are native TOML dates (not strings)

If validation fails, the loader raises `ValueError` or `TypeError` with a message
that tells you exactly which field and index caused the problem.

### The `--seed-demo` flag

Passing `--seed-demo` generates sample transactional data on top of the bootstrapped
conference:

- **Vouchers** -- speaker comp, student comp, 20% early bird percentage, $25 fixed
  discount. Random codes are printed to stdout so you can test with them.
- **Demo users** -- Five users (`attendee_alice`, `attendee_bob`, `speaker_carol`,
  `attendee_dave`, `attendee_eve`), all with password `demo` and `is_staff=True`.
- **Orders** -- Alice with a paid individual ticket + t-shirt, Bob with a paid
  corporate ticket, Carol with a comp speaker ticket.
- **Carts** -- An open cart for Bob with an individual ticket and two t-shirts.
- **Credits** -- A $25 store credit for Alice.
- **Activities** -- Django Sprint, Newcomer Orientation, Open Source Workshop,
  Lightning Talks.
- **Travel Grants** -- One application in each status (submitted, accepted, offered,
  rejected, withdrawn) with realistic data.

This is for local development and demos only.
