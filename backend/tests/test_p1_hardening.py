import asyncio

from backend.api import readiness
from backend.core.post_processor import PostProcessor
from backend.core.transpiler import SQLTranspiler


def test_transpiler_rejects_stacked_statements():
    result = SQLTranspiler().transpile(
        "SELECT 1; SELECT 2",
        "mysql",
        "postgres",
    )

    assert result.success is False
    assert result.error_code == "SECURITY_VIOLATION"
    assert "Multiple SQL statements" in result.error


def test_transpiler_accepts_one_statement_with_terminal_semicolon():
    result = SQLTranspiler().transpile(
        "SELECT 1;",
        "mysql",
        "postgres",
    )

    assert result.success is True
    assert result.target_sql


def test_top_conversion_does_not_rewrite_sql_literal():
    processor = PostProcessor()
    sql = "SELECT 'SELECT TOP 5 value' AS message"

    result, notes = processor._convert_top_to_limit(sql)

    assert result == sql
    assert notes == []


def test_group_concat_conversion_does_not_rewrite_sql_literal():
    processor = PostProcessor()
    sql = "SELECT 'GROUP_CONCAT(name)' AS message"

    result, notes = processor._fix_group_concat_default_separator(sql)

    assert result == sql
    assert notes == []


def test_readiness_probe_is_cached_and_single_flight(monkeypatch):
    async def exercise():
        calls = 0

        def fake_checks():
            nonlocal calls
            calls += 1
            return {
                "transpiler": {"status": "ok"},
                "functions": {"status": "ok"},
                "types": {"status": "ok"},
                "nl2sql": {"status": "ok"},
            }

        monkeypatch.setattr(readiness, "_run_checks", fake_checks)
        readiness._cached_checks = None
        readiness._cached_at = 0.0

        first, second = await asyncio.gather(
            readiness._get_checks(),
            readiness._get_checks(),
        )

        assert first == second
        assert calls == 1

    asyncio.run(exercise())
