# Architecture & Internals

This document explains how the `pretalx-client` package is structured, why it is
structured that way, and what you need to know to work on it effectively.

## Three-layer design

The package is split into three layers. Each has a distinct responsibility and a
clear boundary with the layer above it.

```
  Your code
     |
     v
+--------------------------+
| PretalxClient            |  client.py + models.py
| (public API)             |  Frozen dataclasses, typed methods
+--------------------------+
     |  delegates HTTP to
     v
+--------------------------+
| adapters/                |  normalization.py, schedule.py, talks.py
| (normalization)          |  Multilingual fields, ID resolution, fallback logic
+--------------------------+
     |  consumes raw dicts from
     v
+--------------------------+
| generated/               |  http_client.py + models.py
| (auto-generated)         |  One method per OpenAPI endpoint, raw dataclasses
+--------------------------+
     |  uses
     v
   httpx
     |
     v
  Pretalx REST API
```

Data flows down as method calls and up as raw dicts that get progressively
refined into typed, frozen dataclasses.

### Layer 1: Generated (`generated/`)

Everything in this directory is machine-produced. Two scripts in the parent
`django-program` repo handle regeneration:

- **`scripts/pretalx/generate_client.py`** runs `datamodel-code-generator`
  against `schemas/pretalx/schema.yml` to produce `generated/models.py`. This
  file contains plain dataclasses like `Submission`, `Speaker`, `TalkSlot`, and
  `Room` that mirror the OpenAPI component schemas.

- **`scripts/pretalx/generate_http_client.py`** reads the same schema and emits
  `generated/http_client.py` containing `GeneratedPretalxClient`. This class has
  one method per `operationId` in the spec -- things like `speakers_list()`,
  `submissions_list()`, `slots_list()`, and `rooms_list()`. Every method returns
  raw `dict[str, Any]` or `list[dict[str, Any]]`.

`GeneratedPretalxClient` also provides the pagination and error-handling
primitives that the rest of the package depends on:

| Method               | Behavior                                                    |
|----------------------|-------------------------------------------------------------|
| `_request()`         | Single HTTP request, raises `RuntimeError` on failure       |
| `_request_or_none()` | Same, but returns `None` on 404                             |
| `_paginate()`        | Follows `next` links across all pages, returns flat list    |
| `_paginate_or_none()`| Same, but returns `None` if the first page is 404           |

Pagination works by reusing a single `httpx.Client` session and clearing query
params after the first request (subsequent pages encode params in the `next`
URL).

**Do not edit generated files by hand.** Regenerate them:

```bash
# From the django-program root:
uv run python scripts/pretalx/generate_client.py      # models.py
uv run python scripts/pretalx/generate_http_client.py  # http_client.py
```

The `generated/__init__.py` re-exports the types that the adapter and client
layers actually use, aliased with `Generated` prefixes to avoid name collisions:

```python
from pretalx_client.generated.models import Speaker as GeneratedSpeaker
from pretalx_client.generated.models import Submission as GeneratedSubmission
from pretalx_client.generated.models import TalkSlot as GeneratedTalkSlot
# etc.
```

### Layer 2: Adapters (`adapters/`)

The Pretalx API has a few behaviors that make a raw generated client painful to
use directly. The adapter layer exists to absorb those quirks.

#### `normalization.py` -- multilingual fields and ID resolution

Pretalx represents localizable text in two ways depending on the endpoint and
authentication level:

```python
# Sometimes a plain string:
{"name": "Main Hall"}

# Sometimes a language-keyed dict:
{"name": {"en": "Main Hall", "de": "Hauptsaal"}}
```

`localized()` handles both. It prefers the `"en"` key, falls back to the first
available value, and returns `""` for `None`. It also recurses into nested
`{"name": {...}}` structures that appear in some responses.

A related problem is foreign-key fields. The real (authenticated) API returns
integer IDs for `submission_type`, `track`, `room`, and `tags`. The public API
sometimes returns inline objects instead. `resolve_id_or_localized()` accepts
either form:

```python
# Integer ID with a mapping dict:
resolve_id_or_localized(42, {42: "Tutorial"})  # "Tutorial"

# Localized dict without a mapping:
resolve_id_or_localized({"en": "Tutorial"})    # "Tutorial"

# None:
resolve_id_or_localized(None)                  # ""
```

`resolve_many_ids_or_localized()` does the same for lists (used by `tags`).

#### `schedule.py` -- slot normalization and datetime parsing

Two slot formats exist in the wild:

| Field     | Legacy format (`/schedules/latest/`) | Paginated format (`/slots/`) |
|-----------|--------------------------------------|------------------------------|
| Room      | `"room": "Main Hall"` (string)       | `"room": 7` (integer ID)    |
| Talk ref  | `"code": "ABC123"`                   | `"submission": "ABC123"`     |
| Title     | `"title": "My Talk"` present         | Not present                  |

`normalize_slot()` unifies both into a consistent dict with keys `room`,
`start`, `end`, `code`, `title`, `start_dt`, and `end_dt`. The room value goes
through `resolve_id_or_localized()`, so it works with both strings and IDs.

`parse_datetime()` is a thin wrapper around `datetime.fromisoformat()` that
returns `None` instead of raising on bad input.

#### `talks.py` -- the talks endpoint fallback

This adapter encapsulates a real-world compatibility problem.
`fetch_talks_with_fallback()` implements a two-step strategy:

1. Try `GET /api/events/{slug}/talks/`
2. If that returns 404, fall back to fetching
   `GET /api/events/{slug}/submissions/?state=confirmed` and
   `GET /api/events/{slug}/submissions/?state=accepted`, then concatenate the
   results.

The fallback exists because some Pretalx instances -- including PyCon US -- do
not expose the `/talks/` endpoint at all. The submissions endpoint returns the
same data in a slightly different shape, and the rest of the normalization
pipeline handles the differences.

The function takes a `PretalxClient` instance and calls its `_get_paginated()`
and `_get_paginated_or_none()` methods directly. It returns raw dicts; the
caller is responsible for converting them into `PretalxTalk` instances.

### Layer 3: Client (`client.py` + `models.py`)

This is the public API. Consumers import `PretalxClient`, `PretalxSpeaker`,
`PretalxTalk`, `PretalxSlot`, and `SubmissionState` from the package root.

#### `PretalxClient`

Constructed with an event slug, optional base URL, and optional API token:

```python
client = PretalxClient("pycon-us-2026", api_token="abc123")
```

Internally it creates a `GeneratedPretalxClient` and delegates all HTTP through
it. The public methods -- `fetch_speakers()`, `fetch_talks()`,
`fetch_schedule()`, etc. -- call generated methods to get raw dicts, then pass
them through the appropriate `from_api()` classmethods on the model dataclasses.

For talks specifically, `fetch_talks()` routes through
`fetch_talks_with_fallback()` in the adapter layer before constructing
`PretalxTalk` instances.

The client also provides `_fetch_id_name_mapping()`, which fetches lookup tables
from endpoints like `/rooms/`, `/submission-types/`, `/tracks/`, and `/tags/`.
These mappings are `dict[int, str]` and get passed into `from_api()` calls so
integer IDs can be resolved to human-readable names.

#### Model dataclasses

All three model classes (`PretalxSpeaker`, `PretalxTalk`, `PretalxSlot`) are
frozen, slotted dataclasses. Each has a `from_api()` classmethod that:

1. Tries to parse the raw dict through the corresponding generated dataclass
   via `_parse_generated()`.
2. If that succeeds, extracts and normalizes fields from the generated instance.
3. If that fails (returns `None`), falls back to direct dict access with
   sensible defaults.

This two-path design is the core resilience mechanism. The generated dataclasses
capture the "expected" API shape from the OpenAPI spec, but the real API
frequently deviates -- extra fields, missing fields, different types for the same
field across endpoints. The fallback path handles all of that.

#### `_parse_generated()`

This function is worth understanding in detail:

```python
def _parse_generated[T](cls: type[T], data: dict[str, Any]) -> T | None:
    field_names = {f.name for f in _dc.fields(cls)}
    filtered = {k: v for k, v in data.items() if k in field_names}
    return cls(**filtered)  # or None on any exception
```

It filters the raw dict to only the fields the generated dataclass declares,
then tries to construct an instance. If construction fails for any reason --
wrong types, missing required fields, unexpected values -- it returns `None` and
logs a debug message. The caller then falls back to manual dict extraction.

This makes the package forward-compatible with API changes: new fields get
ignored, removed fields trigger the fallback, and renamed fields still work
through the dict path.

## Request flow in practice

A typical `fetch_talks()` call traverses the entire stack:

```
client.fetch_talks(submission_types={1: "Talk"}, rooms={7: "Main Hall"})
   |
   +--> fetch_talks_with_fallback(client)          [adapters/talks.py]
   |       |
   |       +--> client._get_paginated_or_none()    [client.py]
   |       |       |
   |       |       +--> self._http._paginate_or_none()  [generated/http_client.py]
   |       |               |
   |       |               +--> httpx.Client.get()      GET /api/events/{slug}/talks/
   |       |               |
   |       |               +--> (follows "next" links until exhausted)
   |       |
   |       +--> (if 404: fall back to /submissions/?state=confirmed + accepted)
   |       |
   |       +--> returns list[dict]
   |
   +--> for each raw dict:
           |
           +--> PretalxTalk.from_api(item, submission_types=..., rooms=...)  [models.py]
                   |
                   +--> _parse_generated(GeneratedSubmission, item)
                   |       |
                   |       +--> filters dict to Submission fields
                   |       +--> constructs GeneratedSubmission or returns None
                   |
                   +--> resolve_id_or_localized(raw.submission_type, {1: "Talk"})
                   |       [adapters/normalization.py]
                   |
                   +--> returns frozen PretalxTalk(code="ABC", title="...", ...)
```

## Key design decisions

### Why generated code at all?

The Pretalx API has 50+ endpoints. Writing HTTP methods for each by hand is
tedious and error-prone. The generated client guarantees complete endpoint
coverage and correct URL construction. When Pretalx adds endpoints, regenerating
picks them up automatically.

### Why not use the generated models directly?

Three reasons:

1. **API inconsistency.** The OpenAPI spec describes the "ideal" response shape.
   Real responses diverge: `avatar` vs `avatar_url`, speakers as strings vs
   dicts, integer IDs vs inline objects. The handwritten models absorb this.

2. **Consumer ergonomics.** The generated `Submission` dataclass has 17 fields
   including `slots: list[int]` and `answers: list[int]` that consumers never
   need. `PretalxTalk` has 12 fields, all resolved to human-readable strings.

3. **Stability.** Regenerating the generated layer is safe because the public
   models are a separate, handwritten contract. Internal refactors to the
   generated code don't break consumers.

### Why frozen dataclasses?

Immutability. Once a `PretalxTalk` is constructed, it cannot be accidentally
mutated. This makes the objects safe to cache, pass between threads, and use as
dict keys. The `slots=True` option reduces memory footprint.

### Why not pydantic?

This package depends only on `httpx`. No pydantic, no attrs, no Django. Stdlib
`dataclasses` plus `datamodel-code-generator` keeps the dependency tree minimal,
which matters because this package is also used as a standalone library outside
of `django-program`.

## File reference

| File | Purpose |
|------|---------|
| `__init__.py` | Re-exports `PretalxClient`, `PretalxSpeaker`, `PretalxTalk`, `PretalxSlot`, `SubmissionState` |
| `client.py` | `PretalxClient` -- public HTTP client with typed methods |
| `models.py` | Frozen dataclasses with `from_api()` constructors, `SubmissionState` enum, `_parse_generated()` |
| `adapters/__init__.py` | Re-exports adapter functions |
| `adapters/normalization.py` | `localized()`, `resolve_id_or_localized()`, `resolve_many_ids_or_localized()` |
| `adapters/schedule.py` | `parse_datetime()`, `normalize_slot()` |
| `adapters/talks.py` | `fetch_talks_with_fallback()` |
| `generated/__init__.py` | Re-exports generated types with `Generated` prefix aliases |
| `generated/http_client.py` | `GeneratedPretalxClient` -- one method per OpenAPI endpoint |
| `generated/models.py` | Generated dataclasses (`Submission`, `Speaker`, `TalkSlot`, `Room`, `StateEnum`, etc.) |
