# Installation

## Requirements

django-program requires **Python 3.14+** and **Django 5.2+**. The Python 3.14 minimum
exists because the package uses [PEP 649](https://peps.python.org/pep-0649/) deferred
evaluation of annotations, which landed in CPython 3.14. There is no backport and no
`from __future__ import annotations` workaround -- you need 3.14.

## Install the package

With uv (recommended):

```bash
uv add django-program
```

With pip:

```bash
pip install django-program
```

## Add the Django apps

django-program ships six Django apps. Add all of them to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # Django defaults
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # django-program
    "django_program.conference",
    "django_program.registration",
    "django_program.pretalx",
    "django_program.sponsors",
    "django_program.programs",
    "django_program.manage",
]
```

Each app handles a distinct part of the conference lifecycle:

| App | What it does |
|---|---|
| `conference` | Core conference model, sections, the `bootstrap_conference` management command |
| `registration` | Ticket types, add-ons, carts, orders, payments, vouchers |
| `pretalx` | Speaker, talk, room, and schedule slot models synced from Pretalx |
| `sponsors` | Sponsor levels, sponsor profiles, benefits, comp ticket vouchers |
| `programs` | Activities (sprints, tutorials, open spaces), signups, travel grants |
| `manage` | Organizer dashboard with SSE-powered import and sync UI |

## Configure `DJANGO_PROGRAM`

Add a `DJANGO_PROGRAM` dictionary to your Django settings. At minimum you need Stripe
keys if you plan to sell tickets, and a Pretalx token if you plan to sync schedules:

```python
DJANGO_PROGRAM = {
    "stripe": {
        "secret_key": "sk_test_...",
        "publishable_key": "pk_test_...",
        "webhook_secret": "whsec_...",
    },
    "pretalx": {
        "base_url": "https://pretalx.com",
        "token": "your-pretalx-api-token",
    },
    "currency": "USD",
    "currency_symbol": "$",
}
```

If you only need some features (say, just sponsor management without ticket sales),
you can leave the irrelevant sections out. The config uses frozen dataclasses with
sensible defaults -- see the [Configuration](../configuration.md) page for the full
reference.

## URL configuration

Wire up the URL patterns in your root `urls.py`:

```python
from django.urls import include, path

urlpatterns = [
    # ... your other URLs
    path("manage/", include("django_program.manage.urls")),
    path("<slug:conference_slug>/register/", include("django_program.registration.urls")),
    path("<slug:conference_slug>/program/", include("django_program.pretalx.urls")),
    path("<slug:conference_slug>/sponsors/", include("django_program.sponsors.urls")),
    path("<slug:conference_slug>/programs/", include("django_program.programs.urls")),
]
```

The `<slug:conference_slug>` prefix means each conference gets its own URL namespace.
The `manage/` dashboard sits outside that prefix since organizers may manage multiple
conferences.

## Run migrations

```bash
python manage.py migrate
```

This creates all the tables for conferences, tickets, orders, speakers, sponsors, and
program activities.

## Template configuration

django-program ships its own templates. Make sure your `TEMPLATES` setting includes
app directories so Django can find them:

```python
import django_program

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [Path(django_program.__file__).resolve().parent / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]
```

## Field encryption

The registration app uses
[django-fernet-encrypted-fields](https://pypi.org/project/django-fernet-encrypted-fields/)
for sensitive payment data. Set the encryption key in your settings:

```python
FIELD_ENCRYPTION_KEY = "your-fernet-key-here"
```

Generate one with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## What's next

Head to the [Quickstart](quickstart.md) to bootstrap a full conference from a TOML
file and see the management dashboard in action.
