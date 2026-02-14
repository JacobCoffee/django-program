# Installation

## Requirements

- Python 3.14+
- [httpx](https://www.python-httpx.org/) (installed automatically)

That's it. No Django, no ORM, no heavy framework.

## Install with uv

```bash
uv add pretalx-client
```

## Install with pip

```bash
pip install pretalx-client
```

## Verify the install

```python
from pretalx_client import PretalxClient

client = PretalxClient("pycon-us-2026")
print(client.api_url)
# https://pretalx.com/api/events/pycon-us-2026/
```

If you're using `pretalx-client` as part of [django-program](https://github.com/JacobCoffee/django-program), it's already included as a workspace dependency -- no extra install needed.

## Authentication

Most Pretalx data is publicly accessible, but some fields (speaker emails, draft submissions) require an API token. You can generate one from your Pretalx user profile under **Settings > API tokens**.

Pass it when constructing the client:

```python
client = PretalxClient(
    "pycon-us-2026",
    api_token="your-pretalx-api-token",
)
```

Without a token, the client still works -- you just won't see restricted fields.
