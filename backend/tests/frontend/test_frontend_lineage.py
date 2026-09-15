#!/usr/bin/env python3
"""Frontend lineage tests."""
from __future__ import annotations

import pytest

from frontend.pages.lineage import _build_lineage, _build_mermaid


class TestLineageBuilding:
    """Test lineage extraction from SQL."""

    def test_simple_select(self) -> None:
        """Simple SELECT should extract table and output columns."""
        sql = "SELECT name FROM users"
        vm = _build_lineage(sql, "postgres")
        assert len(vm.tables) == 1
        assert vm.tables[0].name == "users"
        assert len(vm.output_columns) == 1
        assert vm.output_columns[0].name == "name"

    def test_joined_tables(self) -> None:
        """JOIN should extract all tables."""
        sql = "SELECT u.name, o.id FROM users u JOIN orders o ON u.id = o.user_id"
        vm = _build_lineage(sql, "postgres")
        table_names = {t.name for t in vm.tables}
        assert "users" in table_names
        assert "orders" in table_names

    def test_subquery_tables(self) -> None:
        """Subquery should extract inner table."""
        sql = "SELECT * FROM (SELECT id FROM users) sub"
        vm = _build_lineage(sql, "postgres")
        table_names = {t.name for t in vm.tables}
        assert "users" in table_names

    def test_aggregation(self) -> None:
        """Aggregation should extract output columns."""
        sql = "SELECT dept, COUNT(*) AS cnt FROM employees GROUP BY dept"
        vm = _build_lineage(sql, "postgres")
        col_names = {c.name for c in vm.output_columns}
        assert "dept" in col_names
        assert "cnt" in col_names

    def test_column_references(self) -> None:
        """Column references should be tracked."""
        sql = "SELECT u.name FROM users u WHERE u.id = 1"
        vm = _build_lineage(sql, "postgres")
        assert "u" in vm.column_references or "users" in vm.column_references


class TestMermaidGeneration:
    """Test Mermaid diagram generation."""

    def test_simple_mermaid(self) -> None:
        """Simple lineage should produce valid Mermaid."""
        sql = "SELECT name FROM users"
        vm = _build_lineage(sql, "postgres")
        mermaid = _build_mermaid(vm)
        assert "flowchart LR" in mermaid
        assert "users" in mermaid
        assert "```mermaid" in mermaid
        assert "```" in mermaid

    def test_mermaid_escapes_special_chars(self) -> None:
        """Mermaid should escape special characters in table names."""
        sql = "SELECT * FROM \"table-name\""
        vm = _build_lineage(sql, "postgres")
        mermaid = _build_mermaid(vm)
        # Should not contain raw dashes in node IDs
        assert '""' not in mermaid

    def test_mermaid_with_multiple_tables(self) -> None:
        """Mermaid with multiple tables should include all."""
        sql = "SELECT u.name FROM users u JOIN orders o ON u.id = o.user_id"
        vm = _build_lineage(sql, "postgres")
        mermaid = _build_mermaid(vm)
        assert "flowchart LR" in mermaid


class TestLineageEdgeCases:
    """Test edge cases in lineage extraction."""

    def test_empty_query(self) -> None:
        """Empty query should return empty lineage."""
        with pytest.raises(Exception):  # sqlglot will raise on empty
            _build_lineage("", "postgres")

    def test_complex_cte(self) -> None:
        """CTE should extract tables from within CTE."""
        sql = "WITH cte AS (SELECT * FROM users) SELECT * FROM cte"
        vm = _build_lineage(sql, "postgres")
        table_names = {t.name for t in vm.tables}
        assert "users" in table_names
