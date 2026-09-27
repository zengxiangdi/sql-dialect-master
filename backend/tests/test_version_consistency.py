#!/usr/bin/env python3
"""Consistency tests for canonical version and metadata facts.

These tests guard against the exact drift that existed in the repo
before the metadata module:

- pyproject.toml = 1.1.0
- backend/core/config.py api_version = "1.0.1"
- .env.example = 1.0.1
- frontend/pages/settings.py = "SQL Dialect Master v2.0"
- main.py / settings.py / .env.example = "36 types" / "298 functions"
  (hardcoded, out of sync with type_mapping.json / functions_db.json)

Every public surface must now derive its numbers from
backend.core.metadata, which is the single release source of truth.
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

from backend.core import metadata

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
METADATA_PY = ROOT / "backend" / "core" / "metadata.py"
CONFIG_PY = ROOT / "backend" / "core" / "config.py"
MAIN_PY = ROOT / "backend" / "api" / "main.py"
SETTINGS_PY = ROOT / "frontend" / "pages" / "settings.py"
ENV_EXAMPLE = ROOT / ".env.example"


def _pyproject_version() -> str:
    with PYPROJECT.open("rb") as f:
        return tomllib.load(f)["project"]["version"]


def _data_file_count(path: Path, key: str, nested: bool = False) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    value = data[key]
    if nested:
        value = data["mappings"]
    return len(value)


class TestVersionSingleSourceOfTruth:
    """All version facts must agree on one number."""

    def test_metadata_project_version_matches_pyproject(self) -> None:
        assert metadata.PROJECT_VERSION == _pyproject_version()

    def test_metadata_api_version_matches_project_version(self) -> None:
        assert metadata.API_VERSION == metadata.PROJECT_VERSION

    def test_frontend_arch_version_is_int(self) -> None:
        assert metadata.FRONTEND_ARCHITECTURE_VERSION == 2

    def test_config_api_version_sourced_from_metadata(self) -> None:
        text = CONFIG_PY.read_text(encoding="utf-8")
        assert "from backend.core.metadata import API_VERSION" in text
        assert 'api_version: str = "1.0.1"' not in text

    def test_env_example_api_version_matches(self) -> None:
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        match = re.search(r"SDM_API_VERSION=([^\n]+)", text)
        assert match, "SDM_API_VERSION missing from .env.example"
        assert match.group(1).strip() == metadata.PROJECT_VERSION

    def test_settings_page_uses_project_version_not_v2(self) -> None:
        text = SETTINGS_PY.read_text(encoding="utf-8")
        assert "SQL Dialect Master v2.0" not in text
        assert "meta.PROJECT_VERSION" in text

    def test_settings_page_not_showing_release_v2_claim(self) -> None:
        """Frontend v2 architecture must never be displayed as release v2.0.

        The display text in the About section must use metadata.PROJECT_VERSION
        (1.1.0), not "v2.0" or "v2" as a product release claim. The module
        docstring mentioning "SQL Dialect Master v2" refers to the frontend
        architecture generation, not a release version, and is acceptable.
        """
        text = SETTINGS_PY.read_text(encoding="utf-8")
        # Only scan the About-section display block (after the "About" marker).
        about_block = text.split("##### About", 1)[-1]
        assert "v2.0" not in about_block
        assert "SQL Dialect Master v2" not in about_block


class TestMetadataCountsMatchDataFiles:
    """Every count in metadata must be traceable to its data file."""

    def test_function_count_matches_functions_db(self) -> None:
        n = _data_file_count(ROOT / "backend" / "core" / "functions_db.json", "functions")
        assert metadata.FUNCTION_COUNT == n

    def test_type_count_matches_type_mapping(self) -> None:
        n = _data_file_count(ROOT / "backend" / "core" / "type_mapping.json", "mappings", nested=True)
        assert metadata.TYPE_COUNT == n

    def test_dialect_count_matches_type_mapping_dialects(self) -> None:
        n = _data_file_count(ROOT / "backend" / "core" / "type_mapping.json", "dialects")
        assert metadata.SUPPORTED_DIALECTS_COUNT == n

    def test_rule_count_is_positive_int(self) -> None:
        assert metadata.RULE_COUNT() > 0


class TestApiMainUsesDynamicCounts:
    """backend/api/main.py must not hardcode counts that exist in data files."""

    def test_main_py_not_hardcoding_type_count_36(self) -> None:
        text = MAIN_PY.read_text(encoding="utf-8")
        # The old "36 types × 12 databases" hardcoded string must be gone.
        assert "36 types" not in text
        assert "36 data type mappings" not in text
        # The new code must reference meta.TYPE_COUNT or equivalent dynamic value.
        assert "meta.TYPE_COUNT" in text or "TYPE_COUNT" in text

    def test_main_py_not_hardcoding_function_count_298(self) -> None:
        text = MAIN_PY.read_text(encoding="utf-8")
        # "298 functions" as a bare literal must not appear as a hardcoded claim.
        assert "298 functions" not in text
        # The count must come from the metadata module.
        assert "meta.FUNCTION_COUNT" in text or "FUNCTION_COUNT" in text

    def test_main_py_uses_meta_for_openapi_tags(self) -> None:
        text = MAIN_PY.read_text(encoding="utf-8")
        assert "from backend.core import metadata as meta" in text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
