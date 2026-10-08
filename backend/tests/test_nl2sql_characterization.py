"""P8 NL2SQL characterization tests.

Locks the current generate() behavior via golden snapshots so that every
module migration step in the P8 architecture split is independently
verifiable.

Golden snapshots live in ``data/nl2sql_golden.json`` and are generated
one-time by ``data/dump_nl2sql_golden.py``.  The test reads the file and
asserts equality — it never recomputes the values.

Locked fields per case:
    success, sql, explanation, suggestions, input_text
``confidence`` is NOT locked (it is locky); G2 already tests
``evidence.score == confidence``.

Named gates (structural assertions, not just golden equality):
    D1 — date arithmetic canonical forms per dialect
    D2 — relational EXISTS / NOT EXISTS
    G1 — fail-closed for unknown relationships
    P0 — dialect-specific SQL forms (top-N limit forms, date forms)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import sqlglot

from backend.core.nl2sql import NL2SQLGenerator

GOLDEN_PATH = Path(__file__).resolve().parent / "data" / "nl2sql_golden.json"

with open(GOLDEN_PATH, encoding="utf-8") as _f:
    _GOLDEN: dict = json.load(_f)

DIALECTS = [
    "mysql", "postgres", "oracle", "tsql", "hive", "spark",
    "trino", "databricks", "snowflake", "redshift", "clickhouse", "duckdb",
]


# =============================================================================
# Helpers
# =============================================================================

def _result_fields(result, prompt: str) -> dict:
    return {
        "success": result.success,
        "sql": result.sql,
        "explanation": result.explanation,
        "suggestions": list(result.suggestions),
        "input_text": prompt,
    }


def _sql_without_comments(sql: str | None) -> str:
    if sql is None:
        return ""
    return "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))


def _parse(sql: str, dialect: str):
    return sqlglot.parse_one(_sql_without_comments(sql), read=dialect)


# =============================================================================
# Golden matrix — 12 dialects × 6 prompts
# =============================================================================

class TestGoldenMatrix:
    """Verify every (dialect, prompt) pair matches its golden snapshot."""

    @pytest.mark.parametrize("key,expected", sorted(_GOLDEN["matrix"].items()))
    def test_matrix_case(self, key: str, expected: dict):
        dialect, prompt = key.split("::", 1)
        result = NL2SQLGenerator().generate(prompt, dialect=dialect)
        actual = _result_fields(result, prompt)
        assert actual == expected, (
            f"Golden mismatch for {key!r}:\n"
            f"  actual:    {json.dumps(actual, ensure_ascii=False)}\n"
            f"  expected:  {json.dumps(expected, ensure_ascii=False)}"
        )

    @pytest.mark.parametrize("key,expected", sorted(_GOLDEN["matrix"].items()))
    def test_matrix_sql_is_none_iff_failure(self, key: str, expected: dict):
        """sql is None if and only if success is False."""
        dialect, prompt = key.split("::", 1)
        result = NL2SQLGenerator().generate(prompt, dialect=dialect)
        assert (result.sql is None) == (not result.success), (
            f"Inconsistent sql/success for {key!r}: "
            f"sql={result.sql!r}, success={result.success}"
        )


# =============================================================================
# D1: Date arithmetic — golden equality
# =============================================================================

class TestD1DateArithmeticGolden:
    @pytest.mark.parametrize("key,expected", sorted(_GOLDEN["d1_date_arithmetic"].items()))
    def test_d1_case(self, key: str, expected: dict):
        # key = "D1::<dialect>::<prompt>"
        parts = key.split("::")
        assert len(parts) == 3, f"Malformed D1 key: {key!r}"
        dialect, prompt = parts[1], parts[2]
        result = NL2SQLGenerator().generate(prompt, dialect=dialect)
        actual = _result_fields(result, prompt)
        assert actual == expected, (
            f"D1 golden mismatch for {key!r}:\n"
            f"  actual:    {json.dumps(actual, ensure_ascii=False)}\n"
            f"  expected:  {json.dumps(expected, ensure_ascii=False)}"
        )


# =============================================================================
# D1: Structural — canonical date forms per dialect
# =============================================================================

class TestD1DateArithmeticStructure:
    """Verify the canonical date expression forms are correct per dialect."""

    def test_today_postgres(self):
        r = NL2SQLGenerator().generate("查询今天的订单", "postgres")
        assert r.success
        assert "date = CURRENT_DATE" in r.sql

    def test_yesterday_postgres(self):
        r = NL2SQLGenerator().generate("show yesterday's orders", "postgres")
        assert r.success
        assert "CURRENT_DATE - INTERVAL '1 days'" in r.sql

    def test_yesterday_mysql(self):
        r = NL2SQLGenerator().generate("show yesterday's orders", "mysql")
        assert r.success
        assert "DATE_SUB(CURRENT_DATE, INTERVAL 1 DAY)" in r.sql

    def test_yesterday_oracle(self):
        r = NL2SQLGenerator().generate("show yesterday's orders", "oracle")
        assert r.success
        assert "TRUNC(SYSDATE) - 1" in r.sql

    def test_yesterday_tsql(self):
        r = NL2SQLGenerator().generate("show yesterday's orders", "tsql")
        assert r.success
        assert "DATEADD(DAY, -1, CAST(GETDATE() AS DATE))" in r.sql

    def test_yesterday_hive(self):
        r = NL2SQLGenerator().generate("show yesterday's orders", "hive")
        assert r.success
        assert "DATE_SUB(CURRENT_DATE, 1)" in r.sql

    def test_last_7_days_postgres(self):
        r = NL2SQLGenerator().generate("查询最近7天的订单", "postgres")
        assert r.success
        assert "CURRENT_DATE - INTERVAL '7 days'" in r.sql

    def test_last_7_days_mysql(self):
        r = NL2SQLGenerator().generate("查询最近7天的订单", "mysql")
        assert r.success
        assert "DATE_SUB(CURRENT_DATE, INTERVAL 7 DAY)" in r.sql

    def test_last_7_days_oracle(self):
        r = NL2SQLGenerator().generate("查询最近7天的订单", "oracle")
        assert r.success
        assert "TRUNC(SYSDATE) - 7" in r.sql

    def test_last_7_days_tsql(self):
        r = NL2SQLGenerator().generate("查询最近7天的订单", "tsql")
        assert r.success
        assert "DATEADD(DAY, -7, CAST(GETDATE() AS DATE))" in r.sql

    def test_last_7_days_hive(self):
        r = NL2SQLGenerator().generate("查询最近7天的订单", "hive")
        assert r.success
        assert "DATE_SUB(CURRENT_DATE, 7)" in r.sql

    def test_last_3_weeks_postgres(self):
        r = NL2SQLGenerator().generate("查询最近3周的订单", "postgres")
        assert r.success
        assert "CURRENT_DATE - INTERVAL '21 days'" in r.sql

    def test_last_2_months_mysql(self):
        r = NL2SQLGenerator().generate("查询最近2月的订单", "mysql")
        assert r.success
        assert "DATE_SUB(CURRENT_DATE, INTERVAL 2 MONTH)" in r.sql

    def test_last_1_year_oracle(self):
        r = NL2SQLGenerator().generate("查询最近1年的订单", "oracle")
        assert r.success
        assert "ADD_MONTHS(TRUNC(SYSDATE), -12)" in r.sql

    def test_last_1_year_tsql(self):
        r = NL2SQLGenerator().generate("查询最近1年的订单", "tsql")
        assert r.success
        assert "DATEADD(MONTH, -12, CAST(GETDATE() AS DATE))" in r.sql

    def test_last_1_year_hive(self):
        r = NL2SQLGenerator().generate("查询最近1年的订单", "hive")
        assert r.success
        assert "ADD_MONTHS(CURRENT_DATE, -12)" in r.sql


# =============================================================================
# D2: Relational EXISTS / NOT EXISTS — golden + structural
# =============================================================================

class TestD2RelationalGolden:
    @pytest.mark.parametrize("key,expected", sorted(_GOLDEN["d2_relational"].items()))
    def test_d2_case(self, key: str, expected: dict):
        parts = key.split("::")
        assert len(parts) == 3, f"Malformed D2 key: {key!r}"
        dialect, prompt = parts[1], parts[2]
        result = NL2SQLGenerator().generate(prompt, dialect=dialect)
        actual = _result_fields(result, prompt)
        assert actual == expected, (
            f"D2 golden mismatch for {key!r}:\n"
            f"  actual:    {json.dumps(actual, ensure_ascii=False)}\n"
            f"  expected:  {json.dumps(expected, ensure_ascii=False)}"
        )


class TestD2RelationalStructure:
    def test_users_with_orders_postgres_uses_exists(self):
        r = NL2SQLGenerator().generate("find users who have orders", "postgres")
        assert r.success
        assert "WHERE EXISTS" in r.sql
        assert "users.id = orders.user_id" in r.sql
        tree = _parse(r.sql, "postgres")
        from sqlglot import exp
        exists = list(tree.find_all(exp.Exists))
        assert len(exists) == 1

    def test_users_without_orders_postgres_uses_not_exists(self):
        r = NL2SQLGenerator().generate("find users without orders", "postgres")
        assert r.success
        assert "NOT EXISTS" in r.sql
        assert "users.id = orders.user_id" in r.sql

    def test_users_with_orders_hive_uses_exists(self):
        r = NL2SQLGenerator().generate("find users who have orders", "hive")
        assert r.success
        assert "WHERE EXISTS" in r.sql
        assert "users.id = orders.user_id" in r.sql

    def test_users_with_orders_mysql_uses_exists(self):
        r = NL2SQLGenerator().generate("find users who have orders", "mysql")
        assert r.success
        assert "WHERE EXISTS" in r.sql
        assert "users.id = orders.user_id" in r.sql


# =============================================================================
# G1: Fail-closed — unknown relationships
# =============================================================================

class TestG1FailClosedGolden:
    @pytest.mark.parametrize("key,expected", sorted(_GOLDEN["g1_fail_closed"].items()))
    def test_g1_case(self, key: str, expected: dict):
        parts = key.split("::")
        assert len(parts) == 3, f"Malformed G1 key: {key!r}"
        dialect, prompt = parts[1], parts[2]
        result = NL2SQLGenerator().generate(prompt, dialect=dialect)
        actual = _result_fields(result, prompt)
        assert actual == expected, (
            f"G1 golden mismatch for {key!r}:\n"
            f"  actual:    {json.dumps(actual, ensure_ascii=False)}\n"
            f"  expected:  {json.dumps(expected, ensure_ascii=False)}"
        )


class TestG1FailClosedStructure:
    """Unknown relationships must fail safely: success=False, sql=None,
    confidence=0.0, explanation names the pair, suggestions non-empty,
    and no 'ON None' in the SQL."""

    def test_unknown_relationship_fails(self):
        r = NL2SQLGenerator().generate("find users who have invoices", "postgres")
        assert r.success is False
        assert r.sql is None
        assert r.confidence == 0.0
        assert "Unable to safely infer" in r.explanation
        assert "users" in r.explanation
        assert "invoices" in r.explanation
        assert len(r.suggestions) > 0

    def test_unknown_relationship_hive_fails(self):
        r = NL2SQLGenerator().generate("find users who have invoices", "hive")
        assert r.success is False
        assert r.sql is None
        assert r.confidence == 0.0

    def test_no_on_none_in_successful_sql(self):
        """A successful join must never contain 'ON None'."""
        r = NL2SQLGenerator().generate("show users and products", "postgres")
        assert r.success
        assert r.sql is not None
        assert "ON None" not in r.sql

    def test_known_relationship_succeeds_with_physical_join(self):
        """users/products have a canonical FK; the join must succeed."""
        r = NL2SQLGenerator().generate("show users and products", "postgres")
        assert r.success
        assert "INNER JOIN products" in r.sql
        assert "users.id = products.user_id" in r.sql


# =============================================================================
# P0: Dialect-specific SQL forms
# =============================================================================

class TestP0DialectForms:

    def test_top_n_oracle_uses_fetch_first(self):
        r = NL2SQLGenerator().generate("find top 10 products by price", "oracle")
        assert r.success
        assert "FETCH FIRST 10 ROWS ONLY" in r.sql
        assert "LIMIT" not in r.sql

    def test_top_n_tsql_uses_top(self):
        r = NL2SQLGenerator().generate("find top 5 products by price", "tsql")
        assert r.success
        assert "SELECT TOP 5" in r.sql
        assert "LIMIT" not in r.sql

    def test_top_n_postgres_uses_limit(self):
        r = NL2SQLGenerator().generate("find top 10 products by price", "postgres")
        assert r.success
        assert "LIMIT 10" in r.sql
        assert "FETCH FIRST" not in r.sql
        assert "SELECT TOP" not in r.sql

    def test_top_n_mysql_uses_limit(self):
        r = NL2SQLGenerator().generate("find top 10 products by price", "mysql")
        assert r.success
        assert "LIMIT 10" in r.sql

    def test_all_12_dialects_matrix(self):
        """Every dialect in the matrix produces a parseable result for the
        plain select prompt."""
        for dialect in DIALECTS:
            r = NL2SQLGenerator().generate("查询所有用户", dialect=dialect)
            assert r.success, f"Plain select failed for dialect {dialect}"
            tree = sqlglot.parse_one(
                _sql_without_comments(r.sql), read=dialect
            )
            assert tree is not None


# =============================================================================
# P8: SQL parseability smoke (all successful golden cases must parse)
# =============================================================================

class TestParseability:
    @pytest.mark.parametrize("key,expected",
                             [(k, v) for k, v in sorted(_GOLDEN["matrix"].items())
                              if v["success"]])
    def test_successful_sql_parses(self, key: str, expected: dict):
        dialect, prompt = key.split("::", 1)
        r = NL2SQLGenerator().generate(prompt, dialect=dialect)
        tree = sqlglot.parse_one(_sql_without_comments(r.sql), read=dialect)
        assert tree is not None
