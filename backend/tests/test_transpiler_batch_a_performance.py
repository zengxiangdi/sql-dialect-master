"""Regression tests for batch A parser reuse and fast paths."""

from __future__ import annotations

import inspect
from collections import Counter

import sqlglot

import backend.core.transpiler as transpiler_module
from backend.core.config import settings
from backend.core.transpiler import (
    SQLTranspiler,
    _contains_clause_construct,
    _contains_type_construct,
)


def _transpiler(monkeypatch) -> SQLTranspiler:
    monkeypatch.setattr(settings, "security_check_enabled", False)
    instance = SQLTranspiler()
    instance._cache_enabled = False
    return instance


def test_compatibility_notes_reuse_one_clause_parse(monkeypatch):
    sql = "SELECT id FROM users LIMIT 5"
    calls: list[tuple[str, str | None, list[str]]] = []
    original = sqlglot.parse_one

    def counted_parse_one(statement, read=None, **kwargs):
        calls.append(
            (statement, read, [frame.function for frame in inspect.stack()[1:8]])
        )
        return original(statement, read=read, **kwargs)

    monkeypatch.setattr(transpiler_module.sqlglot, "parse_one", counted_parse_one)
    result = _transpiler(monkeypatch).transpile(
        sql, "mysql", "postgres", pretty=False, validate=True
    )

    assert result.success is True
    # The source compatibility evidence has one lazy AST, even though LIMIT
    # is checked from several note paths.  The target output is parsed once by
    # target validation; no MySQL normalization AST is needed for this SQL.
    source_calls = [call for call in calls if call[:2] == (sql, "mysql")]
    clause_calls = [
        call for call in calls if "_contains_clause_construct" in call[2]
    ]
    assert len(source_calls) <= 1
    assert len(clause_calls) <= 1
    assert len(calls) == 2


def test_construct_evidence_parse_failure_is_fail_closed(monkeypatch):
    def fail_parse_one(*args, **kwargs):
        raise ValueError("synthetic parse failure")

    monkeypatch.setattr(transpiler_module.sqlglot, "parse_one", fail_parse_one)
    assert _contains_type_construct(
        "CREATE TABLE t (payload JSON)", "mysql", "JSON"
    ) is False
    assert _contains_clause_construct(
        "SELECT * FROM t LIMIT 1", "mysql", "LIMIT"
    ) is False


def test_postgres_array_type_evidence_keeps_compatibility_note(monkeypatch):
    notes = SQLTranspiler()._get_compatibility_notes(
        "postgres",
        "mysql",
        source_sql="CREATE TABLE t (tags INTEGER[])",
        final_sql="CREATE TABLE t (tags JSON)",
    )
    assert "ARRAY types → JSON transformation" in notes


def test_mysql_plain_query_skips_ast_normalization(monkeypatch):
    sql = "SELECT id, name FROM users WHERE id > 100"
    calls = Counter()
    original = sqlglot.parse_one
    original_transpile = sqlglot.transpile

    def counted_parse_one(statement, read=None, **kwargs):
        calls["parse_one"] += 1
        return original(statement, read=read, **kwargs)

    def counted_transpile(*args, **kwargs):
        calls["transpile"] += 1
        return original_transpile(*args, **kwargs)

    monkeypatch.setattr(transpiler_module.sqlglot, "parse_one", counted_parse_one)
    monkeypatch.setattr(transpiler_module.sqlglot, "transpile", counted_transpile)
    result = _transpiler(monkeypatch).transpile(
        sql, "mysql", "postgres", pretty=False, validate=False
    )

    assert result.success is True
    assert result.target_sql == "SELECT id, name FROM users WHERE id > 100"
    assert calls == Counter({"transpile": 1})

    # Target-MySQL normalization is a no-op and must take the same direct
    # transpile path without an AST pre-pass.
    calls.clear()
    result = _transpiler(monkeypatch).transpile(
        sql, "mysql", "mysql", pretty=False, validate=False
    )
    assert result.success is True
    assert calls == Counter({"transpile": 1})


def test_mysql_ast_normalizations_keep_target_sql_and_notes(monkeypatch):
    cases = [
        (
            "SELECT DATE_SUB(created_at, INTERVAL 3 DAY) AS x FROM t",
            "oracle",
            "SELECT created_at - INTERVAL 3 DAY AS x FROM t",
            ["Converted MySQL DATE_SUB interval to oracle date arithmetic"],
        ),
        (
            "SELECT DATEDIFF(end_date, start_date) AS x FROM t",
            "oracle",
            "SELECT TRUNC(end_date) - TRUNC(start_date) AS x FROM t",
            ["Converted MySQL DATEDIFF to oracle date arithmetic"],
        ),
        (
            "SELECT CONCAT(first_name, last_name) AS x FROM t",
            "postgres",
            "SELECT CONCAT(first_name, last_name) AS x FROM t",
            ["Preserved variadic CONCAT for postgres string coercion"],
        ),
        (
            "SELECT a, SUM(b) FROM t GROUP BY a WITH ROLLUP",
            "postgres",
            "SELECT a, SUM(b) FROM t GROUP BY ROLLUP (a)",
            ["Converted MySQL WITH ROLLUP to postgres ROLLUP(...) syntax"],
        ),
        (
            "SELECT DATE_FORMAT(created_at, '%Y-%m-%d') AS day FROM t",
            "snowflake",
            "SELECT TO_CHAR(CAST(created_at AS TIMESTAMP), 'YYYY-MM-DD') AS day FROM t",
            ["Normalized Snowflake date format tokens"],
        ),
        (
            "SELECT ROUND(amount, 2) AS x FROM t",
            "postgres",
            "SELECT ROUND(CAST(amount AS DECIMAL), 2) AS x FROM t",
            ["Cast PostgreSQL ROUND value to NUMERIC for two-argument rounding"],
        ),
        (
            "SELECT JSON_OBJECT('id', id) AS x FROM t",
            "postgres",
            "SELECT JSON_BUILD_OBJECT('id', id) AS x FROM t",
            ["Converted JSON_OBJECT to JSON_BUILD_OBJECT"],
        ),
        (
            "SELECT JSON_ARRAYAGG(JSON_OBJECT('id', id)) FROM t",
            "postgres",
            "SELECT JSON_AGG(JSON_BUILD_OBJECT('id', id)) FROM t",
            [
                "Converted JSON_ARRAYAGG(JSON_OBJECT(...)) to JSON_AGG(JSON_BUILD_OBJECT(...))"
            ],
        ),
        (
            "SELECT NOW() AS x FROM t",
            "oracle",
            "SELECT SYSDATE AS x FROM t",
            ["Converted NOW to SYSDATE (AST)"],
        ),
    ]

    for sql, target, expected_sql, expected_notes in cases:
        result = _transpiler(monkeypatch).transpile(
            sql, "mysql", target, pretty=False, validate=False
        )
        assert result.success is True, (sql, result.error)
        assert result.target_sql == expected_sql
        assert result.transformations == expected_notes


def test_group_concat_guard_prefilters_non_executable_text(monkeypatch):
    calls = 0
    original = sqlglot.parse_one

    def counted_parse_one(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(transpiler_module.sqlglot, "parse_one", counted_parse_one)
    transpiler = SQLTranspiler()
    for sql in (
        "SELECT id FROM users",
        "SELECT 'GROUP_CONCAT(name)' AS message",
        "-- GROUP_CONCAT(name)\nSELECT 1",
        "SELECT schema$GROUP_CONCAT(name) FROM users",
    ):
        assert transpiler._group_concat_dynamic_separator(sql) is False
    assert calls == 0


def test_group_concat_dynamic_separator_still_fails_closed(monkeypatch):
    calls = 0
    original = sqlglot.parse_one

    def counted_parse_one(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(transpiler_module.sqlglot, "parse_one", counted_parse_one)
    assert SQLTranspiler()._group_concat_dynamic_separator(
        "SELECT GROUP_CONCAT(name SEPARATOR separator_name) FROM users"
    ) is True
    assert calls == 1


def test_security_reuses_raw_ast_between_dangerous_and_system_checks(monkeypatch):
    calls = 0
    original = sqlglot.parse

    def counted_parse(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(transpiler_module.sqlglot, "parse", counted_parse)
    result = SQLTranspiler()._validate_security(
        "DROP TABLE information_schema.tables",
        dialect="mysql",
        block_dangerous=False,
    )

    assert result["blocked"] is False
    assert calls == 1
    assert any("Dangerous SQL operation detected: DROP" in w for w in result["warnings"])
    assert any("System table access detected" in w for w in result["warnings"])

    calls = 0
    result = SQLTranspiler()._validate_security(
        "DROP TABLE users; SELECT 1--x",
        dialect="mysql",
        block_dangerous=False,
    )
    assert result["multiple_statements"] is True
    # The raw dangerous-operation parse and the prepared multi-statement parse
    # are distinct modes, each cached once for this call.
    assert calls == 2

