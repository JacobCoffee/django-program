# Pretalx Integration

This document covers the architecture of the `pretalx-client` package, how to
regenerate it from the upstream OpenAPI schema, the compatibility guarantees it
provides, and the rollout plan for publishing it as a standalone library.

## Architecture Overview

The Pretalx integration is organized into three layers, each with a distinct
responsibility:

```
packages/pretalx-client/src/pretalx_client/
+-- generated/          # Layer 1: Codegen output (DO NOT EDIT)
|   +-- models.py       #   datamodel-code-generator output
+-- adapters/           # Layer 2: Runtime quirk handling
|   +-- normalization.py #   Multilingual field resolution, ID-to-name mapping
+-- models.py           # Layer 2: Typed dataclasses (PretalxSpeaker, PretalxTalk, PretalxSlot)
+-- client.py           # Layer 3: Stable public API (PretalxClient)
+-- __init__.py          # Public re-exports
```

### Layer 1: Generated Models

Output of `datamodel-code-generator` run against the Pretalx OpenAPI 3.0.3
schema. Located in `packages/pretalx-client/src/pretalx_client/generated/`.
These files are machine-generated and must never be edited by hand -- they are
overwritten on every schema sync.

### Layer 2: Adapters and Typed Models

Handwritten code that compensates for runtime behavior not captured in the
OpenAPI schema:

- **`models.py`** -- Frozen dataclasses (`PretalxSpeaker`, `PretalxTalk`,
  `PretalxSlot`) with `from_api()` class methods that normalize raw API dicts
  into well-typed Python objects. Handles multilingual field resolution,
  ID-to-name mapping, and datetime parsing.
- **`adapters/normalization.py`** -- Standalone helpers (`localized()`,
  `resolve_id_or_localized()`) for resolving Pretalx's multilingual and
  integer-ID field patterns.

These files are maintained manually and are the primary place to handle new
API quirks as they are discovered.

### Layer 3: Client Facade

`PretalxClient` in `client.py` is the stable public API. It provides methods
like `fetch_speakers()`, `fetch_talks()`, and `fetch_schedule()` that return
typed dataclasses. Consumers (including the Django sync service) import from
here and should not depend on generated code or adapter internals directly.

### Django Integration

`src/django_program/pretalx/sync.py` contains `PretalxSyncService`, which
consumes `PretalxClient` and maps the typed dataclasses into Django ORM models
(`Speaker`, `Talk`, `ScheduleSlot`, `Room`). The re-export shim at
`src/django_program/pretalx/client.py` bridges the workspace package into the
Django app's import namespace.

## Schema Regeneration

### Prerequisites

- `uv` installed and project dependencies synced (`uv sync --all-groups`)
- Internet access (fetches from `https://docs.pretalx.org/schema.yml`)

### Running the Pipeline

```bash
make pretalx-sync-schema
```

This single command chains three steps:

1. **Fetch** (`make pretalx-fetch-schema`) -- Downloads the OpenAPI schema from
   `https://docs.pretalx.org/schema.yml` into `schemas/pretalx/schema.yml` and
   writes a SHA256 checksum to `schemas/pretalx/schema.sha256`.

2. **Validate** (`make pretalx-validate-schema`) -- Verifies the SHA256
   checksum matches, checks for required OpenAPI 3.x top-level keys (`openapi`,
   `info`, `paths`), and prints a summary of the schema contents.

3. **Generate** (`make pretalx-generate-client`) -- Runs
   `datamodel-code-generator` against the downloaded schema and writes Python
   dataclass models to
   `packages/pretalx-client/src/pretalx_client/generated/models.py`. Generator
   options include `--target-python-version 3.14`, `--use-union-operator`, and
   `--output-model-type dataclasses.dataclass`.

### Automated Schema Drift Detection

A GitHub Actions workflow (`.github/workflows/pretalx-schema-sync.yml`) runs
weekly on Monday at 06:00 UTC. It executes the full `make pretalx-sync-schema`
pipeline and, if any files changed, opens a pull request on the
`chore/pretalx-schema-sync` branch. The workflow can also be triggered manually
via `workflow_dispatch`.

### After Regeneration

If the generated models changed:

1. Run `make ci` to verify lint, formatting, type-checks, and tests pass.
2. Review the diff in `generated/models.py` for any breaking changes to field
   names or types that would affect the adapter layer.
3. Update `models.py` and `client.py` if new fields need to be surfaced through
   the typed dataclasses.
4. Update `sync.py` on the Django side if the domain model mapping needs to
   change.

## Compatibility Guarantees

### What is Stable

The **client facade** (`PretalxClient` and the typed dataclasses exported from
`pretalx_client`) provides a stable API. Consumers can depend on:

- Method signatures: `fetch_speakers()`, `fetch_talks()`, `fetch_schedule()`,
  `fetch_rooms()`, `fetch_submissions()`, `fetch_events()`
- Return types: `list[PretalxSpeaker]`, `list[PretalxTalk]`, `list[PretalxSlot]`
- Dataclass field names and types on `PretalxSpeaker`, `PretalxTalk`,
  `PretalxSlot`

### What May Change

- **Generated code** (`generated/`) is regenerated from upstream and may change
  at any time. Do not import from `pretalx_client.generated` directly.
- **Adapter internals** (`adapters/`) are implementation details. The public
  helpers `localized()` and `resolve_id_or_localized()` are available but not
  part of the semver contract.

### What the Adapters Handle

The adapters exist because the real Pretalx API behaves differently from what
the OpenAPI schema documents. These runtime quirks are not bugs to report
upstream -- they are intentional behavior that varies by Pretalx instance
configuration and event setup.

## Known Non-Schema Runtime Quirks

The following behaviors are observed in production Pretalx instances but are not
documented in the OpenAPI schema. The adapter layer handles all of them
transparently.

### Multilingual Fields Return Variable Types

Pretalx localized fields (`name`, `title`, `abstract`, etc.) return either a
plain `str` or a `dict[str, str]` keyed by language code, depending on the
instance's `Accept-Language` header handling and localization configuration.

```python
# When the instance has a single language:
{"title": "My Talk"}

# When the instance has multiple languages:
{"title": {"en": "My Talk", "de": "Mein Vortrag"}}
```

The `_localized()` helper resolves both forms, preferring the `en` key when
available.

### ID Fields vs. Inline Objects

The `submission_type`, `track`, and `room` fields on submissions may be returned
as integer IDs or as localized inline objects, depending on whether the request
is authenticated and which API version the instance runs.

```python
# Integer ID form (common with API tokens):
{"submission_type": 42, "track": 7, "room": 3}

# Inline object form (common with public/unauthenticated access):
{"submission_type": {"en": "Talk"}, "track": {"en": "Web"}, "room": {"en": "Main Hall"}}
```

The `_resolve_id_or_localized()` helper handles both. When IDs are returned, the
client pre-fetches `/submission-types/`, `/tracks/`, and `/rooms/` endpoints to
build lookup tables.

### `/talks/` Endpoint Returns 404

Some Pretalx events (notably PyCon US) do not expose the `/talks/` endpoint at
all, returning HTTP 404. The client falls back to
`/submissions/?state=confirmed` combined with `/submissions/?state=accepted` to
capture all scheduled content including tutorials and sponsor workshops.

```python
# The client handles this automatically:
talks = client.fetch_talks()  # tries /talks/, falls back to /submissions/
```

### `/slots/` Uses Different Field Names

The paginated `/slots/` endpoint returns slot objects with different keys than
the legacy `/schedules/latest/` response:

- Uses `submission` instead of `code` to reference the linked talk
- Does not include a `title` field (the title must be looked up from the talk)
- Returns `room` as an integer ID rather than a name string

The `PretalxSlot.from_api()` method handles both formats.

### Speaker Avatar Field Name Varies

Different Pretalx instances use either `avatar_url` or `avatar` for the speaker
profile image URL. `PretalxSpeaker.from_api()` checks both keys.

## Rollout Checklist

### Versioning

The `pretalx-client` package follows [semver](https://semver.org/):

| Change Type | Version Bump | Example |
|---|---|---|
| Generated code regeneration (no adapter changes) | Patch | `0.1.0` -> `0.1.1` |
| New adapter/facade features (backward-compatible) | Minor | `0.1.1` -> `0.2.0` |
| Breaking changes to facade API | Major | `0.2.0` -> `1.0.0` |

Generated code changes alone are patch bumps because the facade API remains
stable. If a schema change requires adapter updates that alter the public
dataclass fields, that is a minor or major bump depending on backward
compatibility.

### Release Process

The package will be published to PyPI from its own repository at
`github.com/JacobCoffee/pretalx-client`. The release flow:

1. Bump the version in `packages/pretalx-client/pyproject.toml`:
   ```bash
   cd packages/pretalx-client
   uv version --bump patch  # or minor/major
   ```
2. Run `make ci` to verify everything passes.
3. Commit and tag:
   ```bash
   git add packages/pretalx-client/pyproject.toml
   git commit -m "chore: bump pretalx-client to X.Y.Z"
   git tag pretalx-client-vX.Y.Z
   git push origin main --tags
   ```
4. The tag triggers a publish workflow that builds and uploads to PyPI.

### Migration from In-Tree Client

Currently, `src/django_program/pretalx/client.py` is a **re-export shim** that
imports everything from the `pretalx_client` workspace package and re-exports it
under the `django_program.pretalx.client` namespace:

```python
# src/django_program/pretalx/client.py (current shim)
from pretalx_client.client import PretalxClient
from pretalx_client.models import PretalxSpeaker, PretalxTalk, PretalxSlot, ...
```

This allows existing code in `sync.py` and elsewhere to continue importing from
`django_program.pretalx.client` without changes.

**Migration path:**

1. **Now (workspace phase):** The shim exists. All Django-side code imports from
   `django_program.pretalx.client`. The `pretalx-client` package is resolved via
   `[tool.uv.sources]` as a workspace member.

2. **When published to PyPI:** Remove the `[tool.uv.sources]` workspace override
   so `uv` resolves `pretalx-client` from PyPI instead. The shim continues to
   work -- no code changes needed in consumers.

3. **Eventually:** Update imports in `sync.py` and other Django code to import
   directly from `pretalx_client`:
   ```python
   # Before:
   from django_program.pretalx.client import PretalxClient
   # After:
   from pretalx_client import PretalxClient
   ```
   Then remove the shim file entirely.

### uv Sources Strategy

The `pyproject.toml` at the project root uses `[tool.uv.sources]` to bridge
development and production:

```toml
# During development: resolve from workspace
[tool.uv.sources]
pretalx-client = { workspace = true }

[tool.uv.workspace]
members = ["packages/*"]
```

```toml
# In production (after PyPI publish): remove the sources override
# uv will resolve pretalx-client from PyPI using the version in [project.dependencies]
[project]
dependencies = [
    "pretalx-client>=0.1.0",
]
```

The workspace member at `packages/pretalx-client/` has its own `pyproject.toml`
with independent versioning. During development, `uv sync` links it as an
editable install. In CI and production, once the sources override is removed,
`uv` fetches the published wheel from PyPI.
