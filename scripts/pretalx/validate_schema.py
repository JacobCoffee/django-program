"""Validate the local Pretalx OpenAPI schema and its checksum.

Loads ``schemas/pretalx/schema.yml``, verifies its SHA256 digest against
``schemas/pretalx/schema.sha256``, and checks that the YAML contains the
required top-level OpenAPI 3.x keys (``openapi``, ``info``, ``paths``).
"""

import hashlib
import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_DIR = PROJECT_ROOT / "schemas" / "pretalx"
SCHEMA_FILE = SCHEMA_DIR / "schema.yml"
CHECKSUM_FILE = SCHEMA_DIR / "schema.sha256"


def _validate_checksum() -> bool:
    """Verify the schema file matches its stored SHA256 checksum.

    Returns:
        ``True`` if the computed digest matches the stored one.
    """
    if not CHECKSUM_FILE.exists():
        print("FAIL: Checksum file not found. Run fetch_schema.py first.", file=sys.stderr)
        return False

    stored_line = CHECKSUM_FILE.read_text().strip()
    # Format: "<hex_digest>  <filename>"
    stored_digest = stored_line.split()[0]

    content = SCHEMA_FILE.read_bytes()
    computed_digest = hashlib.sha256(content).hexdigest()

    if computed_digest != stored_digest:
        print("FAIL: Checksum mismatch", file=sys.stderr)
        print(f"  Expected: {stored_digest}", file=sys.stderr)
        print(f"  Got:      {computed_digest}", file=sys.stderr)
        return False

    print(f"  Checksum OK: {computed_digest}")
    return True


def _validate_openapi_structure(data: dict[str, Any]) -> bool:
    """Check that the parsed YAML has required OpenAPI 3.x top-level keys.

    Args:
        data: The parsed YAML document as a dict.

    Returns:
        ``True`` if all required keys are present and the version looks valid.
    """
    required_keys = ("openapi", "info", "paths")
    missing = [key for key in required_keys if key not in data]
    if missing:
        print(f"FAIL: Missing required OpenAPI keys: {', '.join(missing)}", file=sys.stderr)
        return False

    version = str(data["openapi"])
    if not version.startswith("3."):
        print(f"FAIL: Expected OpenAPI 3.x, got '{version}'", file=sys.stderr)
        return False

    print(f"  OpenAPI version: {version}")
    print(f"  Info title: {data['info'].get('title', '(none)')}")
    print(f"  Paths defined: {len(data['paths'])}")
    return True


def main() -> None:
    """Validate the Pretalx OpenAPI schema file and checksum."""
    if not SCHEMA_FILE.exists():
        print(f"FAIL: Schema file not found at {SCHEMA_FILE}", file=sys.stderr)
        raise SystemExit(1)

    print(f"Validating {SCHEMA_FILE.relative_to(PROJECT_ROOT)} ...")

    checksum_ok = _validate_checksum()

    with SCHEMA_FILE.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        print("FAIL: Schema YAML did not parse to a mapping", file=sys.stderr)
        raise SystemExit(1)

    structure_ok = _validate_openapi_structure(data)

    if checksum_ok and structure_ok:
        print("PASS: Schema is valid OpenAPI 3.x with matching checksum")
    else:
        print("FAIL: Validation failed", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
