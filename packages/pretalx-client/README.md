# pretalx-client

Standalone Python client for the [Pretalx](https://pretalx.com) REST API.

## Installation

```bash
pip install pretalx-client
```

## Usage

```python
from pretalx_client import PretalxClient

client = PretalxClient("pycon-us-2026", api_token="your-token")

speakers = client.fetch_speakers()
talks = client.fetch_talks()
schedule = client.fetch_schedule()
```

## Features

- Typed dataclass responses (`PretalxSpeaker`, `PretalxTalk`, `PretalxSlot`)
- Automatic pagination handling
- Multilingual field resolution
- Fallback from `/talks/` to `/submissions/` when the talks endpoint is unavailable
- Support for authenticated and public API access

## Requirements

- Python 3.14+
- httpx

## License

MIT
