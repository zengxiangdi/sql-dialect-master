#!/usr/bin/env python3
"""Profile security-validation sub-stages and boundary cases."""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from backend.core import transpiler as transpiler_module
from backend.core.config import DANGEROUS_SQL_PATTERNS, WARNING_SQL_PATTERNS
from backend.core.transpiler import SQLTranspiler, _DANGEROUS_OPERATION_PATTERN

DEFAULT_STATEMENTS = [
    "SELECT id, name FROM users WHERE status = 'active'",
    "SELECT * FROM orders WHERE created_at >= '2026-01-01' ORDER BY created_at DESC",
    "INSERT INTO users (id, name) VALUES (1, 'alice')",
    "UPDATE users SET status = 'inactive' WHERE id = 1",
    "DELETE FROM sessions WHERE expires_at < CURRENT_TIMESTAMP",
    "DROP TABLE IF EXISTS scratch_users",
    "SELECT 'DROP TABLE' AS note",
    "SELECT 1 -- DROP TABLE should not be executable\n",
    "SELECT 1; SELECT 2",
    "SELECT ';' AS value",
]


def _time_call(fn, repeats: int) -> list[float]:
    samples: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - started)
    return samples


def _summary(samples: list[float]) -> dict[str, float]:
    return {
        "mean_seconds": statistics.mean(samples),
        "median_seconds": statistics.median(samples),
        "min_seconds": min(samples),
        "max_seconds": max(samples),
    }


def _measure(name: str, fn, statements: list[str], repeats: int) -> dict:
    samples: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        for sql in statements:
            fn(sql)
        samples.append(time.perf_counter() - started)
    summary = _summary(samples)
    total_statements = len(statements) * repeats
    summary["per_statement_ms"] = summary["mean_seconds"] / len(statements) * 1000
    summary["name"] = name
    summary["statements"] = len(statements)
    summary["repeats"] = repeats
    summary["total_statement_calls"] = total_statements
    return summary


def _profile_default(repeats: int) -> dict[str, dict]:
    transpiler = SQLTranspiler()
    statements = DEFAULT_STATEMENTS
    measurements = {
        "mask_non_executable": _measure(
            "mask_non_executable",
            transpiler_module.mask_non_executable,
            statements,
            repeats,
        ),
        "dangerous_operation_regex": _measure(
            "dangerous_operation_regex",
            lambda sql: _DANGEROUS_OPERATION_PATTERN.search(
                transpiler_module.mask_non_executable(sql)
            ),
            statements,
            repeats,
        ),
        "has_multiple_statements": _measure(
            "has_multiple_statements",
            SQLTranspiler._has_multiple_statements,
            statements,
            repeats,
        ),
        "dangerous_pattern_scan": _measure(
            "dangerous_pattern_scan",
            lambda sql: [p.search(transpiler_module.mask_non_executable(sql)) for p, _ in DANGEROUS_SQL_PATTERNS],
            statements,
            repeats,
        ),
        "warning_pattern_scan": _measure(
            "warning_pattern_scan",
            lambda sql: [p.search(transpiler_module.mask_non_executable(sql)) for p, _ in WARNING_SQL_PATTERNS],
            statements,
            repeats,
        ),
        "validate_security": _measure(
            "validate_security",
            transpiler._validate_security,
            statements,
            repeats,
        ),
    }
    parse_only = _measure("sqlglot_parse_only", transpiler_module.sqlglot.parse, statements, repeats)
    measurements["sqlglot_parse_only"] = parse_only
    measurements["sqlglot_parse_and_count"] = _measure(
        "sqlglot_parse_and_count",
        lambda sql: len(transpiler_module.sqlglot.parse(sql)) > 1,
        statements,
        repeats,
    )
    return measurements


def _profile_boundaries(repeats: int) -> dict[str, dict]:
    cases = {
        "plain_select": "SELECT 1",
        "dangerous_operation": "DROP TABLE users",
        "dml_warning": "DELETE FROM users",
        "keyword_in_string": "SELECT 'DROP TABLE users; SELECT 2'",
        "keyword_in_comment": "SELECT 1 -- DROP TABLE; SELECT 2\n",
        "real_multi_statement": "SELECT 1; SELECT 2",
    }
    transpiler = SQLTranspiler()
    return {
        name: {
            "sql": sql,
            "validate_security": _summary(_time_call(lambda sql=sql: transpiler._validate_security(sql), repeats)),
            "has_multiple_statements": _summary(
                _time_call(lambda sql=sql: SQLTranspiler._has_multiple_statements(sql), repeats)
            ),
            "expected_multiple_statements": name == "real_multi_statement",
        }
        for name, sql in cases.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--output", type=Path, default=Path("security-validation-profile.json"))
    args = parser.parse_args()

    statements = DEFAULT_STATEMENTS * max(1, args.iterations // len(DEFAULT_STATEMENTS))
    transpiler = SQLTranspiler()
    measurements = _profile_default(args.repeats)
    batch_validation = _measure(
        "validate_security_benchmark_workload",
        transpiler._validate_security,
        statements,
        args.repeats,
    )
    parse_share = (
        measurements["sqlglot_parse_only"]["mean_seconds"]
        / measurements["validate_security"]["mean_seconds"]
        * 100
    )

    payload = {
        "runtime": {
            "python": __import__("platform").python_version(),
            "sqlglot": __import__("sqlglot").__version__,
        },
        "workload": {"iterations": len(statements), "repeats": args.repeats},
        "measurements": measurements,
        "benchmark_validation": batch_validation,
        "boundary_cases": _profile_boundaries(args.repeats),
        "analysis": {
            "parse_share_of_statement_validation_percent": parse_share,
            "dominant_stage": "sqlglot_parse_only" if measurements["sqlglot_parse_only"]["mean_seconds"] == max(m["mean_seconds"] for m in measurements.values() if isinstance(m, dict) and "mean_seconds" in m) else "other",
        },
    }
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
