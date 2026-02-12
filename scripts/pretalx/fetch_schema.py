"""Download the Pretalx OpenAPI schema and compute a SHA256 checksum.

Fetches the official Pretalx OpenAPI 3.0.3 schema YAML from
``https://docs.pretalx.org/schema.yml``, writes it to
``schemas/pretalx/schema.yml``, and stores the SHA256 digest in
``schemas/pretalx/schema.sha256``.
"""

import hashlib
import sys
from pathlib import Path

import httpx

SCHEMA_URL = "https://docs.pretalx.org/schema.yml"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_DIR = PROJECT_ROOT / "schemas" / "pretalx"
SCHEMA_FILE = SCHEMA_DIR / "schema.yml"
CHECKSUM_FILE = SCHEMA_DIR / "schema.sha256"


def main() -> None:
    """Fetch the Pretalx OpenAPI schema and write a SHA256 checksum file."""
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Downloading {SCHEMA_URL} ...")
    try:
        response = httpx.get(SCHEMA_URL, timeout=60, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        print(f"FAIL: HTTP {exc.response.status_code} from {SCHEMA_URL}", file=sys.stderr)
        raise SystemExit(1) from exc
    except httpx.RequestError as exc:
        print(f"FAIL: Connection error fetching {SCHEMA_URL}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    content = response.content
    SCHEMA_FILE.write_bytes(content)
    print(f"  Wrote {len(content):,} bytes to {SCHEMA_FILE.relative_to(PROJECT_ROOT)}")

    digest = hashlib.sha256(content).hexdigest()
    CHECKSUM_FILE.write_text(f"{digest}  schema.yml\n")
    print(f"  SHA256: {digest}")
    print(f"  Wrote checksum to {CHECKSUM_FILE.relative_to(PROJECT_ROOT)}")
    print("DONE")


if __name__ == "__main__":
    main()
