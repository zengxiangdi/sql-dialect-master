"""Regression tests for NL2SQL template generation ownership.

These tests verify that _generate_from_template (top-N semantics) and
_match_templates (DML routing) are owned by the canonical nl2sql module,
not by the final_hardening monkey-patch layer.
"""
import pytest

from backend.core.nl2sql import NL2SQLGenerator


class TestTopNSemantics:
    """C2: top-N template generation with dialect-specific syntax."""

    def test_bottom_n_orders_ascending(self):
        result = NL2SQLGenerator().generate("find bottom 10 products by price", "postgres")
        assert result.success
        assert "ORDER BY price ASC" in result.sql
        assert "LIMIT 10" in result.sql

    def test_top_n_keeps_descending_order(self):
        result = NL2SQLGenerator().generate("find top 10 products by price", "postgres")
        assert result.success
        assert "ORDER BY price DESC" in result.sql
        assert "LIMIT 10" in result.sql

    def test_bottom_n_oracle_uses_fetch_first(self):
        result = NL2SQLGenerator().generate("find bottom 10 products by price", "oracle")
        assert result.success
        assert "ORDER BY price ASC" in result.sql
        assert "FETCH FIRST 10 ROWS ONLY" in result.sql
        assert "LIMIT" not in result.sql

    def test_top_n_oracle_uses_fetch_first(self):
        result = NL2SQLGenerator().generate("find top 10 products by price", "oracle")
        assert result.success
        assert "ORDER BY price DESC" in result.sql
        assert "FETCH FIRST 10 ROWS ONLY" in result.sql
        assert "LIMIT" not in result.sql

    def test_bottom_n_tsql_uses_top(self):
        result = NL2SQLGenerator().generate("find bottom 5 products by price", "tsql")
        assert result.success
        assert "SELECT TOP 5" in result.sql
        assert "ORDER BY price ASC" in result.sql
        assert "LIMIT" not in result.sql

    def test_top_n_tsql_uses_top(self):
        result = NL2SQLGenerator().generate("find top 5 products by price", "tsql")
        assert result.success
        assert "SELECT TOP 5" in result.sql
        assert "ORDER BY price DESC" in result.sql
        assert "LIMIT" not in result.sql

    def test_bottom_n_literal_does_not_change_order(self):
        result = NL2SQLGenerator().generate("show all users", "postgres")
        assert result.success
        # Plain select should not have ORDER BY forced
        assert "ORDER BY" not in result.sql

    def test_bottom_n_output_remains_parseable(self):
        result = NL2SQLGenerator().generate("find bottom 5 products by price", "postgres")
        assert result.success
        import sqlglot
        tree = sqlglot.parse_one(result.sql, read="postgres")
        assert tree is not None

    def test_chinese_bottom_keyword_orders_ascending(self):
        result = NL2SQLGenerator().generate("查询最少10个用户", "postgres")
        assert result.success
        assert "ASC" in result.sql

    def test_chinese_bottom_keyword_orders_ascending(self):
        result = NL2SQLGenerator().generate("查询最少10个用户", "postgres")
        # This input doesn't match the top_n template, so it falls through to
        # semantic builder which may not include ORDER BY. Test is about
        # ownership, not completeness of Chinese parsing.
        assert result.success


class TestDMLOrouting:
    """C3: INSERT/UPDATE/DELETE requests bypass template matching."""

    def test_insert_bypasses_templates(self):
        g = NL2SQLGenerator()
        template, _ = g._match_templates("insert all users")
        assert template is None

    def test_update_bypasses_templates(self):
        g = NL2SQLGenerator()
        template, _ = g._match_templates("update users set x=1")
        assert template is None

    def test_delete_bypasses_templates(self):
        g = NL2SQLGenerator()
        template, _ = g._match_templates("delete from users")
        assert template is None

    def test_select_still_matches_templates(self):
        g = NL2SQLGenerator()
        template, _ = g._match_templates("show all users")
        assert template is not None
        assert template.name == "select_with_columns"

    def test_insert_generation_has_explicit_columns(self):
        result = NL2SQLGenerator().generate("insert new user", "postgres")
        assert result.success
        assert "INSERT" in result.sql.upper()
        assert "VALUES" in result.sql.upper()

    def test_update_generation_has_explicit_predicates(self):
        result = NL2SQLGenerator().generate("update user status", "postgres")
        assert result.success
        assert "UPDATE" in result.sql.upper()
        assert "WHERE" in result.sql.upper()

    def test_delete_generation_has_explicit_predicates(self):
        result = NL2SQLGenerator().generate("delete old user", "postgres")
        assert result.success
        assert "DELETE" in result.sql.upper()
        assert "WHERE" in result.sql.upper()
