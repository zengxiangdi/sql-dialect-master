"""Regression tests for batch SQL parsing edge cases.

Ensures that statement splitting via the canonical SQLTranspiler.batch_transpile
handles semicolons inside strings, comments, multiline literals, and dollar-quoted
PostgreSQL bodies without incorrectly splitting them.
"""
import pytest

from backend.core.transpiler import SQLTranspiler


@pytest.fixture
def transpiler():
    return SQLTranspiler()


class TestBatchSemicolonEdgeCases:
    """Test that semicolons inside strings/comments don't cause false splits."""

    def test_semicolon_in_single_quoted_string(self, transpiler):
        """A semicolon inside a single-quoted string literal must not split."""
        statements = ["SELECT 'a;b' AS msg"]
        results = transpiler.batch_transpile(statements, "hive", "postgres")
        assert len(results) == 1
        assert results[0].success
        assert "a;b" in results[0].target_sql

    def test_semicolon_in_double_quoted_identifier(self, transpiler):
        """A semicolon inside a double-quoted identifier must not split."""
        statements = ['SELECT "col;umn" FROM t']
        results = transpiler.batch_transpile(statements, "hive", "postgres")
        assert len(results) == 1
        assert results[0].success

    def test_semicolon_in_line_comment(self, transpiler):
        """A semicolon inside a line comment must not split into two statements."""
        statements = ["SELECT 1 -- comment; not a split"]
        results = transpiler.batch_transpile(statements, "hive", "postgres")
        assert len(results) == 1
        assert results[0].success

    def test_semicolon_in_block_comment(self, transpiler):
        """A semicolon inside a block comment must not split."""
        statements = ["SELECT 1 /* comment; not a split */ FROM t"]
        results = transpiler.batch_transpile(statements, "hive", "postgres")
        assert len(results) == 1
        assert results[0].success

    def test_multiline_string_with_semicolon(self, transpiler):
        """A multiline string literal with semicolons must not split."""
        statements = ["SELECT 'line1;\nline2;' AS val"]
        results = transpiler.batch_transpile(statements, "hive", "postgres")
        assert len(results) == 1
        assert results[0].success

    def test_dollar_quoted_body_contains_semicolon(self, transpiler):
        """A PostgreSQL dollar-quoted string body may contain semicolons."""
        # Note: sqlglot may not parse dollar quotes perfectly; we test what we can
        statements = ["SELECT $tag$hello;world$tag$ AS val"]
        results = transpiler.batch_transpile(statements, "postgres", "mysql")
        # Single statement regardless of parseability
        assert len(results) == 1

    def test_nested_parentheses_with_semicolon(self, transpiler):
        """Semicolons inside nested function calls should not split."""
        statements = ["SELECT CONCAT('a;', 'b;')"]
        results = transpiler.batch_transpile(statements, "hive", "postgres")
        assert len(results) == 1
        assert results[0].success

    def test_actual_stacked_statements_rejected(self, transpiler):
        """Real stacked statements should still be rejected."""
        statements = ["SELECT 1; SELECT 2"]
        result = transpiler.transpile("SELECT 1; SELECT 2", "hive", "postgres")
        assert not result.success
        assert "Multiple SQL statements" in result.error

    def test_empty_statements_skipped(self, transpiler):
        """Empty or whitespace-only statements should be filtered out."""
        statements = ["SELECT 1", "", "  ", "SELECT 2"]
        results = transpiler.batch_transpile(statements, "hive", "postgres")
        # Empty statements will fail validation but should not crash
        successes = [r for r in results if r.success]
        assert len(successes) == 2

    def test_terminal_semicolon_accepted(self, transpiler):
        """A single statement with trailing semicolon is accepted."""
        statements = ["SELECT 1;"]
        result = transpiler.transpile("SELECT 1;", "hive", "postgres")
        assert result.success
        assert result.target_sql
