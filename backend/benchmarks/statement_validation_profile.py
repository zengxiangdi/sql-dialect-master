#!/usr/bin/env python3
"""Profile the statement-validation cost without changing production code."""

import argparse
import json
import platform
import time
from statistics import mean, median
from typing import Callable, List

import sqlglot

from backend.benchmarks.transpiler_benchmark import build_statements
from backend.core.transpiler import SQLTranspiler


def measure(capture: Callable[[], object], repeats: int) -> List[float]:
    timings = []
    for _ in range(repeats):
        start = time.perf_counter()
        capture()
        timings.append(time.perf_counter() - start)
    return timings


def run(iterations: int, repeats: int, dialect: str) -> dict:
    statements = build_statements(iterations)
    transpiler = SQLTranspiler()

    def validate_only() -> None:
        for statement in statements:
            transpiler._has_multiple_statements(statement)

    def parse_only() -> None:
        for statement in statements:
            sqlglot.parse(statement)

    def parse_and_count() -> None:
        for statement in statements:
            len(sqlglot.parse(statement)) > 1

    validation = measure(validate_only, repeats)
    parsing = measure(parse_only, repeats)
    parse_count = measure(parse_and_count, repeats)

    validation_mean = mean(validation)
    parsing_mean = mean(parsing)
    parse_count_mean = mean(parse_count)
    per_statement = iterations

    return {
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "sqlglot": getattr(sqlglot, "__version__", "unknown"),
        },
        "workload": {
            "iterations": iterations,
            "repeats": repeats,
            "dialect": dialect,
        },
        "measurements": {
            "has_multiple_statements": {
                "mean_seconds": validation_mean,
                "median_seconds": median(validation),
                "per_statement_ms": validation_mean / per_statement * 1000,
                "timings_seconds": validation,
            },
            "sqlglot_parse_only": {
                "mean_seconds": parsing_mean,
                "median_seconds": median(parsing),
                "per_statement_ms": parsing_mean / per_statement * 1000,
                "timings_seconds": parsing,
            },
            "sqlglot_parse_and_count": {
                "mean_seconds": parse_count_mean,
                "median_seconds": median(parse_count),
                "per_statement_ms": parse_count_mean / per_statement * 1000,
                "timings_seconds": parse_count,
            },
        },
        "analysis": {
            "parse_share_of_statement_validation_percent": (
                parsing_mean / validation_mean * 100.0 if validation_mean else 0.0
            ),
            "parse_and_count_share_percent": (
                parse_count_mean / validation_mean * 100.0 if validation_mean else 0.0
            ),
            "validation_over_parse_ms": (
                (validation_mean - parsing_mean) / per_statement * 1000
            ),
            "validation_over_parse_and_count_ms": (
                (validation_mean - parse_count_mean) / per_statement * 1000
            ),
        },
        "notes": [
            "This profiler instruments only benchmark-process functions; production code is unchanged.",
            "_has_multiple_statements currently delegates to sqlglot.parse() and checks the parsed statement count.",
            "Measurements use the same stable workload family as the main transpiler benchmark.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--dialect", default="mysql")
    args = parser.parse_args()
    if args.iterations < 1 or args.repeats < 1:
        parser.error("iterations and repeats must be >= 1")
    print(json.dumps(run(args.iterations, args.repeats, args.dialect), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
