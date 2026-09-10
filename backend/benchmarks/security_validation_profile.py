#!/usr/bin/env python3
"""Profile security-validation sub-stages without changing production code."""

import argparse
import json
import platform
import time
from statistics import mean, median
from typing import Callable, Dict, List

import sqlglot

from backend.benchmarks.transpiler_benchmark import DEFAULT_STATEMENTS
from backend.core import transpiler as transpiler_module
from backend.core.config import DANGEROUS_SQL_PATTERNS, WARNING_SQL_PATTERNS
from backend.core.transpiler import SQLTranspiler, _DANGEROUS_OPERATION_PATTERN


SECURITY_CASES = [
    ("select", "SELECT id, name FROM users WHERE id > 100"),
    ("dangerous_operation", "DROP TABLE users"),
    ("dml_warning", "UPDATE users SET name = 'x'"),
    ("literal_keyword", "SELECT 'DROP TABLE users' AS text"),
    ("comment_keyword", "SELECT 1 -- DROP TABLE users"),
]


def measure(capture: Callable[[], object], repeats: int) -> List[float]:
    timings = []
    for _ in range(repeats):
        start = time.perf_counter()
        capture()
        timings.append(time.perf_counter() - start)
    return timings


def _pattern_scan(sql: str, patterns) -> None:
    for pattern, _ in patterns:
        pattern.search(sql)


def run(iterations: int, repeats: int) -> Dict[str, object]:
    statements = [DEFAULT_STATEMENTS[index % len(DEFAULT_STATEMENTS)] for index in range(iterations)]
    transpiler = SQLTranspiler()
    original_mask = transpiler_module.mask_non_executable
    masked = [original_mask(statement) for statement in statements]

    def mask_only() -> None:
        for statement in statements:
            original_mask(statement)

    def dangerous_operation_only() -> None:
        for statement in masked:
            _DANGEROUS_OPERATION_PATTERN.search(statement)

    def parse_only() -> None:
        for statement in statements:
            sqlglot.parse(statement)

    def dangerous_patterns_only() -> None:
        for statement in masked:
            _pattern_scan(statement, DANGEROUS_SQL_PATTERNS)

    def warning_patterns_only() -> None:
        for statement in masked:
            _pattern_scan(statement, WARNING_SQL_PATTERNS)

    def full_security() -> None:
        for statement in statements:
            transpiler._validate_security(statement)

    timings = {
        "mask_non_executable": measure(mask_only, repeats),
        "dangerous_operation_regex": measure(dangerous_operation_only, repeats),
        "sqlglot_parse": measure(parse_only, repeats),
        "dangerous_pattern_scan": measure(dangerous_patterns_only, repeats),
        "warning_pattern_scan": measure(warning_patterns_only, repeats),
        "validate_security": measure(full_security, repeats),
    }

    means = {name: mean(values) for name, values in timings.items()}
    per_statement_ms = {
        name: value / iterations * 1000.0 for name, value in means.items()
    }
    full_mean = means["validate_security"]
    shares = {
        name: (value / full_mean * 100.0 if full_mean else 0.0)
        for name, value in means.items()
        if name != "validate_security"
    }

    boundary_cases = []
    for name, sql in SECURITY_CASES:
        result = transpiler._validate_security(sql)
        boundary_cases.append(
            {
                "name": name,
                "sql": sql,
                "blocked": result["blocked"],
                "multiple_statements": result.get("multiple_statements", False),
                "warning_count": len(result.get("warnings", [])),
            }
        )

    return {
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "sqlglot": getattr(sqlglot, "__version__", "unknown"),
        },
        "workload": {
            "iterations": iterations,
            "repeats": repeats,
            "case_count": len(SECURITY_CASES),
            "statement_family": "existing transpiler benchmark DEFAULT_STATEMENTS",
        },
        "measurements": {
            name: {
                "mean_seconds": mean(values),
                "median_seconds": median(values),
                "per_statement_ms": per_statement_ms[name],
                "timings_seconds": values,
            }
            for name, values in timings.items()
        },
        "analysis": {
            "substage_share_of_full_validation_percent": shares,
            "full_validation_total_seconds_mean": full_mean,
            "patterns": {
                "dangerous_count": len(DANGEROUS_SQL_PATTERNS),
                "warning_count": len(WARNING_SQL_PATTERNS),
            },
        },
        "boundary_cases": boundary_cases,
        "notes": [
            "This profiler instruments only benchmark-process functions; production code is unchanged.",
            "Substage timings are isolated measurements and are not additive because they use separate runs.",
            "The full validation measurement uses SQLTranspiler._validate_security() with current repository behavior.",
            "Boundary cases include executable and masked keyword locations and record current blocking/warning behavior.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if args.iterations < 1 or args.repeats < 1:
        parser.error("iterations and repeats must be >= 1")
    print(json.dumps(run(args.iterations, args.repeats), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
