"""Generate typed Python models from the Pretalx OpenAPI schema.

Uses ``datamodel-code-generator`` to parse ``schemas/pretalx/schema.yml``
and output generated dataclass models into
``packages/pretalx-client/src/pretalx_client/generated/``.
"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_FILE = PROJECT_ROOT / "schemas" / "pretalx" / "schema.yml"
OUTPUT_DIR = PROJECT_ROOT / "packages" / "pretalx-client" / "src" / "pretalx_client" / "generated"


def main() -> None:
    """Run datamodel-code-generator against the Pretalx OpenAPI schema."""
    if not SCHEMA_FILE.exists():
        print(f"FAIL: Schema file not found at {SCHEMA_FILE}", file=sys.stderr)
        print("  Run `make pretalx-fetch-schema` first.", file=sys.stderr)
        raise SystemExit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Generating models from {SCHEMA_FILE.relative_to(PROJECT_ROOT)} ...")
    print(f"  Output: {OUTPUT_DIR.relative_to(PROJECT_ROOT)}/")

    cmd = [
        sys.executable,
        "-m",
        "datamodel_code_generator",
        "--input",
        str(SCHEMA_FILE),
        "--input-file-type",
        "openapi",
        "--output",
        str(OUTPUT_DIR / "models.py"),
        "--output-model-type",
        "dataclasses.dataclass",
        "--target-python-version",
        "3.14",
        "--use-standard-collections",
        "--use-union-operator",
        "--collapse-root-models",
        "--field-constraints",
        "--strict-nullable",
        "--use-double-quotes",
        "--wrap-string-literal",
    ]

    print(f"  Running: {' '.join(cmd[-10:])}")
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)

    if result.returncode != 0:
        print("FAIL: datamodel-code-generator exited with errors", file=sys.stderr)
        if result.stdout:
            print(result.stdout, file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)

    if result.stdout:
        print(result.stdout)

    init_file = OUTPUT_DIR / "__init__.py"
    if not init_file.exists():
        init_file.write_text('"""Generated Pretalx API models from OpenAPI schema."""\n')
        print(f"  Created {init_file.relative_to(PROJECT_ROOT)}")

    print("DONE: Models generated successfully")


if __name__ == "__main__":
    main()
