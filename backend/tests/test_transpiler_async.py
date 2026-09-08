"""Regression tests for asynchronous batch transpilation."""

import asyncio
import threading
import time

from backend.core.transpiler import SQLTranspiler, TranspileResult


def test_batch_transpile_async_honors_concurrency_and_order(monkeypatch) -> None:
    """Async batches cap worker concurrency while preserving input order."""
    transpiler = SQLTranspiler()
    statements = [f"SELECT {index}" for index in range(6)]
    lock = threading.Lock()
    active = 0
    max_active = 0

    def fake_transpile(sql: str, source: str, target: str, pretty: bool = True):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return TranspileResult(
            success=True,
            source_sql=sql,
            target_sql=sql,
            source_dialect=source,
            target_dialect=target,
        )

    monkeypatch.setattr(transpiler, "transpile", fake_transpile)

    async def run_batch():
        return await transpiler.batch_transpile_async(
            statements,
            "mysql",
            "postgres",
            max_concurrent=2,
        )

    results = asyncio.run(run_batch())

    assert max_active <= 2
    assert [result.source_sql for result in results] == statements
    assert all(result.success for result in results)
