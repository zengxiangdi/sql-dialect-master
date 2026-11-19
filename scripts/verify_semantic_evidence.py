#!/usr/bin/env python3
"""Verify that Tier A semantic tests did not silently skip in CI."""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


TIER_A_MODULE_MARKERS = (
    "test_d3_date_runtime.py",
    "test_duckdb_runtime.py",
    "test_postgres_runtime.py",
    "semantic/test_runtime_semantics.py",
    "backend/tests/test_runtime_semantics.py",
)
LOCAL_POSTGRES_SKIP_MARKERS = (
    "PostgreSQL runtime database unavailable",
    "PostgreSQL runtime test database unavailable",
)
DUCKDB_COMPATIBILITY_SKIP_MARKER = "not executable in DuckDB:"


def _module_name(testcase: ET.Element) -> str:
    return " ".join(
        part
        for part in (
            testcase.attrib.get("file", ""),
            testcase.attrib.get("classname", ""),
        )
        if part
    )


def _is_tier_a(module: str) -> bool:
    normalized = module.replace(".", "/")
    return any(
        marker in module
        or marker in normalized
        or marker.removesuffix(".py") in normalized
        for marker in TIER_A_MODULE_MARKERS
    )


def _is_allowed_skip(module: str, reason: str, *, ci: bool) -> bool:
    normalized = module.replace(".", "/")
    if (
        DUCKDB_COMPATIBILITY_SKIP_MARKER in reason
        and (
            "semantic/test_runtime_semantics.py" in normalized
            or "semantic/test_runtime_semantics" in normalized
        )
    ):
        return True
    if not ci and any(marker in reason for marker in LOCAL_POSTGRES_SKIP_MARKERS):
        return True
    return False


def find_violations(junit_path: Path, *, ci: bool = False) -> list[str]:
    """Return Tier A skip violations found in a pytest JUnit report."""
    root = ET.parse(junit_path).getroot()
    violations: list[str] = []
    for testcase in root.iter("testcase"):
        skipped = testcase.find("skipped")
        if skipped is None:
            continue
        module = _module_name(testcase)
        if not _is_tier_a(module):
            continue
        reason = skipped.attrib.get("message", "").strip() or "(no reason provided)"
        if not _is_allowed_skip(module, reason, ci=ci):
            name = f"{module}::{testcase.attrib.get('name', '<unknown>')}"
            violations.append(f"{name}: {reason}")
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", required=True, type=Path, help="pytest JUnit XML report")
    parser.add_argument(
        "--ci",
        action="store_true",
        help="Enforce CI policy: local PostgreSQL-unavailable skips are not allowed",
    )
    args = parser.parse_args(argv)
    if not args.junit.is_file():
        parser.error(f"JUnit report does not exist: {args.junit}")
    violations = find_violations(args.junit, ci=args.ci)
    if violations:
        print("Semantic Tier A skip gate failed:", file=sys.stderr)
        for violation in violations:
            print(f"- {violation}", file=sys.stderr)
        return 1
    print(f"Semantic Tier A skip gate passed: {args.junit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
