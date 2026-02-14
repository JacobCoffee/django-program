# pretalx-client

[![PyPI](https://img.shields.io/pypi/v/pretalx-client)](https://pypi.org/project/pretalx-client/)
[![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://jacobcoffee.github.io/django-program/pretalx-client/)

Standalone Python client for the [Pretalx](https://pretalx.com) REST API.

| Link | |
|------|---|
| PyPI | https://pypi.org/project/pretalx-client/ |
| Docs | https://jacobcoffee.github.io/django-program/pretalx-client/ |

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
