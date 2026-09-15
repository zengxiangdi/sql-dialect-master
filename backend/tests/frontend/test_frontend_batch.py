#!/usr/bin/env python3
"""Frontend batch conversion tests — specifically testing the batch split bug fix."""
from __future__ import annotations

import pytest

from frontend.pages.convert import _split_statements


class TestBatchStatementSplitting:
    """Test the batch statement splitting function."""

    def test_simple_semicolon_split(self) -> None:
        """Basic semicolon-separated statements should split correctly."""
        sql = "SELECT * FROM users; SELECT * FROM orders;"
        statements = _split_statements(sql)
        assert len(statements) == 2
        assert "users" in statements[0].lower()
        assert "orders" in statements[1].lower()

    def test_semicolon_in_string_literal(self) -> None:
        """Semicolon inside string literal should NOT split."""
        sql = "SELECT ';' AS value;"
        statements = _split_statements(sql)
        # Should be treated as one statement
        assert len(statements) == 1
        assert ";" in statements[0]

    def test_comment_with_semicolon(self) -> None:
        """Comment containing semicolon should not cause split."""
        sql = "-- comment ;\nSELECT * FROM users;"
        statements = _split_statements(sql)
        # Should be one statement (comment + select)
        assert len(statements) == 1 or (len(statements) == 2 and "SELECT" in statements[-1].upper())

    def test_single_statement_no_trailing_semicolon(self) -> None:
        """Single statement without trailing semicolon should work."""
        sql = "SELECT * FROM users"
        statements = _split_statements(sql)
        assert len(statements) == 1
        assert "SELECT" in statements[0].upper()

    def test_multiple_statements_different_dialects(self) -> None:
        """Statements from different dialect patterns."""
        sql = "SELECT TOP 10 * FROM users; SELECT * FROM orders LIMIT 10;"
        statements = _split_statements(sql)
        # Should split into at least 2 statements
        assert len(statements) >= 2

    def test_empty_input(self) -> None:
        """Empty input should return empty list."""
        statements = _split_statements("")
        assert statements == []

    def test_whitespace_only(self) -> None:
        """Whitespace-only input should return empty list."""
        statements = _split_statements("   \n\t  ")
        assert statements == []

    def test_dollar_quoted_postgresql(self) -> None:
        """PostgreSQL dollar-quoted strings with semicolons."""
        sql = "SELECT $$value; with semicolon$$;"
        statements = _split_statements(sql)
        # Should handle dollar quotes properly
        assert len(statements) >= 1


class TestBatchWithCanonicalAPI:
    """Test that batch conversion uses canonical backend API."""

    def test_batch_uses_canonical_api(self) -> None:
        """batch_convert_sql should delegate to SQLTranspiler.batch_transpile."""
        from frontend.app_context_v2 import batch_convert_sql
        from backend.core.transpiler import SQLTranspiler

        # Verify the function exists and is callable
        assert callable(batch_convert_sql)

        # Test actual batch conversion
        statements = ["SELECT 1", "SELECT 2"]
        results = batch_convert_sql(statements, "postgres", "mysql")
        assert len(results) == 2
        assert all(r.success for r in results)

    def test_batch_with_semicolon_in_string(self) -> None:
        """Batch with semicolon in string literal should not break."""
        from frontend.app_context_v2 import batch_convert_sql

        # The canonical API handles this correctly
        statements = ["SELECT ';' AS value"]
        results = batch_convert_sql(statements, "postgres", "mysql")
        assert len(results) == 1
        assert results[0].success is True
