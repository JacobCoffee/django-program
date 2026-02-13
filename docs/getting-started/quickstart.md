# Quickstart

This guide takes you from zero to a running conference in about five minutes.
By the end you will have ticket types, sponsor levels, and a management dashboard
you can log into.

## 1. Install django-program

```bash
uv add django-program
```

Or `pip install django-program` if you prefer pip.

## 2. Configure your Django project

Add the apps and settings as described in [Installation](installation.md). The short
version:

```python
# settings.py

INSTALLED_APPS = [
    # Django defaults ...
    "django_program.conference",
    "django_program.registration",
    "django_program.pretalx",
    "django_program.sponsors",
    "django_program.programs",
    "django_program.manage",
]

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

## 3. Add URL patterns

```python
# urls.py
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("manage/", include("django_program.manage.urls")),
    path("<slug:conference_slug>/register/", include("django_program.registration.urls")),
    path("<slug:conference_slug>/program/", include("django_program.pretalx.urls")),
    path("<slug:conference_slug>/sponsors/", include("django_program.sponsors.urls")),
    path("<slug:conference_slug>/programs/", include("django_program.programs.urls")),
]
```

## 4. Run migrations

```bash
python manage.py migrate
```

## 5. Bootstrap from a TOML config

django-program ships a management command that creates a full conference -- sections,
ticket types, add-ons, and sponsor levels -- from a single TOML file. The repo includes
an example config modeled on PyCon US.

Create a file called `conference.toml` (or copy `conference.example.toml` from the
repo):

```toml
[conference]
name = "PyCon US 2027"
start = 2027-05-14
end = 2027-05-22
timezone = "America/New_York"
venue = "David L. Lawrence Convention Center, Pittsburgh PA"
pretalx_event_slug = "pycon-us-2027"
website_url = "https://us.pycon.org/2027/"

[[conference.sections]]
name = "Tutorials"
start = 2027-05-14
end = 2027-05-15

[[conference.sections]]
name = "Talks"
start = 2027-05-16
end = 2027-05-18

[[conference.sections]]
name = "Sprints"
start = 2027-05-19
end = 2027-05-22

[[conference.tickets]]
name = "Individual"
price = 100.00
quantity = 2500
per_user = 1
available = { opens = 2025-01-15, closes = 2027-05-13 }

[[conference.tickets]]
name = "Corporate"
price = 350.00
quantity = 1000
per_user = 1
available = { opens = 2025-01-15, closes = 2027-05-13 }

[[conference.tickets]]
name = "Student"
price = 25.00
quantity = 500
per_user = 1
voucher_required = true
available = { opens = 2025-01-15, closes = 2027-05-13 }

[[conference.sponsor_levels]]
name = "Visionary"
cost = 150_000.00
comp_tickets = 25

[[conference.sponsor_levels]]
name = "Sustainability"
cost = 90_000.00
comp_tickets = 15

[[conference.sponsor_levels]]
name = "Contributing"
cost = 30_000.00
comp_tickets = 5
```

Now run the bootstrap command:

```bash
python manage.py bootstrap_conference --config conference.toml
```

This creates the `Conference` object, its `Section` entries, all `TicketType` and
`AddOn` records, and the `SponsorLevel` hierarchy. If you run it again with `--update`,
it will update existing records rather than duplicating them.

To also create demo data (sample orders, a test user, etc.):

```bash
python manage.py bootstrap_conference --config conference.toml --update --seed-demo
```

## 6. Set up permission groups

The management dashboard uses Django's built-in permission system. Run this command
to create the organizer groups:

```bash
python manage.py setup_groups
```

## 7. Create an admin user

```bash
python manage.py createsuperuser
```

## 8. Start the dev server

```bash
python manage.py runserver
```

Open `http://localhost:8000/manage/` in your browser and log in with your superuser
credentials. You should see the conference dashboard with your bootstrapped data.

The Django admin is at `http://localhost:8000/admin/` if you want to inspect or edit
records directly.

## Using the example dev server

If you cloned the django-program repo, there is a batteries-included dev server in
the `examples/` directory. It handles all the setup above automatically:

```bash
make dev
```

This wipes the SQLite database, runs migrations, bootstraps from
`conference.example.toml`, creates permission groups, creates an `admin/admin`
superuser, and starts the dev server on port 8000. Log in at
`http://localhost:8000/admin/` with `admin` / `admin`.

## What's next

- [Configuration](../configuration.md) -- Full reference for the `DJANGO_PROGRAM`
  settings dict and the TOML bootstrap schema
- [Registration Flow](../registration-flow.md) -- How the cart, checkout, and Stripe
  payment pipeline works
- [Pretalx Integration](../pretalx-integration.md) -- Syncing speakers and schedules
  from Pretalx
