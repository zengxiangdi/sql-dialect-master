#!/usr/bin/env python3
"""Validate that user-facing README facts match repository sources."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
PYPROJECT = ROOT / "pyproject.toml"
CONFIG = ROOT / "backend" / "core" / "config.py"
METADATA = ROOT / "backend" / "core" / "metadata.py"
BENCHMARK = ROOT / "backend" / "benchmarks" / "transpiler_benchmark.py"
REACT_FRONTEND = ROOT / "frontend-react"
FRONTEND_PACKAGE = REACT_FRONTEND / "package.json"
FRONTEND_LOCK = REACT_FRONTEND / "package-lock.json"
TYPE_MAPPING = ROOT / "backend" / "core" / "type_mapping.json"
FUNCTIONS_DB = ROOT / "backend" / "core" / "functions_db.json"
ENV_EXAMPLE = ROOT / ".env.example"


def fail(message: str) -> None:
    raise SystemExit(f"README consistency check failed: {message}")


def _readme_struct_section(readme: str) -> str:
    """Return the project-structure code block from the README."""
    match = re.search(r"## .*(?:Project Structure|Structure).*?\n(.*?)^##\s", readme, re.DOTALL | re.MULTILINE)
    if not match:
        fail("README project-structure section not found")
    return match.group(1)


def main() -> None:
    readme = README.read_text(encoding="utf-8")
    pyproject_text = PYPROJECT.read_text(encoding="utf-8")
    pyproject = tomllib.loads(pyproject_text)
    config = CONFIG.read_text(encoding="utf-8")

    version = pyproject["project"]["version"]
    requires_python = pyproject["project"]["requires-python"]

    if not FRONTEND_PACKAGE.is_file():
        fail("frontend-react/package.json is missing")
    if not FRONTEND_LOCK.is_file():
        fail("frontend-react/package-lock.json is missing")
    try:
        frontend_package_version = json.loads(
            FRONTEND_PACKAGE.read_text(encoding="utf-8")
        )["version"]
        frontend_lock = json.loads(FRONTEND_LOCK.read_text(encoding="utf-8"))
        frontend_lock_version = frontend_lock["version"]
        frontend_lock_root_version = frontend_lock["packages"][""]["version"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        fail(f"frontend version metadata is invalid: {exc}")

    frontend_versions = {
        "frontend-react/package.json version": frontend_package_version,
        "frontend-react/package-lock.json version": frontend_lock_version,
        "frontend-react/package-lock.json packages[''] version": frontend_lock_root_version,
        "pyproject.toml project.version": version,
    }
    for name, actual in frontend_versions.items():
        if actual != version:
            fail(f"{name}={actual!r} does not match pyproject.toml project.version={version!r}")

    version_match = re.search(
        r"(?m)^version\s*=\s*[\"']([^\"']+)[\"']\s*$", pyproject_text
    )
    if not version_match or version_match.group(1) != version:
        fail("could not parse project version consistently")

    expected_dialects = [
        "hive",
        "mysql",
        "oracle",
        "tsql",
        "postgres",
        "spark",
        "trino",
        "snowflake",
        "redshift",
        "clickhouse",
        "duckdb",
        "databricks",
    ]
    dialect_block = re.search(
        r"SUPPORTED_DIALECTS:\s*List\[str\]\s*=\s*\[(.*?)\]\n\nclass DialectCategory",
        config,
        re.DOTALL,
    )
    if not dialect_block:
        fail("SUPPORTED_DIALECTS definition is missing or changed shape")
    actual_dialects = re.findall(r'"([a-z0-9_]+)"', dialect_block.group(1))
    if actual_dialects != expected_dialects:
        fail(f"SUPPORTED_DIALECTS drifted: expected {expected_dialects}, got {actual_dialects}")

    required_fragments = {
        "Python badge": "Python 3.11+",
        "12-dialect feature claim": "12 database dialects",
        "12x12 matrix claim": "12 × 12 conversion matrix",
        "project version marker": f"Current release: {version}",
        "semantic dependency install": ".[dev,semantic]",
        "benchmark path": "backend/benchmarks/transpiler_benchmark.py",
        "benchmark description": "reproducible benchmark",
    }
    for name, fragment in required_fragments.items():
        if fragment not in readme:
            fail(f"missing {name}: {fragment!r}")

    if requires_python != ">=3.11":
        fail(f"unexpected project Python requirement: {requires_python}")

    if not BENCHMARK.is_file():
        fail("README references a benchmark that does not exist")

    # React is the sole product frontend.
    if not (REACT_FRONTEND / "package.json").is_file() or not (REACT_FRONTEND / "src").is_dir():
        fail("React frontend workspace is missing")
    if re.search(r"(?im)^.*(?:streamlit|sdm-streamlit|sdm_local_v2\.py).*$", readme):
        fail("README still documents the retired Streamlit frontend")

    # ── Feature-count claims ──────────────────────────────────────────
    if TYPE_MAPPING.is_file():
        type_mapping = json.loads(TYPE_MAPPING.read_text(encoding="utf-8"))
        n_types = len(type_mapping.get("mappings", {}))
        claim = re.search(r"(\d+)\s+data types × 12 databases matrix", readme)
        if claim and int(claim.group(1)) != n_types:
            fail(f"README claims {claim.group(1)} data types, source has {n_types}")

    if FUNCTIONS_DB.is_file():
        functions_db = json.loads(FUNCTIONS_DB.read_text(encoding="utf-8"))
        n_functions = len(functions_db.get("functions", []))
        claim = re.search(r"(\d+)\s+SQL functions with cross-database comparison", readme)
        if claim and int(claim.group(1)) != n_functions:
            fail(f"README claims {claim.group(1)} SQL functions, source has {n_functions}")

    # ── Version / API consistency across all public surfaces ─────────
    # The metadata module is the single source of truth for version
    # facts. config.py must import from it; .env.example must match;
    # the frontend settings page must use the project version.

    metadata_text = METADATA.read_text(encoding="utf-8") if METADATA.is_file() else ""
    if not METADATA.is_file():
        fail("backend/core/metadata.py is missing — canonical version source not found")

    # PROJECT_VERSION in metadata must match pyproject version.
    proj_version_match = re.search(r"PROJECT_VERSION\s*=\s*[\"']([^\"']+)[\"']", metadata_text)
    if not proj_version_match:
        fail("backend/core/metadata.py: PROJECT_VERSION not found")
    if proj_version_match.group(1) != version:
        fail(
            f"metadata.py PROJECT_VERSION={proj_version_match.group(1)!r} "
            f"does not match pyproject version={version!r}"
        )

    # config.py must import api_version from metadata (not hardcode "1.0.1").
    config_text = CONFIG.read_text(encoding="utf-8")
    if re.search(r'api_version:\s*str\s*=\s*"1\.0\.1"', config_text):
        fail(
            "config.py still hardcodes api_version=\"1.0.1\" — "
            "must import from backend.core.metadata"
        )
    if "from backend.core.metadata import" not in config_text:
        fail(
            "config.py does not import from backend.core.metadata — "
            "api_version must be sourced from the metadata module"
        )

    # .env.example must carry the same API version as the metadata module.
    if ENV_EXAMPLE.is_file():
        env_text = ENV_EXAMPLE.read_text(encoding="utf-8")
        api_version_match = re.search(r"SDM_API_VERSION=([^\n]+)", env_text)
        if not api_version_match:
            fail(".env.example: SDM_API_VERSION not found")
        if api_version_match.group(1).strip() != version:
            fail(
                f".env.example SDM_API_VERSION={api_version_match.group(1)!r} "
                f"does not match project version={version!r}"
            )

    print(
        "README consistency check passed: "
        f"version={version}, requires-python={requires_python}, "
        f"dialects={len(actual_dialects)}, benchmark={BENCHMARK.relative_to(ROOT)}, "
        f"react_frontend={REACT_FRONTEND.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
