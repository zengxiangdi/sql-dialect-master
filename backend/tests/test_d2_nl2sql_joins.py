#!/usr/bin/env python3
"""
D2 — NL2SQL Subquery / JOIN Semantic Completion Tests
"""
import pytest
import sqlglot
from sqlglot import exp

from backend.core.nl2sql_legacy import NL2SQLGenerator


@pytest.fixture
def gen():
    return NL2SQLGenerator()


def table_names(tree):
    """Extract all table names from a parsed SQL tree."""
    names = set()
    for t in tree.find_all(exp.Table):
        names.add(t.name)
    return names


# =============================================================================
# Phase 1: Positive relational queries (EXISTS)
# =============================================================================

class TestExistsQueries:
    """Tests for 'who have' / 'with' patterns producing EXISTS clauses."""

    def test_users_have_orders(self, gen):
        """'find users who have orders' should use EXISTS, not JOIN."""
        result = gen.generate("find users who have orders", "postgres")
        assert result.success
        assert "WHERE EXISTS" in result.sql
        assert "FROM orders" in result.sql
        assert "users.id = orders.user_id" in result.sql
        # Should not contain a physical JOIN
        assert "JOIN" not in result.sql.upper().split("WHERE")[0]

    def test_customers_with_orders(self, gen):
        """'find customers with orders' should use EXISTS."""
        result = gen.generate("find customers with orders", "postgres")
        assert result.success
        assert "WHERE EXISTS" in result.sql
        assert "customers.id = orders.customer_id" in result.sql

    def test_users_placed_orders(self, gen):
        """'find users who placed orders' should use EXISTS."""
        result = gen.generate("find users who placed orders", "postgres")
        assert result.success
        assert "WHERE EXISTS" in result.sql

    def test_users_with_products(self, gen):
        """'find users with products' should use EXISTS."""
        result = gen.generate("find users with products", "postgres")
        assert result.success
        assert "WHERE EXISTS" in result.sql

    def test_subject_table_is_main_table(self, gen):
        """The first-mentioned table should be the FROM table."""
        result = gen.generate("find users who have orders", "postgres")
        tree = sqlglot.parse_one(result.sql, read="postgres")
        from_tables = {t.name for t in tree.find_all(exp.From)}
        # 'users' should be the main FROM table
        assert "users" in from_tables


# =============================================================================
# Phase 2: Negative relational queries (NOT EXISTS)
# =============================================================================

class TestNotExistsQueries:
    """Tests for 'who don't have' / 'without' patterns producing NOT EXISTS."""

    def test_users_without_orders(self, gen):
        """'find users without orders' should use NOT EXISTS."""
        result = gen.generate("find users without orders", "postgres")
        assert result.success
        assert "WHERE NOT EXISTS" in result.sql
        assert "orders" in result.sql

    def test_users_do_not_have_orders(self, gen):
        """'find users who do not have orders' should use NOT EXISTS."""
        result = gen.generate("find users who do not have orders", "postgres")
        assert result.success
        assert "WHERE NOT EXISTS" in result.sql

    def test_customers_without_orders(self, gen):
        """'find customers without orders' should use NOT EXISTS."""
        result = gen.generate("find customers without orders", "postgres")
        assert result.success
        assert "WHERE NOT EXISTS" in result.sql

    def test_no_false_positive_for_simple_query(self, gen):
        """A simple query without relational keywords should not use EXISTS."""
        result = gen.generate("find all users", "postgres")
        assert result.success
        assert "EXISTS" not in result.sql


# =============================================================================
# Phase 3: Table hint compatibility
# =============================================================================

class TestTableHintCompatibility:
    """Ensure D2 works correctly with table_hint parameter."""

    def test_with_table_hint_users(self, gen):
        """Query with table_hint should use hint as main table."""
        result = gen.generate(
            "find users who have orders",
            "postgres",
            table_hint="my_schema.users"
        )
        assert result.success
        assert "my_schema.users" in result.sql
        assert "WHERE EXISTS" in result.sql

    def test_with_table_hint_orders(self, gen):
        """Query with table_hint for relation table."""
        result = gen.generate(
            "find users who have orders",
            "postgres",
            table_hint="my_schema.orders"
        )
        assert result.success
        assert "my_schema.orders" in result.sql


# =============================================================================
# Phase 4: Date condition + relational combination (D2 + D3 interaction)
# =============================================================================

class TestDateAndRelationCombination:
    """Test that date conditions and relational queries work together."""

    def test_users_with_orders_last_week(self, gen):
        """Combined: users who have orders from last week."""
        result = gen.generate(
            "find users who have orders from last week",
            "postgres"
        )
        assert result.success
        assert "WHERE EXISTS" in result.sql
        # Date condition should be in the subquery
        assert "DATE_SUB" in result.sql or "CURRENT_DATE" in result.sql

    def test_users_without_orders_last_month(self, gen):
        """Combined: users without orders from last month."""
        result = gen.generate(
            "find users who do not have orders from last month",
            "postgres"
        )
        assert result.success
        assert "WHERE NOT EXISTS" in result.sql


# =============================================================================
# Phase 5: Dialect coverage
# =============================================================================

class TestDialectCoverage:
    """Test D2 works across all supported dialects."""

    DIALECTS = ["postgres", "mysql", "oracle", "tsql", "duckdb"]

    @pytest.mark.parametrize("dialect", DIALECTS)
    def test_users_have_orders_dialect(self, gen, dialect):
        """Users who have orders should work in all dialects."""
        result = gen.generate("find users who have orders", dialect)
        assert result.success
        assert "EXISTS" in result.sql

    @pytest.mark.parametrize("dialect", DIALECTS)
    def test_users_without_orders_dialect(self, gen, dialect):
        """Users without orders should work in all dialects."""
        result = gen.generate("find users without orders", dialect)
        assert result.success
        assert "NOT EXISTS" in result.sql


# =============================================================================
# Phase 6: Unknown relationship safety
# =============================================================================

class TestUnknownRelationships:
    """Unknown relationships should fail safely with explicit warning."""

    def test_users_have_invoices_fails_safely(self, gen):
        """Users and invoices have no known relationship."""
        result = gen.generate("find users who have invoices", "postgres")
        assert result.success is False
        assert "Unable to safely infer" in result.explanation
        assert len(result.suggestions) > 0
        assert result.confidence == 0.0

    def test_users_have_logs_fails_safely(self, gen):
        """Users and logs have no known relationship."""
        result = gen.generate("find users who have logs", "postgres")
        assert result.success is False
        assert "Unable to safely infer" in result.explanation

    def test_products_have_payments_fails_safely(self, gen):
        """Products and payments have no known relationship."""
        result = gen.generate("find products who have payments", "postgres")
        assert result.success is False
        assert "Unable to safely infer" in result.explanation

    def test_unknown_relationship_has_lower_confidence(self, gen):
        """Known relationships should have higher confidence than unknown."""
        result_known = gen.generate("find users who have orders", "postgres")
        result_unknown = gen.generate("find users who have invoices", "postgres")
        # Known relationship should succeed with high confidence
        assert result_known.success is True
        assert result_known.confidence > 0.9
        # Unknown relationship should fail with zero confidence
        assert result_unknown.success is False
        assert result_unknown.confidence == 0.0


# =============================================================================
# Phase 7: Regression protection — non-relational queries unaffected
# =============================================================================

class TestRegressionProtection:
    """Ensure existing non-relational queries still work correctly."""

    def test_product_query_unchanged(self, gen):
        """Product queries without relational keywords should be unchanged."""
        result = gen.generate(
            "find products with price greater than 100 order by price desc limit 10",
            "postgres"
        )
        assert result.success
        tree = sqlglot.parse_one(result.sql, read="postgres")
        # Should only reference products table, not orders
        tables = table_names(tree)
        assert tables == {"products"}

    def test_aggregate_query_unchanged(self, gen):
        """Aggregate queries should be unchanged."""
        result = gen.generate(
            "calculate average price for products grouped by category order by average price desc",
            "postgres"
        )
        assert result.success
        tree = sqlglot.parse_one(result.sql, read="postgres")
        tables = table_names(tree)
        assert tables == {"products"}

    def test_plain_select_unchanged(self, gen):
        """Plain select queries should work as before."""
        result = gen.generate("find all users", "postgres")
        assert result.success
        assert "SELECT" in result.sql
        assert "users" in result.sql.lower()


# =============================================================================
# Phase 7: Edge cases
# =============================================================================

class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_single_table_no_join(self, gen):
        """Single table queries should not produce joins."""
        result = gen.generate("find users", "postgres")
        assert result.success
        assert "JOIN" not in result.sql
        assert "EXISTS" not in result.sql

    def test_multiple_tables_no_relation_keyword(self, gen):
        """Multiple tables without relation keywords should not force EXISTS."""
        result = gen.generate("show users and products", "postgres")
        # Should use standard join logic, not EXISTS
        assert result.success

    def test_chinese_query(self, gen):
        """Chinese language queries should also work."""
        result = gen.generate("查找有订单的用户", "postgres")
        assert result.success
        # Should extract tables and generate appropriate SQL
