"""Unit tests for the semantic evidence skip gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts" / "verify_semantic_evidence.py"
SPEC = importlib.util.spec_from_file_location("verify_semantic_evidence", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _write_report(tmp_path: Path, testcase: str) -> Path:
    report = tmp_path / "semantic.xml"
    report.write_text(
        f"<?xml version='1.0'?><testsuites><testsuite>{testcase}</testsuite></testsuites>",
        encoding="utf-8",
    )
    return report


def _case(*, file: str, name: str = "test_case", reason: str | None = None) -> str:
    skipped = "" if reason is None else f'<skipped message="{reason}" />'
    return f'<testcase classname="semantic" name="{name}" file="{file}">{skipped}</testcase>'


def test_no_skip_passes(tmp_path):
    report = _write_report(
        tmp_path,
        '<testcase classname="semantic" name="test_case" file="test_duckdb_runtime.py" />',
    )
    assert MODULE.main(["--junit", str(report), "--ci"]) == 0


def test_tier_a_skip_fails_in_ci(tmp_path):
    report = _write_report(
        tmp_path,
        _case(
            file="backend/tests/semantic/test_postgres_runtime.py",
            reason="PostgreSQL runtime database unavailable",
        ),
    )
    assert MODULE.main(["--junit", str(report), "--ci"]) == 1


def test_local_postgres_environment_skip_is_allowed(tmp_path):
    report = _write_report(
        tmp_path,
        _case(
            file="backend/tests/semantic/test_postgres_runtime.py",
            reason="PostgreSQL runtime database unavailable",
        ),
    )
    assert MODULE.find_violations(report, ci=False) == []


def test_explicit_duckdb_compatibility_skip_is_whitelisted(tmp_path):
    report = _write_report(
        tmp_path,
        _case(
            file="backend/tests/semantic/test_runtime_semantics.py",
            reason="Source SQL not executable in DuckDB: known dialect limitation",
        ),
    )
    assert MODULE.main(["--junit", str(report), "--ci"]) == 0


def test_unknown_tier_a_skip_fails_even_locally(tmp_path):
    report = _write_report(
        tmp_path,
        _case(
            file="backend/tests/semantic/test_duckdb_runtime.py",
            reason="duckdb is missing",
        ),
    )
    assert MODULE.find_violations(report, ci=False)
