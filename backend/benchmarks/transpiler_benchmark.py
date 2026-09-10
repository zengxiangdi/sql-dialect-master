#!/usr/bin/env python3
"""Reproducible benchmark for transpiler wall time and hot-path stage cost.

The benchmark intentionally avoids a pass/fail performance threshold. Runtime
performance varies across CI and developer machines; this command is for
observability and regression investigation rather than correctness gating.
Instrumentation is applied from this benchmark process only; production code
is not modified by the profiling harness.
"""

import argparse
import asyncio
import json
import platform
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from statistics import mean, median
from typing import Callable, Dict, Iterator, List
from unittest.mock import patch

import sqlglot

from backend.core.config import settings
from backend.core.transpiler import SQLTranspiler


DEFAULT_STATEMENTS = [
    "SELECT id, name, created_at FROM users WHERE id > 100 ORDER BY created_at DESC LIMIT 50",
    "SELECT department_id, COUNT(*) AS employee_count FROM employees GROUP BY department_id",
    "SELECT o.id, o.total, c.name FROM orders o JOIN customers c ON o.customer_id = c.id",
    "SELECT DATE_FORMAT(created_at, '%Y-%m-%d') AS day, COUNT(*) FROM events GROUP BY day",
]

INVALID_INPUTS = [None, 42, True]


@dataclass
class StageRecorder:
    """Accumulate inclusive wall-clock time for instrumented callables."""

    totals: Dict[str, float] = field(default_factory=dict)
    calls: Dict[str, int] = field(default_factory=dict)

    @contextmanager
    def time_call(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            self.totals[name] = self.totals.get(name, 0.0) + elapsed
            self.calls[name] = self.calls.get(name, 0) + 1


def build_statements(iterations: int) -> List[str]:
    """Create a stable workload without depending on external data."""
    return [DEFAULT_STATEMENTS[index % len(DEFAULT_STATEMENTS)] for index in range(iterations)]


def measure_sync(
    transpiler: SQLTranspiler,
    statements: List[str],
    source: str,
    target: str,
    validate: bool = True,
) -> float:
    """Measure sequential transpilation wall-clock time."""
    start = time.perf_counter()
    for statement in statements:
        transpiler.transpile(statement, source, target, pretty=False, validate=validate)
    return time.perf_counter() - start


async def measure_async(
    transpiler: SQLTranspiler,
    statements: List[str],
    source: str,
    target: str,
    max_concurrent: int,
) -> float:
    """Measure bounded-concurrency transpilation wall-clock time."""
    start = time.perf_counter()
    await transpiler.batch_transpile_async(
        statements,
        source,
        target,
        pretty=False,
        max_concurrent=max_concurrent,
    )
    return time.perf_counter() - start


def measure_repeated(capture: Callable[[], float], repeats: int) -> List[float]:
    """Capture repeated timings in seconds."""
    return [capture() for _ in range(repeats)]


def _wrap_instance_method(
    transpiler: SQLTranspiler,
    name: str,
    recorder: StageRecorder,
    stage: str,
) -> None:
    """Wrap one bound instance method without changing production code."""
    original = getattr(transpiler, name)

    def wrapped(*args, **kwargs):
        with recorder.time_call(stage):
            return original(*args, **kwargs)

    setattr(transpiler, name, wrapped)


def _instrument_transpiler(transpiler: SQLTranspiler, recorder: StageRecorder) -> None:
    """Instrument existing transpiler stage boundaries from the benchmark process."""
    method_stages = {
        "_validate_security": "security_checks",
        "_has_multiple_statements": "statement_validation",
        "_cache_key": "cache_key",
        "_get_compatibility_notes": "compatibility_notes",
        "_generate_warnings_masked": "warnings",
        "_validate_output_detailed": "output_validation",
    }
    for name, stage in method_stages.items():
        if hasattr(transpiler, name):
            _wrap_instance_method(transpiler, name, recorder, stage)

    original_get = transpiler._cache.get
    original_set = transpiler._cache.set

    def timed_get(*args, **kwargs):
        with recorder.time_call("cache_lookup"):
            return original_get(*args, **kwargs)

    def timed_set(*args, **kwargs):
        with recorder.time_call("cache_set"):
            return original_set(*args, **kwargs)

    transpiler._cache.get = timed_get
    transpiler._cache.set = timed_set


def _measure_sqlglot_and_postprocess(
    transpiler: SQLTranspiler,
    statements: List[str],
    source: str,
    target: str,
    validate: bool,
    recorder: StageRecorder,
) -> float:
    """Measure the synchronous pipeline with SQLGlot/post-process hooks."""
    original_transpile = sqlglot.transpile
    original_process = transpiler.post_processor.process
    transpiler_module = __import__("backend.core.transpiler", fromlist=["mask_non_executable"])
    original_mask = transpiler_module.mask_non_executable

    def timed_transpile(*args, **kwargs):
        with recorder.time_call("sqlglot_transpile"):
            return original_transpile(*args, **kwargs)

    def timed_process(*args, **kwargs):
        with recorder.time_call("post_process"):
            return original_process(*args, **kwargs)

    def timed_mask(*args, **kwargs):
        with recorder.time_call("security_masking"):
            return original_mask(*args, **kwargs)

    with patch("backend.core.transpiler.sqlglot.transpile", timed_transpile), patch(
        "backend.core.transpiler.mask_non_executable", timed_mask
    ):
        transpiler.post_processor.process = timed_process
        return measure_sync(transpiler, statements, source, target, validate=validate)


def measure_input_validation(repeats: int) -> Dict[str, object]:
    """Measure the public type-validation fast path without changing behavior."""
    timings: List[float] = []
    transpiler = SQLTranspiler()
    for _ in range(repeats):
        start = time.perf_counter()
        for value in INVALID_INPUTS:
            transpiler.transpile(value, "mysql", "postgres", pretty=False)
        timings.append(time.perf_counter() - start)
    return {
        "mean_seconds": mean(timings),
        "median_seconds": median(timings),
        "timings_seconds": timings,
        "cases_per_measurement": len(INVALID_INPUTS),
    }


def profile_configuration(
    statements: List[str],
    source: str,
    target: str,
    pretty: bool,
    validate: bool,
    cache_enabled: bool,
    security_enabled: bool,
    repeats: int,
) -> Dict[str, object]:
    """Profile one stable cache/security/validation configuration."""
    previous_security = settings.security_check_enabled
    try:
        settings.security_check_enabled = security_enabled
        timings: List[float] = []
        aggregate = StageRecorder()

        for _ in range(repeats):
            transpiler = SQLTranspiler()
            transpiler._cache_enabled = cache_enabled
            _instrument_transpiler(transpiler, aggregate)
            elapsed = _measure_sqlglot_and_postprocess(
                transpiler, statements, source, target, validate, aggregate
            )
            timings.append(elapsed)

        total_mean = mean(timings)
        per_statement = {
            name: value / len(statements) / repeats
            for name, value in aggregate.totals.items()
        }
        per_statement_percent = {
            name: (value / (total_mean / len(statements)) * 100.0)
            if total_mean
            else 0.0
            for name, value in per_statement.items()
        }
        hotspots = sorted(
            per_statement_percent.items(), key=lambda item: item[1], reverse=True
        )[:2]

        return {
            "cache_enabled": cache_enabled,
            "security_enabled": security_enabled,
            "validate": validate,
            "pretty": pretty,
            "timings_seconds": timings,
            "mean_seconds": total_mean,
            "median_seconds": median(timings),
            "per_statement_seconds": per_statement,
            "stage_percent_of_mean": per_statement_percent,
            "stage_calls": aggregate.calls,
            "top_hotspots": [
                {"stage": name, "percent_of_mean": percent}
                for name, percent in hotspots
            ],
        }
    finally:
        settings.security_check_enabled = previous_security


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=100, help="Statements per measurement")
    parser.add_argument("--repeats", type=int, default=3, help="Measurements per mode")
    parser.add_argument("--concurrency", type=int, default=8, help="Async concurrency limit")
    parser.add_argument("--source", default="mysql", help="Source dialect")
    parser.add_argument("--target", default="postgres", help="Target dialect")
    args = parser.parse_args()

    if args.iterations < 1 or args.repeats < 1 or args.concurrency < 1:
        parser.error("iterations, repeats, and concurrency must all be >= 1")

    statements = build_statements(args.iterations)

    # Preserve the historical wall-clock benchmark: cache-disabled sync/async.
    baseline_transpiler = SQLTranspiler()
    baseline_transpiler._cache_enabled = False
    sync_timings = measure_repeated(
        lambda: measure_sync(baseline_transpiler, statements, args.source, args.target),
        args.repeats,
    )
    async_timings = measure_repeated(
        lambda: asyncio.run(
            measure_async(
                baseline_transpiler,
                statements,
                args.source,
                args.target,
                args.concurrency,
            )
        ),
        args.repeats,
    )

    sync_mean = mean(sync_timings)
    async_mean = mean(async_timings)
    speedup = sync_mean / async_mean if async_mean > 0 else None

    configurations = []
    for cache_enabled in (False, True):
        for security_enabled in (False, True):
            for validate in (False, True):
                configurations.append(
                    profile_configuration(
                        statements,
                        args.source,
                        args.target,
                        pretty=False,
                        validate=validate,
                        cache_enabled=cache_enabled,
                        security_enabled=security_enabled,
                        repeats=args.repeats,
                    )
                )

    print(json.dumps({
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "sqlglot": getattr(sqlglot, "__version__", "unknown"),
        },
        "workload": {
            "iterations": args.iterations,
            "repeats": args.repeats,
            "source": args.source,
            "target": args.target,
        },
        "input_validation": measure_input_validation(args.repeats),
        "async": {
            "max_concurrent": args.concurrency,
            "timings_seconds": async_timings,
            "mean_seconds": async_mean,
        },
        "sync": {
            "timings_seconds": sync_timings,
            "mean_seconds": sync_mean,
        },
        "async_speedup": speedup,
        "profiling": {
            "stage_timing_model": "inclusive",
            "configurations": configurations,
            "notes": [
                "Stage timings are benchmark-process instrumentation, not production telemetry.",
                "Stage percentages are inclusive and can overlap when one measured call invokes another.",
                "Input validation is measured separately on invalid public inputs because successful-path type checks are inline.",
                "validate is a function argument rather than an application settings switch.",
                "Cache-enabled measurements use a new transpiler per repeat, so each run starts cold.",
                "top_hotspots ranks the two largest inclusive contributors for each configuration.",
            ],
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
