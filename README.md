An attempt to modernize the conference workflow.

Inspirations
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
