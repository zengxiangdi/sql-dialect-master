"""Regression tests for _apply_dialect_adjustments ownership convergence.

These tests verify that nl2sql.py owns the canonical dialect-adjustment
behavior, independent of the final_hardening monkey-patch layer.
"""
import pytest

from backend.core.nl2sql import NL2SQLGenerator


class TestDialectAdjustmentsOwnImplementation:
    """Tests for dialect-specific date-function normalization."""

    def test_oracle_current_date_rewrite(self):
        generator = NL2SQLGenerator()
        sql = "SELECT * FROM t WHERE d = CURRENT_DATE"
        result = generator._apply_dialect_adjustments(sql, "oracle")
        assert "TRUNC(SYSDATE)" in result
        assert "CURRENT_DATE" not in result.split("--")[0]

    def test_oracle_date_sub_expansion(self):
        generator = NL2SQLGenerator()
        sql = "SELECT * FROM t WHERE d >= DATE_SUB(CURRENT_DATE, 7)"
        result = generator._apply_dialect_adjustments(sql, "oracle")
        assert "TRUNC(SYSDATE) - 7" in result

    def test_oracle_date_add_expansion(self):
        generator = NL2SQLGenerator()
        sql = "SELECT * FROM t WHERE d >= DATE_ADD(CURRENT_DATE, 7)"
        result = generator._apply_dialect_adjustments(sql, "oracle")
        assert "TRUNC(SYSDATE) + 7" in result

    def test_oracle_add_months_expansion(self):
        generator = NL2SQLGenerator()
        sql = "SELECT * FROM t WHERE d >= ADD_MONTHS(CURRENT_DATE, 3)"
        result = generator._apply_dialect_adjustments(sql, "oracle")
        assert "ADD_MONTHS(TRUNC(SYSDATE), 3)" in result

    def test_oracle_current_timestamp_rewrite(self):
        generator = NL2SQLGenerator()
        sql = "SELECT CURRENT_TIMESTAMP FROM t"
        result = generator._apply_dialect_adjustments(sql, "oracle")
        assert "SYSTIMESTAMP" in result

    def test_oracle_parentheses_balanced_after_rewrites(self):
        generator = NL2SQLGenerator()
        sql = "SELECT COALESCE(amount, 0) FROM orders WHERE d >= DATE_SUB(CURRENT_DATE, 7)"
        result = generator._apply_dialect_adjustments(sql, "oracle")
        assert result.count("(") == result.count(")")

    def test_tsql_current_date_rewrite(self):
        generator = NL2SQLGenerator()
        sql = "SELECT * FROM t WHERE d = CURRENT_DATE"
        result = generator._apply_dialect_adjustments(sql, "tsql")
        assert "CAST(GETDATE() AS DATE)" in result
        assert "CURRENT_DATE" not in result.split("--")[0]

    def test_tsql_date_sub_expansion(self):
        generator = NL2SQLGenerator()
        sql = "SELECT * FROM t WHERE d >= DATE_SUB(CURRENT_DATE, 7)"
        result = generator._apply_dialect_adjustments(sql, "tsql")
        assert "DATEADD(DAY, -7, CAST(GETDATE() AS DATE))" in result

    def test_tsql_date_add_expansion(self):
        generator = NL2SQLGenerator()
        sql = "SELECT * FROM t WHERE d >= DATE_ADD(CURRENT_DATE, 7)"
        result = generator._apply_dialect_adjustments(sql, "tsql")
        assert "DATEADD(DAY, 7, CAST(GETDATE() AS DATE))" in result

    def test_tsql_add_months_expansion(self):
        generator = NL2SQLGenerator()
        sql = "SELECT * FROM t WHERE d >= ADD_MONTHS(CURRENT_DATE, 3)"
        result = generator._apply_dialect_adjustments(sql, "tsql")
        assert "DATEADD(MONTH, 3, CAST(GETDATE() AS DATE))" in result

    def test_tsql_current_timestamp_rewrite(self):
        generator = NL2SQLGenerator()
        sql = "SELECT CURRENT_TIMESTAMP FROM t"
        result = generator._apply_dialect_adjustments(sql, "tsql")
        assert "SYSDATETIME()" in result

    def test_postgres_date_sub_expansion(self):
        generator = NL2SQLGenerator()
        sql = "SELECT * FROM t WHERE d >= DATE_SUB(CURRENT_DATE, 7)"
        result = generator._apply_dialect_adjustments(sql, "postgres")
        assert "CURRENT_DATE - INTERVAL '7 days'" in result

    def test_postgres_date_add_expansion(self):
        generator = NL2SQLGenerator()
        sql = "SELECT * FROM t WHERE d >= DATE_ADD(CURRENT_DATE, 7)"
        result = generator._apply_dialect_adjustments(sql, "postgres")
        assert "CURRENT_DATE + INTERVAL '7 days'" in result

    def test_postgres_add_months_expansion(self):
        generator = NL2SQLGenerator()
        sql = "SELECT * FROM t WHERE d >= ADD_MONTHS(CURRENT_DATE, 3)"
        result = generator._apply_dialect_adjustments(sql, "postgres")
        assert "CURRENT_DATE + INTERVAL '3 month'" in result

    def test_duckdb_date_sub_expansion(self):
        generator = NL2SQLGenerator()
        sql = "SELECT * FROM t WHERE d >= DATE_SUB(CURRENT_DATE, 7)"
        result = generator._apply_dialect_adjustments(sql, "duckdb")
        assert "CURRENT_DATE - INTERVAL '7 days'" in result

    def test_duckdb_date_add_expansion(self):
        generator = NL2SQLGenerator()
        sql = "SELECT * FROM t WHERE d >= DATE_ADD(CURRENT_DATE, 3)"
        result = generator._apply_dialect_adjustments(sql, "duckdb")
        assert "CURRENT_DATE + INTERVAL '3 days'" in result

    def test_mysql_date_sub_expansion(self):
        generator = NL2SQLGenerator()
        sql = "SELECT * FROM t WHERE d >= DATE_SUB(CURRENT_DATE, 7)"
        result = generator._apply_dialect_adjustments(sql, "mysql")
        assert "DATE_SUB(CURRENT_DATE, INTERVAL 7 DAY)" in result

    def test_hive_no_change(self):
        generator = NL2SQLGenerator()
        sql = "SELECT * FROM t WHERE d >= DATE_SUB(CURRENT_DATE, 7)"
        result = generator._apply_dialect_adjustments(sql, "hive")
        assert "DATE_SUB(CURRENT_DATE, 7)" in result

    def test_literal_does_not_trigger_rewrite(self):
        generator = NL2SQLGenerator()
        sql = "SELECT 'CURRENT_DATE' FROM t"
        result = generator._apply_dialect_adjustments(sql, "oracle")
        assert "'TRUNC(SYSDATE)'" not in result

    def test_comment_does_not_trigger_rewrite(self):
        generator = NL2SQLGenerator()
        sql = "-- CURRENT_DATE comment\nSELECT * FROM t"
        result = generator._apply_dialect_adjustments(sql, "oracle")
        assert "-- CURRENT_DATE comment" in result

    def test_quoted_identifier_does_not_trigger_rewrite(self):
        generator = NL2SQLGenerator()
        sql = 'SELECT "CURRENT_DATE" FROM t'
        result = generator._apply_dialect_adjustments(sql, "oracle")
        assert '"CURRENT_DATE"' in result

    def test_nested_function_preserved_in_oracle(self):
        generator = NL2SQLGenerator()
        sql = "SELECT COALESCE(DATE_SUB(CURRENT_DATE, 7), 'none') FROM t"
        result = generator._apply_dialect_adjustments(sql, "oracle")
        assert "TRUNC(SYSDATE) - 7" in result
        assert "COALESCE" in result
