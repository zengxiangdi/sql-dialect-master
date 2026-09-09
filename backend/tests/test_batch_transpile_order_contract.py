import asyncio

from backend.core.transpiler import SQLTranspiler


def test_batch_transpile_preserves_input_order() -> None:
    transpiler = SQLTranspiler()
    statements = [
        "SELECT 1 AS first",
        "SELECT 2 AS second",
        "SELECT 3 AS third",
    ]

    results = transpiler.batch_transpile(statements, "postgres", "postgres")

    assert [result.source_sql for result in results] == statements
    assert [result.success for result in results] == [True, True, True]
    assert [result.target_dialect for result in results] == ["postgres"] * 3


def test_batch_transpile_isolates_item_failures() -> None:
    transpiler = SQLTranspiler()
    statements = [
        "SELECT 1 AS first",
        "DROP TABLE users",
        "SELECT 3 AS third",
    ]

    results = transpiler.batch_transpile(statements, "postgres", "postgres")

    assert [result.source_sql for result in results] == statements
    assert results[0].success is True
    assert results[1].success is False
    assert results[1].error_code == "SECURITY_VIOLATION"
    assert results[2].success is True


async def _run_async_batch() -> None:
    transpiler = SQLTranspiler()
    statements = [
        "SELECT 10 AS first",
        "SELECT 20 AS second",
        "DROP TABLE users",
        "SELECT 40 AS fourth",
    ]

    results = await transpiler.batch_transpile_async(
        statements,
        "postgres",
        "postgres",
        max_concurrent=2,
    )

    assert [result.source_sql for result in results] == statements
    assert [result.success for result in results] == [True, True, False, True]
    assert results[2].error_code == "SECURITY_VIOLATION"


def test_batch_transpile_async_preserves_input_order_and_isolation() -> None:
    asyncio.run(_run_async_batch())
