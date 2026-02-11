"""Generate a typed HTTP client class from the Pretalx OpenAPI schema.

Reads ``schemas/pretalx/schema.yml`` and produces
``packages/pretalx-client/src/pretalx_client/generated/http_client.py``
containing :class:`GeneratedPretalxClient` with one method per ``operationId``.

The generated class handles pagination, authentication, and error handling so
the handwritten :class:`~pretalx_client.client.PretalxClient` can delegate to
it instead of building URLs and managing httpx directly.

No external dependencies beyond PyYAML (already a dev dep via datamodel-code-generator).
"""

import re
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_FILE = PROJECT_ROOT / "schemas" / "pretalx" / "schema.yml"
OUTPUT_DIR = PROJECT_ROOT / "packages" / "pretalx-client" / "src" / "pretalx_client" / "generated"
OUTPUT_FILE = OUTPUT_DIR / "http_client.py"


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

_PYTHON_KEYWORD = frozenset(
    {
        "False",
        "None",
        "True",
        "and",
        "as",
        "assert",
        "async",
        "await",
        "break",
        "class",
        "continue",
        "def",
        "del",
        "elif",
        "else",
        "except",
        "finally",
        "for",
        "from",
        "global",
        "if",
        "import",
        "in",
        "is",
        "lambda",
        "nonlocal",
        "not",
        "or",
        "pass",
        "raise",
        "return",
        "try",
        "while",
        "with",
        "yield",
    }
)


def sanitize_operation_id(raw: str) -> str:
    """Turn an arbitrary operationId into a valid Python identifier.

    Lowercases, replaces non-alphanum with ``_``, collapses runs of ``_``,
    strips leading/trailing ``_``, and appends ``_`` if the result is a
    Python keyword.
    """
    name = raw.lower().strip()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    if name in _PYTHON_KEYWORD or not name:
        name = f"{name}_"
    return name


def _patch_schema(schema: dict) -> dict:
    """Patch known bugs in the upstream Pretalx OpenAPI schema in-memory.

    - ``type: str`` -> ``type: string`` (15 occurrences)
    - ``operationId: "File upload"`` -> ``file_upload`` (sanitized later, but
      we normalize here to be safe)
    """
    raw = yaml.dump(schema, default_flow_style=False)
    # Fix `type: str` (must not match `type: string`)
    raw = re.sub(r"\btype: str\b(?!ing)", "type: string", raw)
    return yaml.safe_load(raw)


def _query_param_type(schema: dict) -> str:
    """Map an OpenAPI query param schema to a Python type hint string."""
    typ = schema.get("type", "string")
    if typ == "integer":
        return "int | None"
    if typ == "boolean":
        return "bool | None"
    if typ == "array":
        return "list[str] | None"
    return "str | None"


def _is_paginated(responses: dict) -> bool:
    """Return True if the 200 response references a Paginated*List schema."""
    resp_200 = responses.get("200", {})
    content = resp_200.get("content", {})
    json_schema = content.get("application/json", {}).get("schema", {})

    ref = json_schema.get("$ref", "")
    if "Paginated" in ref and "List" in ref:
        return True

    # Also check for allOf / oneOf wrapping
    for key in ("allOf", "oneOf", "anyOf"):
        for item in json_schema.get(key, []):
            ref = item.get("$ref", "")
            if "Paginated" in ref and "List" in ref:
                return True

    return False


def _is_delete(method: str, responses: dict) -> bool:
    """Return True if this is a delete operation (204 No Content)."""
    return method == "delete" or "204" in responses


def _has_request_body(operation: dict) -> bool:
    """Return True if the operation has a JSON request body."""
    body = operation.get("requestBody", {})
    content = body.get("content", {})
    return "application/json" in content


# ---------------------------------------------------------------------------
# Operation extraction
# ---------------------------------------------------------------------------


def extract_operations(schema: dict) -> list[dict]:
    """Extract all operations from the OpenAPI paths.

    Returns a list of dicts with keys: operation_id, method, path,
    path_params, query_params, paginated, has_body, is_delete, tag.
    """
    operations = []
    paths = schema.get("paths", {})

    for path, path_item in sorted(paths.items()):
        for method in ("get", "post", "put", "patch", "delete"):
            operation = path_item.get(method)
            if operation is None:
                continue

            raw_op_id = operation.get("operationId", "")
            if not raw_op_id:
                continue

            op_id = sanitize_operation_id(raw_op_id)

            path_params = []
            query_params = []
            for param in operation.get("parameters", []):
                p_name = param.get("name", "")
                p_in = param.get("in", "")
                p_schema = param.get("schema", {})

                if p_in == "path":
                    p_type = "int" if p_schema.get("type") == "integer" else "str"
                    path_params.append({"name": p_name, "type": p_type})
                elif p_in == "query":
                    query_params.append(
                        {
                            "name": p_name,
                            "type": _query_param_type(p_schema),
                        }
                    )

            responses = operation.get("responses", {})
            tags = operation.get("tags", [])

            operations.append(
                {
                    "operation_id": op_id,
                    "method": method,
                    "path": path,
                    "path_params": path_params,
                    "query_params": query_params,
                    "paginated": _is_paginated(responses),
                    "has_body": _has_request_body(operation),
                    "is_delete": _is_delete(method, responses),
                    "tag": tags[0] if tags else "other",
                }
            )

    return operations


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------

_FILE_HEADER = '''\
"""Auto-generated HTTP client for the Pretalx REST API.

Generated by ``scripts/pretalx/generate_http_client.py`` from the OpenAPI
schema at ``schemas/pretalx/schema.yml``.  Do not edit by hand.
"""

import http
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class GeneratedPretalxClient:
    """Low-level HTTP client with one method per Pretalx API endpoint.

    All methods return raw Python dicts/lists (not typed dataclasses).
    The higher-level :class:`~pretalx_client.client.PretalxClient` wraps
    these into typed models.

    Args:
        base_url: Root URL of the Pretalx instance (e.g. ``"https://pretalx.com"``).
        api_token: Optional API token for authenticated access.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str = "https://pretalx.com",
        api_token: str = "",
        timeout: int = 30,
    ) -> None:
        normalized = base_url.rstrip("/").removesuffix("/api")
        self.base_url = normalized
        self.api_token = api_token
        self.timeout = timeout
        self.headers: dict[str, str] = {"Accept": "application/json"}
        if api_token:
            self.headers["Authorization"] = f"Token {api_token}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a single HTTP request and return the JSON response.

        Raises:
            RuntimeError: On HTTP error or connection failure.
        """
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=self.timeout, headers=self.headers) as client:
            try:
                response = client.request(method, url, params=params, json=json_body)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                msg = f"Pretalx API request failed: {exc.response.status_code} for URL {exc.request.url}"
                raise RuntimeError(msg) from exc
            except httpx.RequestError as exc:
                msg = f"Pretalx API connection error for URL {url}: {exc}"
                raise RuntimeError(msg) from exc
        if response.status_code == http.HTTPStatus.NO_CONTENT:
            return {}
        return response.json()

    def _request_or_none(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Execute a request, returning ``None`` on HTTP 404."""
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=self.timeout, headers=self.headers) as client:
            try:
                response = client.request(method, url, params=params)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == http.HTTPStatus.NOT_FOUND:
                    return None
                msg = f"Pretalx API request failed: {exc.response.status_code} for URL {exc.request.url}"
                raise RuntimeError(msg) from exc
            except httpx.RequestError as exc:
                msg = f"Pretalx API connection error for URL {url}: {exc}"
                raise RuntimeError(msg) from exc
        return response.json()

    def _paginate(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all pages from a paginated endpoint.

        Follows ``next`` links until exhausted.
        """
        url: str | None = f"{self.base_url}{path}"
        results: list[dict[str, Any]] = []

        with httpx.Client(timeout=self.timeout, headers=self.headers) as client:
            while url is not None:
                logger.debug("Fetching %s", url)
                try:
                    response = client.get(url, params=params)
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    msg = f"Pretalx API request failed: {exc.response.status_code} for URL {exc.request.url}"
                    raise RuntimeError(msg) from exc
                except httpx.RequestError as exc:
                    msg = f"Pretalx API connection error for URL {url}: {exc}"
                    raise RuntimeError(msg) from exc

                data = response.json()
                if isinstance(data, list):
                    results.extend(data)
                    url = None
                else:
                    results.extend(data.get("results", []))
                    url = data.get("next")
                # Only pass params on the first request; subsequent pages
                # use the full ``next`` URL which already includes params.
                params = None

        logger.debug("Collected %d results from paginated endpoint", len(results))
        return results

    def _paginate_or_none(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]] | None:
        """Fetch all pages, returning ``None`` on HTTP 404."""
        url: str | None = f"{self.base_url}{path}"
        results: list[dict[str, Any]] = []

        with httpx.Client(timeout=self.timeout, headers=self.headers) as client:
            while url is not None:
                logger.debug("Fetching %s", url)
                try:
                    response = client.get(url, params=params)
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == http.HTTPStatus.NOT_FOUND:
                        logger.debug("Got 404 for %s, endpoint unavailable", url)
                        return None
                    msg = f"Pretalx API request failed: {exc.response.status_code} for URL {exc.request.url}"
                    raise RuntimeError(msg) from exc
                except httpx.RequestError as exc:
                    msg = f"Pretalx API connection error for URL {url}: {exc}"
                    raise RuntimeError(msg) from exc

                data = response.json()
                if isinstance(data, list):
                    results.extend(data)
                    url = None
                else:
                    results.extend(data.get("results", []))
                    url = data.get("next")
                params = None

        logger.debug("Collected %d results from paginated endpoint", len(results))
        return results

'''


def _safe_param_name(name: str) -> str:
    """Ensure a parameter name is a valid Python identifier."""
    safe = re.sub(r"[^a-z0-9_]", "_", name.lower())
    if safe in _PYTHON_KEYWORD:
        safe = f"{safe}_"
    return safe


def _build_path_expr(path: str, path_params: list[dict]) -> str:
    """Build an f-string path expression substituting path params."""
    expr = path
    for param in path_params:
        placeholder = "{" + param["name"] + "}"
        safe = _safe_param_name(param["name"])
        expr = expr.replace(placeholder, "{" + safe + "}")
    return expr


def generate_method(op: dict) -> str:
    """Generate the Python source for a single endpoint method."""
    op_id = op["operation_id"]
    method = op["method"]
    path = op["path"]
    path_params = op["path_params"]
    query_params = op["query_params"]
    paginated = op["paginated"]
    has_body = op["has_body"]
    is_delete = op["is_delete"]

    # Build signature
    sig_parts = ["self"]
    for pp in path_params:
        safe = _safe_param_name(pp["name"])
        sig_parts.append(f"{safe}: {pp['type']}")

    # Keyword-only separator
    has_kwargs = bool(query_params) or has_body or paginated
    if has_kwargs:
        sig_parts.append("*")

    for qp in query_params:
        safe = _safe_param_name(qp["name"])
        sig_parts.append(f"{safe}: {qp['type']} = None")

    if has_body:
        sig_parts.append("body: dict[str, Any] | None = None")

    if paginated:
        sig_parts.append("auto_paginate: bool = True")

    # Return type
    if is_delete:
        ret_type = "None"
    elif paginated:
        ret_type = "list[dict[str, Any]]"
    else:
        ret_type = "dict[str, Any]"

    sig = ", ".join(sig_parts)
    path_expr = _build_path_expr(path, path_params)

    lines = []
    lines.append(f"    def {op_id}({sig}) -> {ret_type}:")

    # Build method body
    body_lines = []

    # Build params dict from query params
    if query_params:
        body_lines.append("params: dict[str, Any] = {}")
        for qp in query_params:
            safe = _safe_param_name(qp["name"])
            body_lines.append(f"if {safe} is not None:")
            body_lines.append(f'    params["{qp["name"]}"] = {safe}')
    else:
        body_lines.append("params = None")

    # Build path f-string
    body_lines.append(f'path = f"{path_expr}"')

    if is_delete:
        body_lines.append(f'self._request("{method.upper()}", path, params=params)')
        body_lines.append("return None")
    elif paginated:
        body_lines.append("if auto_paginate:")
        body_lines.append("    return self._paginate(path, params=params or None)")
        body_lines.append(f'return self._request("{method.upper()}", path, params=params or None)')
    elif has_body:
        body_lines.append(f'return self._request("{method.upper()}", path, params=params or None, json_body=body)')
    else:
        body_lines.append(f'return self._request("{method.upper()}", path, params=params or None)')

    lines.extend(f"        {bl}" for bl in body_lines)

    return "\n".join(lines)


def generate_client(operations: list[dict]) -> str:
    """Generate the full Python source for GeneratedPretalxClient."""
    methods_by_tag: dict[str, list[str]] = {}
    for op in operations:
        tag = op["tag"]
        method_src = generate_method(op)
        methods_by_tag.setdefault(tag, []).append(method_src)

    method_blocks = []
    for tag in sorted(methods_by_tag):
        method_blocks.append(f"    # {'=' * 67}")
        method_blocks.append(f"    # {tag}")
        method_blocks.append(f"    # {'=' * 67}")
        method_blocks.append("")
        for msrc in methods_by_tag[tag]:
            method_blocks.append(msrc)
            method_blocks.append("")

    all_methods = "\n".join(method_blocks)

    # Insert methods into the class body (replace the trailing newline in header)
    return _FILE_HEADER.rstrip("\n") + "\n" + all_methods + "\n"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Load the OpenAPI schema and generate the HTTP client module."""
    if not SCHEMA_FILE.exists():
        print(f"FAIL: Schema file not found at {SCHEMA_FILE}", file=sys.stderr)
        print("  Run `make pretalx-fetch-schema` first.", file=sys.stderr)
        raise SystemExit(1)

    print(f"Loading schema from {SCHEMA_FILE.relative_to(PROJECT_ROOT)} ...")

    with SCHEMA_FILE.open() as f:
        schema = yaml.safe_load(f)

    schema = _patch_schema(schema)

    operations = extract_operations(schema)
    print(f"  Found {len(operations)} operations across {len({o['tag'] for o in operations})} tags")

    source = generate_client(operations)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(source)
    print(f"  Wrote {OUTPUT_FILE.relative_to(PROJECT_ROOT)}")
    print(f"DONE: Generated {len(operations)} methods")


if __name__ == "__main__":
    main()
