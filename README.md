# django-program

[![PyPI](https://img.shields.io/pypi/v/django-program)](https://pypi.org/project/django-program/)
[![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://jacobcoffee.github.io/django-program/)
[![CI](https://github.com/JacobCoffee/django-program/actions/workflows/ci.yml/badge.svg)](https://github.com/JacobCoffee/django-program/actions/workflows/ci.yml)

Modern conference management for Django — registration, ticketing, Pretalx schedule sync, sponsors, and program activities.
> [!WARNING]  
> This is almost 80% vibe coded. My plan is to build out this proof-of-concept to migrate off of Symposion, Registrasion, and Pinax-Stripe
> to something that fits better and flows better.
> Then contract or hire someone to flesh this out as a literal package with real security and perf reviews.
> So... use at your own risk :)


| Link | |
|------|---|
| PyPI | https://pypi.org/project/django-program/ |
| Docs | https://jacobcoffee.github.io/django-program/ |
| pretalx-client PyPI | https://pypi.org/project/pretalx-client/ |
| pretalx-client Docs | https://jacobcoffee.github.io/django-program/pretalx-client/ |

Inspirations:
- [Symposion](https://github.com/pinax/symposion)
- [Registrasion](https://github.com/chrisjrn/registrasion)

## Example Dev Server

A runnable Django project lives in `examples/` for interacting with models via the admin, shell, and management commands.

```bash
make dev
# Visit http://localhost:8000/admin/  (login: admin/admin)
```

Or step by step:

```bash
uv run python examples/manage.py migrate
uv run python examples/manage.py bootstrap_conference --config conference.example.toml
uv run python examples/manage.py createsuperuser
uv run python examples/manage.py runserver
```
