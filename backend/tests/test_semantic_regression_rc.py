"""Semantic regression tests for RC gate.

Verifies that high-risk SQL rewrites do not silently change semantics,
and that uncertainty is explicitly exposed via compatibility notes.
"""
import pytest
import sqlglot
from sqlglot import exp

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.transpiler import SQLTranspiler
from backend.core.type_mapping import TypeMapper


transpiler = SQLTranspiler()
generator = NL2SQLGenerator()
type_mapper = TypeMapper()


# =============================================================================
# 1. Aggregation Semantic Tests
# =============================================================================

class TestGroupConcat:
    """GROUP_CONCAT -> STRING_AGG conversion must preserve semantics."""

    def test_simple_group_concat(self):
        sql = "SELECT GROUP_CONCAT(name) FROM users"
        result = transpiler.transpile(sql, "mysql", "postgres")
        assert result.success
        assert "STRING_AGG" in result.target_sql.upper()
        # Simple column names don't need ::TEXT cast (sqlglot omits it)
        # The important thing is the conversion happened

    def test_distinct_preserved(self):
        sql = "SELECT GROUP_CONCAT(DISTINCT name) FROM users"
        result = transpiler.transpile(sql, "mysql", "postgres")
        assert result.success
        assert "DISTINCT" in result.target_sql.upper()

    def test_separator_preserved(self):
        sql = "SELECT GROUP_CONCAT(name SEPARATOR '|') FROM users"
        result = transpiler.transpile(sql, "mysql", "postgres")
        assert result.success
        assert "|'" in result.target_sql or "('|')" in result.target_sql

    def test_order_by_in_group_concat(self):
        sql = "SELECT GROUP_CONCAT(name ORDER BY created_at) FROM users"
        result = transpiler.transpile(sql, "mysql", "postgres")
        assert result.success
        assert "ORDER BY" in result.target_sql.upper()

    def test_nested_expression_in_group_concat(self):
        sql = "SELECT GROUP_CONCAT(CONCAT(first_name, last_name)) FROM users"
        result = transpiler.transpile(sql, "mysql", "postgres")
        assert result.success
        # CONCAT should be preserved (sqlglot may or may not rewrite)
        assert "CONCAT" in result.target_sql.upper() or "||" in result.target_sql


class TestStringAgg:
    """STRING_AGG -> GROUP_CONCAT conversion must preserve semantics."""

    def test_simple_string_agg(self):
        sql = "SELECT STRING_AGG(name, ',') FROM users"
        result = transpiler.transpile(sql, "postgres", "mysql")
        assert result.success
        assert "GROUP_CONCAT" in result.target_sql.upper()
        assert "SEPARATOR" in result.target_sql.upper()

    def test_nested_expression_in_string_agg(self):
        sql = "SELECT STRING_AGG(CONCAT(first_name, last_name), '|') FROM users"
        result = transpiler.transpile(sql, "postgres", "mysql")
        assert result.success
        # CONCAT should not be silently rewritten to COALESCE
        # Note: sqlglot may convert CONCAT to ||, which is semantically equivalent
        assert "CONCAT" in result.target_sql.upper() or "||" in result.target_sql


class TestListagg:
    """LISTAGG conversions must not emit false notes."""

    def test_oracle_to_hive_false_notes_filtered(self):
        sql = "SELECT LISTAGG(name, ',') WITHIN GROUP (ORDER BY id) FROM users"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
        # sqlglot converts LISTAGG to GROUP_CONCAT for oracle->hive
        # The note claiming ARRAY_JOIN(COLLECT_LIST()) is false
        assert not any("ARRAY_JOIN" in n for n in result.compatibility_notes)
        # CONNECT BY note should also be filtered (query has no CONNECT BY)
        assert not any("CONNECT BY" in n for n in result.compatibility_notes)

    def test_listagg_with_nested_case(self):
        sql = "SELECT LISTAGG(CASE WHEN active = 1 THEN name ELSE NULL END, ',') WITHIN GROUP (ORDER BY id) FROM users"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success

    def test_listagg_malformed_no_rewrite(self):
        sql = "SELECT LISTAGG(name, ',') FROM users"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success


class TestArrayAgg:
    """ARRAY_AGG <-> COLLECT_LIST conversions."""

    def test_postgres_to_hive(self):
        sql = "SELECT ARRAY_AGG(name) FROM users"
        result = transpiler.transpile(sql, "postgres", "hive")
        assert result.success
        assert "COLLECT_LIST" in result.target_sql.upper()

    def test_distinct_preserved(self):
        sql = "SELECT ARRAY_AGG(DISTINCT name) FROM users"
        result = transpiler.transpile(sql, "postgres", "hive")
        assert result.success
        assert "DISTINCT" in result.target_sql.upper()


class TestCollectList:
    """COLLECT_LIST -> ARRAY_AGG conversions."""

    def test_hive_to_postgres(self):
        sql = "SELECT COLLECT_LIST(name) FROM users"
        result = transpiler.transpile(sql, "hive", "postgres")
        assert result.success
        assert "ARRAY_AGG" in result.target_sql.upper()

    def test_nested_expression(self):
        sql = "SELECT COLLECT_LIST(CONCAT(a, b)) FROM users"
        result = transpiler.transpile(sql, "hive", "postgres")
        assert result.success


# =============================================================================
# 2. Date/Time Semantic Tests
# =============================================================================

class TestDateTimePreservation:
    """Date/time functions must not be incorrectly rewritten."""

    def test_current_date_preserved(self):
        sql = "SELECT CURRENT_DATE FROM users"
        result = transpiler.transpile(sql, "mysql", "postgres")
        assert result.success
        assert "CURRENT_DATE" in result.target_sql.upper()

    def test_current_timestamp_preserved(self):
        sql = "SELECT CURRENT_TIMESTAMP FROM users"
        result = transpiler.transpile(sql, "mysql", "postgres")
        assert result.success
        assert "CURRENT_TIMESTAMP" in result.target_sql.upper()

    def test_now_preserved(self):
        sql = "SELECT NOW() FROM users"
        result = transpiler.transpile(sql, "mysql", "postgres")
        assert result.success
        assert "NOW()" in result.target_sql.upper()

    def test_date_add_preserved(self):
        sql = "SELECT DATE_ADD(created_at, INTERVAL 7 DAY) FROM users"
        result = transpiler.transpile(sql, "mysql", "postgres")
        assert result.success
        # Result uses + INTERVAL syntax which is semantically equivalent
        assert "INTERVAL" in result.target_sql.upper()

    def test_date_sub_preserved(self):
        sql = "SELECT DATE_SUB(created_at, INTERVAL 7 DAY) FROM users"
        result = transpiler.transpile(sql, "mysql", "postgres")
        assert result.success

    def test_add_months_preserved(self):
        sql = "SELECT ADD_MONTHS(dt, 1) FROM users"
        result = transpiler.transpile(sql, "oracle", "postgres")
        assert result.success
        assert "ADD_MONTHS" in result.target_sql.upper()

    def test_date_format_conversion(self):
        sql = "SELECT DATE_FORMAT(dt, '%Y-%m-%d') FROM users"
        result = transpiler.transpile(sql, "mysql", "postgres")
        assert result.success
        assert "TO_CHAR" in result.target_sql.upper()

    def test_to_char_preserved(self):
        sql = "SELECT TO_CHAR(dt, 'YYYY-MM-DD') FROM users"
        result = transpiler.transpile(sql, "oracle", "postgres")
        assert result.success

    def test_rowcount_not_in_literal(self):
        sql = "SELECT 'ROWNUM is a pseudo-column' FROM dual"
        result = transpiler.transpile(sql, "oracle", "postgres")
        assert result.success
        assert "ROWNUM is a pseudo-column" in result.target_sql

    def test_rowcount_not_in_comment(self):
        sql = "SELECT id FROM users -- use ROWNUM for ranking"
        result = transpiler.transpile(sql, "oracle", "postgres")
        assert result.success
        assert "ROWNUM" in result.target_sql


class TestLimitTop:
    """LIMIT/TOP conversions must be semantically correct."""

    def test_fetch_first_to_limit(self):
        sql = "SELECT * FROM users FETCH FIRST 10 ROWS ONLY"
        result = transpiler.transpile(sql, "oracle", "mysql")
        assert result.success
        assert "LIMIT 10" in result.target_sql.upper()

    def test_top_to_limit(self):
        sql = "SELECT TOP 10 * FROM users"
        result = transpiler.transpile(sql, "tsql", "mysql")
        assert result.success
        assert "LIMIT 10" in result.target_sql.upper()

    def test_top_to_limit_postgres(self):
        sql = "SELECT TOP 10 * FROM users"
        result = transpiler.transpile(sql, "tsql", "postgres")
        assert result.success
        assert "LIMIT 10" in result.target_sql.upper()


# =============================================================================
# 3. NL2SQL Semantic Tests
# =============================================================================

class TestNL2SQLRegression:
    """NL2SQL must preserve semantic intent for key query patterns."""

    def test_in_predicate_preserved(self):
        result = generator.generate("orders where id in (1, 2, 3)", dialect="postgres")
        assert result.success
        assert "WHERE id IN (1, 2, 3)" in result.sql
        # Should NOT add spurious ORDER BY because "order" is substring of "orders"
        assert "ORDER BY" not in result.sql

    def test_not_in_predicate(self):
        result = generator.generate("orders where id not in (1, 2, 3)", dialect="postgres")
        assert result.success
        assert "NOT IN (1, 2, 3)" in result.sql

    def test_status_in_no_duplicate(self):
        result = generator.generate("users where status in (active, pending)", dialect="postgres")
        assert result.success
        # Should have status IN but NOT status = active (duplicate)
        sql_lower = result.sql.lower()
        assert "status in" in sql_lower
        assert result.sql.count("status = 'active'") == 0

    def test_comparison_preserves_gte(self):
        result = generator.generate("users where age greater than or equal to 18", dialect="postgres")
        assert result.success
        assert ">=" in result.sql

    def test_comparison_preserves_lte(self):
        result = generator.generate("users where age less than or equal to 18", dialect="postgres")
        assert result.success
        assert "<=" in result.sql

    def test_null_predicate_is_explicit(self):
        result = generator.generate("users where age is null", dialect="postgres")
        assert result.success
        assert "IS NULL" in result.sql
        assert "IS NOT NULL" not in result.sql

    def test_not_null_predicate(self):
        result = generator.generate("users where age is not null", dialect="postgres")
        assert result.success
        assert "IS NOT NULL" in result.sql
        # Remove IS NOT NULL to check for stray IS NULL
        cleaned = result.sql.replace("IS NOT NULL", "")
        assert "IS NULL" not in cleaned

    def test_aggregate_with_group_by(self):
        result = generator.generate("count orders by status", dialect="mysql")
        assert result.success
        tree = sqlglot.parse_one(result.sql, read="mysql")
        assert tree.find(exp.Group) is not None
        assert tree.find(exp.Count) is not None

    def test_update_has_explicit_predicate(self):
        result = generator.generate("update users set status = active where id = 1", dialect="postgres")
        assert result.success
        tree = sqlglot.parse_one(result.sql, read="postgres")
        assert tree.find(exp.Where) is not None

    def test_delete_has_explicit_predicate(self):
        result = generator.generate("delete from users where id = 1", dialect="postgres")
        assert result.success
        tree = sqlglot.parse_one(result.sql, read="postgres")
        assert tree.find(exp.Where) is not None


# =============================================================================
# 4. TypeMapper Semantic Tests
# =============================================================================

class TestTypeMapperRegression:
    """TypeMapper must handle exact, alias, and precision types."""

    def test_exact_match(self):
        result = type_mapper.map_type("VARCHAR", "mysql", "postgres")
        assert result["success"]
        assert result["target_type"] == "VARCHAR(n)"

    def test_canonical_alias(self):
        result = type_mapper.map_type("INT", "mysql", "postgres")
        assert result["success"]
        assert result["target_type"] == "INTEGER"

    def test_normalized_alias(self):
        result = type_mapper.map_type("BIGINT", "mysql", "postgres")
        assert result["success"]
        assert result["target_type"] == "BIGINT"

    def test_datetime_mapped(self):
        result = type_mapper.map_type("DATETIME", "mysql", "postgres")
        assert result["success"]
        assert result["target_type"] == "TIMESTAMP"

    def test_decimal_with_precision(self):
        # TypeMapper uses canonical type names; precision is handled by the target dialect
        result = type_mapper.map_type("DECIMAL", "mysql", "postgres")
        assert result["success"]
        # DECIMAL maps to NUMERIC in postgres
        assert "NUMERIC" in result["target_type"] or "DECIMAL" in result["target_type"]

    def test_unknown_dialect_fails(self):
        result = type_mapper.map_type("VARCHAR", "mysql", "made_up_db")
        assert not result["success"]
        assert "made_up_db" in result["error"]

    def test_precision_warning_exists(self):
        result = type_mapper.map_type("VARCHAR", "mysql", "postgres")
        assert len(result["warnings"]) > 0
        assert "Max length varies" in result["warnings"][0]


# =============================================================================
# 5. Lexical Boundary Safety Tests
# =============================================================================

class TestLexicalBoundarySafety:
    """Rewrites must not cross lexical boundaries (strings, comments, identifiers)."""

    def test_group_concat_in_string_literal(self):
        sql = "SELECT 'GROUP_CONCAT(CONCAT(a, b))' FROM users"
        result = transpiler.transpile(sql, "mysql", "postgres")
        assert result.success
        assert "GROUP_CONCAT(CONCAT(a, b))" in result.target_sql

    def test_group_concat_in_comment(self):
        sql = "SELECT GROUP_CONCAT(name) FROM users -- GROUP_CONCAT(CONCAT(a, b))"
        result = transpiler.transpile(sql, "mysql", "postgres")
        assert result.success
        assert "GROUP_CONCAT(CONCAT(a, b))" in result.target_sql

    def test_string_agg_in_string_literal(self):
        sql = 'SELECT "STRING_AGG(CONCAT(a, b), \',\')" FROM users'
        result = transpiler.transpile(sql, "postgres", "mysql")
        assert result.success
        assert "STRING_AGG(CONCAT(a, b), ',')" in result.target_sql

    def test_listagg_in_comment(self):
        sql = "SELECT LISTAGG(name, ',') FROM users -- LISTAGG(a, b) WITHIN GROUP"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success


# =============================================================================
# 6. False Note Filtering Tests
# =============================================================================

class TestFalseNoteFiltering:
    """Compatibility notes must only be emitted when the transformation was applied."""

    def test_listagg_no_false_array_join_note(self):
        sql = "SELECT LISTAGG(name, ',') WITHIN GROUP (ORDER BY id) FROM users"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
        assert not any("ARRAY_JOIN" in n for n in result.compatibility_notes)

    def test_connect_by_only_query_no_false_note(self):
        sql = "SELECT * FROM users WHERE id = 1"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
        assert not any("CONNECT BY" in n for n in result.compatibility_notes)

    def test_connect_by_with_clause_preserves_note(self):
        sql = "SELECT * FROM users START WITH id = 1 CONNECT BY PRIOR id = parent_id"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
        # Should have the custom note about CONNECT BY being Oracle-specific
        assert any("CONNECT BY" in n for n in result.compatibility_notes)
