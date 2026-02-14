# Quickstart

This guide walks through the main things you can do with `pretalx-client`.
Every example assumes you've created a client instance:

```python
from pretalx_client import PretalxClient

client = PretalxClient("pycon-us-2026", api_token="abc123")
```

If you're hitting a self-hosted Pretalx instance, pass `base_url`:

```python
client = PretalxClient(
    "my-event",
    base_url="https://pretalx.myconf.org",
    api_token="abc123",
)
```

## Fetching speakers

{func}`~pretalx_client.client.PretalxClient.fetch_speakers` returns a list of
{class}`~pretalx_client.models.PretalxSpeaker` dataclasses. Each one has a `code`,
`name`, `biography`, `avatar_url`, and a list of `submissions` codes they're
associated with.

```python
speakers = client.fetch_speakers()

for s in speakers:
    print(f"{s.name} ({s.code}) -- {len(s.submissions)} talks")
    if s.email:  # only populated with an API token
        print(f"  email: {s.email}")
```

## Fetching talks

{func}`~pretalx_client.client.PretalxClient.fetch_talks` returns
{class}`~pretalx_client.models.PretalxTalk` instances. Under the hood, it tries
the `/talks/` endpoint first. If that 404s (PyCon US's Pretalx instance does this),
it falls back to `/submissions/?state=confirmed` plus `?state=accepted` so you still
get all the scheduled content.

```python
talks = client.fetch_talks()

for t in talks:
    print(f"[{t.code}] {t.title}")
    print(f"  type={t.submission_type}  track={t.track}  state={t.state}")
```

### Resolving IDs to names

Pretalx's real API returns integer IDs for rooms, tracks, submission types, and tags.
The client can resolve these into human-readable names if you fetch the mappings first:

```python
rooms = client.fetch_rooms()
tracks = client.fetch_tracks()
sub_types = client.fetch_submission_types()
tags = client.fetch_tags()

talks = client.fetch_talks(
    rooms=rooms,
    tracks=tracks,
    submission_types=sub_types,
    tags=tags,
)

for t in talks:
    # t.submission_type is now "Talk" instead of 42
    # t.track is now "Web" instead of 7
    print(f"{t.title} ({t.submission_type}, {t.track})")
```

Without the mappings, integer fields stay as their string representation.

## Fetching the schedule

{func}`~pretalx_client.client.PretalxClient.fetch_schedule` hits the `/slots/`
endpoint and returns {class}`~pretalx_client.models.PretalxSlot` instances with
parsed `start_dt` / `end_dt` datetime objects.

```python
rooms = client.fetch_rooms()
schedule = client.fetch_schedule(rooms=rooms)

for slot in schedule:
    print(f"{slot.start} -- {slot.room}: {slot.code or '(break)'}")
```

## Listing events

Don't know the event slug? Use the classmethod
{func}`~pretalx_client.client.PretalxClient.fetch_events` to list everything
your token can see:

```python
events = PretalxClient.fetch_events(api_token="abc123")

for e in events:
    print(f"{e['slug']}: {e['name']}")
```

This returns raw dicts since event metadata doesn't have a dedicated dataclass.

## Fetching submissions by state

If you need more control than `fetch_talks`, use
{func}`~pretalx_client.client.PretalxClient.fetch_submissions` with an explicit
state filter:

```python
from pretalx_client import SubmissionState

drafts = client.fetch_submissions(state=SubmissionState.DRAFT)
withdrawn = client.fetch_submissions(state=SubmissionState.WITHDRAWN)
```

{class}`~pretalx_client.models.SubmissionState` is a `StrEnum` covering all
Pretalx lifecycle states: `SUBMITTED`, `ACCEPTED`, `REJECTED`, `CONFIRMED`,
`WITHDRAWN`, `CANCELED`, `DRAFT`, and `DELETED`.

## The dataclass contract

All response types are frozen, slotted dataclasses. They're constructed via
`from_api()` classmethods that validate the raw API dict through an
auto-generated OpenAPI model before adapting it into the consumer-friendly shape.
If the generated model can't handle a particular API response variation, the
classmethod falls back to direct dict extraction.

You don't need to call `from_api()` yourself -- the client methods handle it.
But if you're processing raw API data from another source, you can:

```python
from pretalx_client import PretalxSpeaker

raw = {"code": "ABC123", "name": "Guido", "biography": "BDFL emeritus"}
speaker = PretalxSpeaker.from_api(raw)
```
