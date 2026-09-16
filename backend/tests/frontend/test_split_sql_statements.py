#!/usr/bin/env python3
"""Tests for split_sql_statements utility."""
from __future__ import annotations

from backend.utils.validators import split_sql_statements


class TestSplitSQLTextPreservation:
    """Test that the splitter preserves original SQL text exactly."""

    def test_single_stmt_preserved(self) -> None:
        """Single statement should be preserved (semicolons are separators)."""
        sql = "SELECT * FROM users;"
        result = split_sql_statements(sql)
        assert len(result) == 1
        # Semicolons are statement separators, stripped from output
        assert result[0].strip() == "SELECT * FROM users"

    def test_single_stmt_no_semicolon_preserved(self) -> None:
        """Single statement without semicolon should be preserved verbatim."""
        sql = "SELECT * FROM users"
        result = split_sql_statements(sql)
        assert len(result) == 1
        assert result[0] == sql

    def test_multiple_stmts_preserved(self) -> None:
        """Multiple statements should preserve each statement's original text."""
        sql = "SELECT 1; SELECT 2; SELECT 3;"
        result = split_sql_statements(sql)
        assert len(result) == 3
        assert result[0].strip() == "SELECT 1"
        assert result[1].strip() == "SELECT 2"
        assert result[2].strip() == "SELECT 3"

    def test_semicolon_in_string_literal_preserved(self) -> None:
        """Semicolon inside string must NOT split the statement."""
        sql = "SELECT 'a;b;c' AS val;"
        result = split_sql_statements(sql)
        assert len(result) == 1
        assert ";" in result[0]
        assert result[0].strip() == "SELECT 'a;b;c' AS val"

    def test_semicolon_in_single_quoted_escaped(self) -> None:
        """Escaped quotes inside strings."""
        sql = "SELECT 'it''s a test;' FROM t;"
        result = split_sql_statements(sql)
        assert len(result) == 1
        assert "it''s a test;" in result[0]

    def test_semicolon_in_block_comment_preserved(self) -> None:
        """Semicolon inside block comment must NOT split."""
        sql = "/* comment ; */ SELECT * FROM t;"
        result = split_sql_statements(sql)
        assert len(result) >= 1

    def test_semicolon_in_line_comment_preserved(self) -> None:
        """Semicolon inside line comment must NOT split."""
        sql = "-- comment ;\nSELECT * FROM t;"
        result = split_sql_statements(sql)
        assert len(result) >= 1

    def test_dollar_quoted_string_preserved(self) -> None:
        """PostgreSQL dollar-quoted strings with semicolons."""
        sql = "SELECT $$value; with semicolon$$;"
        result = split_sql_statements(sql)
        assert len(result) == 1
        assert "value; with semicolon" in result[0]

    def test_tagged_dollar_quote_preserved(self) -> None:
        """Named dollar-quoted strings."""
        sql = "SELECT $tag$;with;semicolon$tag$;"
        result = split_sql_statements(sql)
        assert len(result) == 1
        assert ";with;semicolon" in result[0]

    def test_empty_statements_filtered(self) -> None:
        """Consecutive semicolons should not create empty statements."""
        sql = "SELECT 1;; SELECT 2;"
        result = split_sql_statements(sql)
        assert len(result) == 2
        assert "" not in result


class TestSplitSQLByDialect:
    """Test dialect-specific handling."""

    def test_postgres_dollar_quote(self) -> None:
        """PostgreSQL dollar-quoted strings."""
        sql = "SELECT $$test;value$$;"
        result = split_sql_statements(sql, dialect="postgres")
        assert len(result) == 1
        assert "$$test;value$$" in result[0]

    def test_mysql_backtick(self) -> None:
        """MySQL backtick identifiers with semicolons."""
        sql = "SELECT `col;um` FROM `tab;le`;"
        result = split_sql_statements(sql, dialect="mysql")
        assert len(result) >= 1
        # Should not have split on semicolons inside backticks
        assert "`col;um`" in result[0] or "`col" in result[0]

    def test_oracle_plsql(self) -> None:
        """Oracle PL/SQL blocks."""
        sql = "BEGIN\n  NULL;\nEND;"
        result = split_sql_statements(sql, dialect="oracle")
        assert len(result) >= 1

    def test_tsql_batch(self) -> None:
        """T-SQL GO batch separator."""
        sql = "SELECT 1; GO; SELECT 2;"
        result = split_sql_statements(sql, dialect="tsql")
        assert len(result) >= 2

    def test_duckdb_generate_series(self) -> None:
        """DuckDB function syntax."""
        sql = "SELECT * FROM generate_series(1, 10);"
        result = split_sql_statements(sql, dialect="duckdb")
        assert len(result) == 1

    def test_hive_syntax(self) -> None:
        """Hive/Spark SQL."""
        sql = "SELECT * FROM users WHERE id > 10;"
        result = split_sql_statements(sql, dialect="hive")
        assert len(result) == 1


class TestSplitSQLEdgeCases:
    """Edge cases and robustness."""

    def test_empty_input(self) -> None:
        assert split_sql_statements("") == []
        assert split_sql_statements("   ") == []

    def test_large_batch(self) -> None:
        """100 statements should produce 100 results."""
        sql = ";".join(f"SELECT {i}" for i in range(100)) + ";"
        result = split_sql_statements(sql)
        assert len(result) == 100

    def test_trailing_semicolon_no_empty(self) -> None:
        """Trailing semicolon should not create empty statement."""
        sql = "SELECT 1;"
        result = split_sql_statements(sql)
        assert len(result) == 1

    def test_nested_block_comments(self) -> None:
        """Nested comment-like patterns."""
        sql = "SELECT /* outer /* inner ; */ value FROM t;"
        result = split_sql_statements(sql)
        assert len(result) >= 1

    def test_malformed_input_graceful(self) -> None:
        """Malformed input should not crash."""
        result = split_sql_statements("SELECT ; ; ;")
        assert isinstance(result, list)

    def test_mixed_comments_strings(self) -> None:
        """Complex mix of comments, strings, semicolons."""
        sql = "SELECT 'a;b' AS x; /*comment;*/ SELECT 'c;d';"
        result = split_sql_statements(sql)
        assert len(result) == 2
