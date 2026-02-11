"""Tests for the codegen pipeline scripts (fetch, validate, generate).

The scripts under ``scripts/pretalx/`` are standalone CLI entry-points, not
installed packages.  We import them by file path via ``importlib.util`` and
mutate their module-level constants so all filesystem operations target
``tmp_path``.
"""

import hashlib
import importlib.util
import re
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest
import yaml

# ---------------------------------------------------------------------------
# Helpers: import scripts by file path
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts" / "pretalx"


def _import_script(name: str):
    """Import a script module from ``scripts/pretalx/<name>.py`` by file path.

    Each call creates a fresh module so tests do not leak state between
    each other through shared module globals.
    """
    script_path = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_codegen_script_{name}", script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# fetch_schema.py
# ---------------------------------------------------------------------------


class TestFetchSchema:
    """Tests for scripts/pretalx/fetch_schema.py -- main()."""

    @pytest.mark.unit
    def test_main_writes_schema_and_checksum(self, tmp_path):
        """Mocked httpx.get returns fake YAML; schema.yml and schema.sha256 are written."""
        schema_dir = tmp_path / "schemas" / "pretalx"
        schema_file = schema_dir / "schema.yml"
        checksum_file = schema_dir / "schema.sha256"

        fake_yaml = b"openapi: '3.0.3'\ninfo:\n  title: Pretalx\npaths: {}\n"

        mock_response = Mock(spec=httpx.Response)
        mock_response.content = fake_yaml
        mock_response.raise_for_status = Mock()

        mod = _import_script("fetch_schema")
        mod.SCHEMA_DIR = schema_dir
        mod.SCHEMA_FILE = schema_file
        mod.CHECKSUM_FILE = checksum_file
        mod.PROJECT_ROOT = tmp_path

        with patch.object(mod, "httpx") as mock_httpx:
            mock_httpx.get.return_value = mock_response
            mock_httpx.HTTPStatusError = httpx.HTTPStatusError
            mock_httpx.RequestError = httpx.RequestError

            mod.main()

            mock_httpx.get.assert_called_once()

        assert schema_file.exists()
        assert checksum_file.exists()
        assert schema_file.read_bytes() == fake_yaml

    @pytest.mark.unit
    def test_checksum_format(self, tmp_path):
        """The checksum file must contain '<hex_digest>  schema.yml' (two spaces)."""
        schema_dir = tmp_path / "schemas" / "pretalx"
        schema_file = schema_dir / "schema.yml"
        checksum_file = schema_dir / "schema.sha256"

        fake_yaml = b"openapi: '3.0.3'\ninfo:\n  title: Test\npaths: {}\n"
        expected_digest = hashlib.sha256(fake_yaml).hexdigest()

        mock_response = Mock(spec=httpx.Response)
        mock_response.content = fake_yaml
        mock_response.raise_for_status = Mock()

        mod = _import_script("fetch_schema")
        mod.SCHEMA_DIR = schema_dir
        mod.SCHEMA_FILE = schema_file
        mod.CHECKSUM_FILE = checksum_file
        mod.PROJECT_ROOT = tmp_path

        with patch.object(mod, "httpx") as mock_httpx:
            mock_httpx.get.return_value = mock_response
            mock_httpx.HTTPStatusError = httpx.HTTPStatusError
            mock_httpx.RequestError = httpx.RequestError

            mod.main()

        checksum_text = checksum_file.read_text()
        # Format: "<64-char hex>  schema.yml\n"
        assert re.match(r"^[0-9a-f]{64}  schema\.yml\n$", checksum_text)
        assert checksum_text.strip() == f"{expected_digest}  schema.yml"

    @pytest.mark.unit
    def test_main_exits_on_http_status_error(self, tmp_path):
        """SystemExit(1) when httpx.get raises an HTTPStatusError."""
        schema_dir = tmp_path / "schemas" / "pretalx"

        mock_request = Mock(spec=httpx.Request)
        mock_request.url = "https://docs.pretalx.org/schema.yml"
        mock_resp = Mock(spec=httpx.Response)
        mock_resp.status_code = 404

        exc = httpx.HTTPStatusError(
            message="Not Found",
            request=mock_request,
            response=mock_resp,
        )

        mod = _import_script("fetch_schema")
        mod.SCHEMA_DIR = schema_dir
        mod.PROJECT_ROOT = tmp_path

        with patch.object(mod, "httpx") as mock_httpx:
            mock_httpx.get.side_effect = exc
            mock_httpx.HTTPStatusError = httpx.HTTPStatusError
            mock_httpx.RequestError = httpx.RequestError

            with pytest.raises(SystemExit) as exc_info:
                mod.main()

            assert exc_info.value.code == 1

    @pytest.mark.unit
    def test_main_exits_on_request_error(self, tmp_path):
        """SystemExit(1) when httpx.get raises a connection-level error."""
        schema_dir = tmp_path / "schemas" / "pretalx"

        mock_request = Mock(spec=httpx.Request)
        mock_request.url = "https://docs.pretalx.org/schema.yml"
        exc = httpx.RequestError("Connection refused", request=mock_request)

        mod = _import_script("fetch_schema")
        mod.SCHEMA_DIR = schema_dir
        mod.PROJECT_ROOT = tmp_path

        with patch.object(mod, "httpx") as mock_httpx:
            mock_httpx.get.side_effect = exc
            mock_httpx.HTTPStatusError = httpx.HTTPStatusError
            mock_httpx.RequestError = httpx.RequestError

            with pytest.raises(SystemExit) as exc_info:
                mod.main()

            assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# validate_schema.py
# ---------------------------------------------------------------------------


class TestValidateChecksum:
    """Tests for scripts/pretalx/validate_schema.py -- _validate_checksum()."""

    @pytest.mark.unit
    def test_valid_checksum_passes(self, tmp_path):
        """Correct checksum returns True."""
        schema_dir = tmp_path / "schemas" / "pretalx"
        schema_dir.mkdir(parents=True)
        schema_file = schema_dir / "schema.yml"
        checksum_file = schema_dir / "schema.sha256"

        content = b"openapi: '3.0.3'\ninfo:\n  title: Pretalx\npaths: {}\n"
        schema_file.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        checksum_file.write_text(f"{digest}  schema.yml\n")

        mod = _import_script("validate_schema")
        mod.SCHEMA_FILE = schema_file
        mod.CHECKSUM_FILE = checksum_file

        assert mod._validate_checksum() is True

    @pytest.mark.unit
    def test_wrong_checksum_fails(self, tmp_path):
        """Mismatched checksum returns False."""
        schema_dir = tmp_path / "schemas" / "pretalx"
        schema_dir.mkdir(parents=True)
        schema_file = schema_dir / "schema.yml"
        checksum_file = schema_dir / "schema.sha256"

        content = b"openapi: '3.0.3'\ninfo:\n  title: Pretalx\npaths: {}\n"
        schema_file.write_bytes(content)
        checksum_file.write_text("0000000000000000000000000000000000000000000000000000000000000000  schema.yml\n")

        mod = _import_script("validate_schema")
        mod.SCHEMA_FILE = schema_file
        mod.CHECKSUM_FILE = checksum_file

        assert mod._validate_checksum() is False

    @pytest.mark.unit
    def test_missing_checksum_file_fails(self, tmp_path):
        """Missing checksum file returns False."""
        schema_dir = tmp_path / "schemas" / "pretalx"
        schema_dir.mkdir(parents=True)
        schema_file = schema_dir / "schema.yml"
        checksum_file = schema_dir / "schema.sha256"

        schema_file.write_bytes(b"openapi: '3.0.3'\n")
        # Deliberately do not create checksum_file

        mod = _import_script("validate_schema")
        mod.SCHEMA_FILE = schema_file
        mod.CHECKSUM_FILE = checksum_file

        assert mod._validate_checksum() is False


class TestValidateOpenAPIStructure:
    """Tests for scripts/pretalx/validate_schema.py -- _validate_openapi_structure()."""

    @pytest.fixture
    def validate_mod(self):
        return _import_script("validate_schema")

    @pytest.mark.unit
    def test_valid_openapi_structure(self, validate_mod):
        """A dict with all required keys and a 3.x version passes."""
        data = {
            "openapi": "3.0.3",
            "info": {"title": "Pretalx", "version": "1.0"},
            "paths": {"/api/speakers/": {}},
        }
        assert validate_mod._validate_openapi_structure(data) is True

    @pytest.mark.unit
    def test_missing_required_key_fails(self, validate_mod):
        """A dict missing 'paths' returns False."""
        data = {
            "openapi": "3.0.3",
            "info": {"title": "Pretalx"},
        }
        assert validate_mod._validate_openapi_structure(data) is False

    @pytest.mark.unit
    def test_missing_all_required_keys_fails(self, validate_mod):
        """An empty dict returns False."""
        assert validate_mod._validate_openapi_structure({}) is False

    @pytest.mark.unit
    def test_non_3x_version_fails(self, validate_mod):
        """OpenAPI version 2.0 (Swagger) returns False."""
        data = {
            "openapi": "2.0",
            "info": {"title": "Pretalx"},
            "paths": {},
        }
        assert validate_mod._validate_openapi_structure(data) is False

    @pytest.mark.unit
    def test_numeric_version_coerced(self, validate_mod):
        """A numeric openapi field (e.g. 3.1) is coerced to string and passes."""
        data = {
            "openapi": 3.1,
            "info": {"title": "Test"},
            "paths": {},
        }
        assert validate_mod._validate_openapi_structure(data) is True


class TestValidateSchemaMain:
    """Tests for scripts/pretalx/validate_schema.py -- main()."""

    @pytest.mark.unit
    def test_valid_schema_passes(self, tmp_path):
        """Valid schema with matching checksum succeeds without SystemExit."""
        schema_dir = tmp_path / "schemas" / "pretalx"
        schema_dir.mkdir(parents=True)
        schema_file = schema_dir / "schema.yml"
        checksum_file = schema_dir / "schema.sha256"

        content = b"openapi: '3.0.3'\ninfo:\n  title: Pretalx\n  version: '1.0'\npaths:\n  /speakers/: {}\n"
        schema_file.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        checksum_file.write_text(f"{digest}  schema.yml\n")

        mod = _import_script("validate_schema")
        mod.SCHEMA_DIR = schema_dir
        mod.SCHEMA_FILE = schema_file
        mod.CHECKSUM_FILE = checksum_file
        mod.PROJECT_ROOT = tmp_path

        # Should not raise
        mod.main()

    @pytest.mark.unit
    def test_missing_schema_file_exits(self, tmp_path):
        """SystemExit(1) when the schema file does not exist."""
        schema_dir = tmp_path / "schemas" / "pretalx"
        schema_dir.mkdir(parents=True)
        schema_file = schema_dir / "schema.yml"
        # Deliberately do not create schema_file

        mod = _import_script("validate_schema")
        mod.SCHEMA_FILE = schema_file
        mod.PROJECT_ROOT = tmp_path

        with pytest.raises(SystemExit) as exc_info:
            mod.main()

        assert exc_info.value.code == 1

    @pytest.mark.unit
    def test_checksum_mismatch_exits(self, tmp_path):
        """SystemExit(1) when checksum does not match."""
        schema_dir = tmp_path / "schemas" / "pretalx"
        schema_dir.mkdir(parents=True)
        schema_file = schema_dir / "schema.yml"
        checksum_file = schema_dir / "schema.sha256"

        content = b"openapi: '3.0.3'\ninfo:\n  title: Test\n  version: '1.0'\npaths:\n  /x/: {}\n"
        schema_file.write_bytes(content)
        checksum_file.write_text("bad_checksum_value  schema.yml\n")

        mod = _import_script("validate_schema")
        mod.SCHEMA_DIR = schema_dir
        mod.SCHEMA_FILE = schema_file
        mod.CHECKSUM_FILE = checksum_file
        mod.PROJECT_ROOT = tmp_path

        with pytest.raises(SystemExit) as exc_info:
            mod.main()

        assert exc_info.value.code == 1

    @pytest.mark.unit
    def test_invalid_openapi_structure_exits(self, tmp_path):
        """SystemExit(1) when the schema YAML has invalid OpenAPI structure."""
        schema_dir = tmp_path / "schemas" / "pretalx"
        schema_dir.mkdir(parents=True)
        schema_file = schema_dir / "schema.yml"
        checksum_file = schema_dir / "schema.sha256"

        # Valid YAML but missing 'paths' key
        content = b"openapi: '3.0.3'\ninfo:\n  title: Incomplete\n"
        schema_file.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        checksum_file.write_text(f"{digest}  schema.yml\n")

        mod = _import_script("validate_schema")
        mod.SCHEMA_DIR = schema_dir
        mod.SCHEMA_FILE = schema_file
        mod.CHECKSUM_FILE = checksum_file
        mod.PROJECT_ROOT = tmp_path

        with pytest.raises(SystemExit) as exc_info:
            mod.main()

        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# generate_client.py
# ---------------------------------------------------------------------------


class TestGenerateClient:
    """Tests for scripts/pretalx/generate_client.py -- main()."""

    @pytest.mark.unit
    def test_successful_generation(self, tmp_path):
        """Successful subprocess run writes output dir and __init__.py."""
        schema_dir = tmp_path / "schemas" / "pretalx"
        schema_dir.mkdir(parents=True)
        schema_file = schema_dir / "schema.yml"
        schema_file.write_bytes(b"openapi: '3.0.3'\n")

        output_dir = tmp_path / "generated"

        mock_result = Mock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        mod = _import_script("generate_client")
        mod.SCHEMA_FILE = schema_file
        mod.OUTPUT_DIR = output_dir
        mod.PROJECT_ROOT = tmp_path

        with patch.object(mod, "subprocess") as mock_subprocess:
            mock_subprocess.run.return_value = mock_result
            mod.main()

            mock_subprocess.run.assert_called_once()

        assert output_dir.exists()

        init_file = output_dir / "__init__.py"
        assert init_file.exists()
        assert "Generated Pretalx API models" in init_file.read_text()

    @pytest.mark.unit
    def test_subprocess_failure_exits(self, tmp_path):
        """SystemExit with the subprocess return code on failure."""
        schema_dir = tmp_path / "schemas" / "pretalx"
        schema_dir.mkdir(parents=True)
        schema_file = schema_dir / "schema.yml"
        schema_file.write_bytes(b"openapi: '3.0.3'\n")

        output_dir = tmp_path / "generated"

        mock_result = Mock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 2
        mock_result.stdout = "some output"
        mock_result.stderr = "codegen error details"

        mod = _import_script("generate_client")
        mod.SCHEMA_FILE = schema_file
        mod.OUTPUT_DIR = output_dir
        mod.PROJECT_ROOT = tmp_path

        with patch.object(mod, "subprocess") as mock_subprocess:
            mock_subprocess.run.return_value = mock_result

            with pytest.raises(SystemExit) as exc_info:
                mod.main()

            assert exc_info.value.code == 2

    @pytest.mark.unit
    def test_output_directory_created(self, tmp_path):
        """Output directory is created when it does not exist."""
        schema_dir = tmp_path / "schemas" / "pretalx"
        schema_dir.mkdir(parents=True)
        schema_file = schema_dir / "schema.yml"
        schema_file.write_bytes(b"openapi: '3.0.3'\n")

        output_dir = tmp_path / "deeply" / "nested" / "output"
        assert not output_dir.exists()

        mock_result = Mock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        mod = _import_script("generate_client")
        mod.SCHEMA_FILE = schema_file
        mod.OUTPUT_DIR = output_dir
        mod.PROJECT_ROOT = tmp_path

        with patch.object(mod, "subprocess") as mock_subprocess:
            mock_subprocess.run.return_value = mock_result
            mod.main()

        assert output_dir.exists()

    @pytest.mark.unit
    def test_missing_schema_file_exits(self, tmp_path):
        """SystemExit(1) when the schema file does not exist."""
        schema_file = tmp_path / "schemas" / "pretalx" / "schema.yml"
        output_dir = tmp_path / "output"

        mod = _import_script("generate_client")
        mod.SCHEMA_FILE = schema_file
        mod.OUTPUT_DIR = output_dir
        mod.PROJECT_ROOT = tmp_path

        with pytest.raises(SystemExit) as exc_info:
            mod.main()

        assert exc_info.value.code == 1

    @pytest.mark.unit
    def test_init_py_not_overwritten_when_present(self, tmp_path):
        """Existing __init__.py is left untouched."""
        schema_dir = tmp_path / "schemas" / "pretalx"
        schema_dir.mkdir(parents=True)
        schema_file = schema_dir / "schema.yml"
        schema_file.write_bytes(b"openapi: '3.0.3'\n")

        output_dir = tmp_path / "output"
        output_dir.mkdir(parents=True)
        init_file = output_dir / "__init__.py"
        original_content = "# custom init content\n"
        init_file.write_text(original_content)

        mock_result = Mock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        mod = _import_script("generate_client")
        mod.SCHEMA_FILE = schema_file
        mod.OUTPUT_DIR = output_dir
        mod.PROJECT_ROOT = tmp_path

        with patch.object(mod, "subprocess") as mock_subprocess:
            mock_subprocess.run.return_value = mock_result
            mod.main()

        assert init_file.read_text() == original_content

    @pytest.mark.unit
    def test_subprocess_called_with_correct_args(self, tmp_path):
        """Verify the subprocess command includes expected datamodel-codegen flags."""
        schema_dir = tmp_path / "schemas" / "pretalx"
        schema_dir.mkdir(parents=True)
        schema_file = schema_dir / "schema.yml"
        schema_file.write_bytes(b"openapi: '3.0.3'\n")

        output_dir = tmp_path / "output"

        mock_result = Mock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        mod = _import_script("generate_client")
        mod.SCHEMA_FILE = schema_file
        mod.OUTPUT_DIR = output_dir
        mod.PROJECT_ROOT = tmp_path

        with patch.object(mod, "subprocess") as mock_subprocess:
            mock_subprocess.run.return_value = mock_result
            mod.main()

        call_args = mock_subprocess.run.call_args
        cmd = call_args[0][0]

        assert "--input" in cmd
        assert str(schema_file) in cmd
        assert "--input-file-type" in cmd
        assert "openapi" in cmd
        assert "--output" in cmd
        assert str(output_dir / "models.py") in cmd
        assert "--output-model-type" in cmd
        assert "dataclasses.dataclass" in cmd
        assert "--target-python-version" in cmd
        assert "3.14" in cmd

        assert call_args[1]["capture_output"] is True
        assert call_args[1]["text"] is True
        assert call_args[1]["check"] is False


# ---------------------------------------------------------------------------
# generate_http_client.py
# ---------------------------------------------------------------------------


class TestGenerateHttpClient:
    """Tests for scripts/pretalx/generate_http_client.py."""

    @pytest.fixture
    def gen_mod(self):
        return _import_script("generate_http_client")

    @pytest.mark.unit
    def test_sanitize_operation_id_basic(self, gen_mod):
        assert gen_mod.sanitize_operation_id("speakers_list") == "speakers_list"

    @pytest.mark.unit
    def test_sanitize_operation_id_spaces(self, gen_mod):
        assert gen_mod.sanitize_operation_id("File upload") == "file_upload"

    @pytest.mark.unit
    def test_sanitize_operation_id_special_chars(self, gen_mod):
        assert gen_mod.sanitize_operation_id("foo-bar.baz") == "foo_bar_baz"

    @pytest.mark.unit
    def test_sanitize_operation_id_keyword(self, gen_mod):
        assert gen_mod.sanitize_operation_id("class") == "class_"

    @pytest.mark.unit
    def test_patch_schema_fixes_type_str(self, gen_mod):
        schema = {"paths": {}, "components": {"schemas": {"Foo": {"properties": {"bar": {"type": "str"}}}}}}
        patched = gen_mod._patch_schema(schema)
        assert patched["components"]["schemas"]["Foo"]["properties"]["bar"]["type"] == "string"

    @pytest.mark.unit
    def test_patch_schema_preserves_type_string(self, gen_mod):
        schema = {"paths": {}, "components": {"schemas": {"Foo": {"properties": {"bar": {"type": "string"}}}}}}
        patched = gen_mod._patch_schema(schema)
        assert patched["components"]["schemas"]["Foo"]["properties"]["bar"]["type"] == "string"

    @pytest.mark.unit
    def test_is_paginated_detects_paginated_list(self, gen_mod):
        responses = {
            "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/PaginatedSpeakerList"}}}}
        }
        assert gen_mod._is_paginated(responses) is True

    @pytest.mark.unit
    def test_is_paginated_rejects_non_paginated(self, gen_mod):
        responses = {"200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Speaker"}}}}}
        assert gen_mod._is_paginated(responses) is False

    @pytest.mark.unit
    def test_extract_operations_count(self, gen_mod):
        """Verify correct method count from the real schema."""
        schema_path = REPO_ROOT / "schemas" / "pretalx" / "schema.yml"
        if not schema_path.exists():
            pytest.skip("Real schema not available")

        with schema_path.open() as f:
            schema = yaml.safe_load(f)

        schema = gen_mod._patch_schema(schema)
        ops = gen_mod.extract_operations(schema)
        assert len(ops) == 129

    @pytest.mark.unit
    def test_main_writes_output(self, tmp_path):
        """Mocked schema produces output file."""
        schema_dir = tmp_path / "schemas" / "pretalx"
        schema_dir.mkdir(parents=True)
        schema_file = schema_dir / "schema.yml"

        # Minimal valid schema with one operation
        schema_content = """
openapi: '3.0.3'
info:
  title: Test
  version: '1.0'
paths:
  /api/events/:
    get:
      operationId: api_events_list
      tags:
        - events
      responses:
        '200':
          content:
            application/json:
              schema:
                type: array
                items:
                  type: object
          description: ''
"""
        schema_file.write_text(schema_content)

        output_dir = tmp_path / "output"

        mod = _import_script("generate_http_client")
        mod.SCHEMA_FILE = schema_file
        mod.OUTPUT_DIR = output_dir
        mod.OUTPUT_FILE = output_dir / "http_client.py"
        mod.PROJECT_ROOT = tmp_path

        mod.main()

        assert (output_dir / "http_client.py").exists()
        content = (output_dir / "http_client.py").read_text()
        assert "class GeneratedPretalxClient" in content
        assert "def api_events_list" in content

    @pytest.mark.unit
    def test_main_missing_schema_exits(self, tmp_path):
        """SystemExit(1) when the schema file does not exist."""
        schema_file = tmp_path / "schemas" / "pretalx" / "schema.yml"
        output_dir = tmp_path / "output"

        mod = _import_script("generate_http_client")
        mod.SCHEMA_FILE = schema_file
        mod.OUTPUT_DIR = output_dir
        mod.OUTPUT_FILE = output_dir / "http_client.py"
        mod.PROJECT_ROOT = tmp_path

        with pytest.raises(SystemExit) as exc_info:
            mod.main()

        assert exc_info.value.code == 1

    @pytest.mark.unit
    def test_query_param_type_mapping(self, gen_mod):
        assert gen_mod._query_param_type({"type": "string"}) == "str | None"
        assert gen_mod._query_param_type({"type": "integer"}) == "int | None"
        assert gen_mod._query_param_type({"type": "boolean"}) == "bool | None"
        assert gen_mod._query_param_type({"type": "array"}) == "list[str] | None"
        assert gen_mod._query_param_type({}) == "str | None"
