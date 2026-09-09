#!/usr/bin/env python3
"""Validate that user-facing README facts match repository sources."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
PYPROJECT = ROOT / "pyproject.toml"
CONFIG = ROOT / "backend" / "core" / "config.py"
BENCHMARK = ROOT / "backend" / "benchmarks" / "transpiler_benchmark.py"


def fail(message: str) -> None:
    raise SystemExit(f"README consistency check failed: {message}")


def main() -> None:
    readme = README.read_text(encoding="utf-8")
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    config = CONFIG.read_text(encoding="utf-8")

    version = pyproject["project"]["version"]
    requires_python = pyproject["project"]["requires-python"]

    match = re.search(r"(?m)^\s*version\s*=\s*[\"']([^\"']+)[\"']", PYPROJECT.read_text(encoding="utf-8"))
    if not match or match.group(1) != version:
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
        "python badge": "Python 3.11+",
        "12-dialect feature claim": "12 database dialects",
        "12x12 matrix claim": "12 × 12 conversion matrix",
        "project version": f"version {version}",
        "python requirement": "python-version",
        "benchmark path": "backend/benchmarks/transpiler_benchmark.py",
        "semantic dependency install": '[dev,semantic]',
        "benchmark description": "reproducible benchmark",
    }
    for name, fragment in required_fragments.items():
        if fragment not in readme:
            fail(f"missing {name}: {fragment!r}")

    if requires_python != ">=3.11":
        fail(f"unexpected project Python requirement: {requires_python}")

    if not BENCHMARK.is_file():
        fail("README references a benchmark that does not exist")

    print(
        "README consistency check passed: "
        f"version={version}, requires-python={requires_python}, "
        f"dialects={len(actual_dialects)}, benchmark={BENCHMARK.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
