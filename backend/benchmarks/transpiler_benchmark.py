#!/usr/bin/env python3
"""Small reproducible benchmark for synchronous vs asynchronous transpilation.

The benchmark intentionally avoids a pass/fail performance threshold. Runtime
performance varies across CI and developer machines; this command is for
observability and regression investigation rather than correctness gating.
"""

import argparse
import asyncio
import json
import time
from statistics import mean
from typing import Callable, List

from backend.core.transpiler import SQLTranspiler


DEFAULT_STATEMENTS = [
    "SELECT id, name, created_at FROM users WHERE id > 100 ORDER BY created_at DESC LIMIT 50",
    "SELECT department_id, COUNT(*) AS employee_count FROM employees GROUP BY department_id",
    "SELECT o.id, o.total, c.name FROM orders o JOIN customers c ON o.customer_id = c.id",
    "SELECT DATE_FORMAT(created_at, '%Y-%m-%d') AS day, COUNT(*) FROM events GROUP BY day",
]


def build_statements(iterations: int) -> List[str]:
    """Create a stable workload without depending on external data."""
    return [DEFAULT_STATEMENTS[index % len(DEFAULT_STATEMENTS)] for index in range(iterations)]


def measure_sync(
    transpiler: SQLTranspiler,
    statements: List[str],
    source: str,
    target: str,
) -> float:
    """Measure sequential transpilation wall-clock time."""
    start = time.perf_counter()
    for statement in statements:
        transpiler.transpile(statement, source, target, pretty=False)
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
    transpiler = SQLTranspiler()
    # Benchmark CPU/transpilation work rather than cache retrieval latency.
    transpiler._cache_enabled = False

    sync_timings = measure_repeated(
        lambda: measure_sync(transpiler, statements, args.source, args.target),
        args.repeats,
    )
    async_timings = measure_repeated(
        lambda: asyncio.run(
            measure_async(
                transpiler,
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

    print(json.dumps({
        "workload": {
            "iterations": args.iterations,
            "repeats": args.repeats,
            "source": args.source,
            "target": args.target,
        },
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
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
