#!/usr/bin/env python3
"""Tests for DML-without-WHERE warning deduplication.

Each DELETE/UPDATE without WHERE must produce exactly one warning.
DELETE/UPDATE with WHERE must produce zero WHERE-related warnings.
Security blocking behavior must be unchanged.
"""
import pytest

from backend.core.transpiler import SQLTranspiler


@pytest.fixture
def transpiler():
    return SQLTranspiler()


class TestDeleteWithoutWhereWarnings:
    """DELETE without WHERE produces exactly one warning."""

    def test_delete_without_where_single_warning(self, transpiler):
        result = transpiler.transpile("DELETE FROM users", "mysql", "postgres")
        assert result.success
        where_warnings = [
            w for w in result.warnings
            if "DELETE" in w and "WHERE" in w
        ]
        assert len(where_warnings) == 1, (
            f"Expected exactly 1 DELETE-without-WHERE warning, got {len(where_warnings)}: {where_warnings}"
        )

    def test_delete_with_where_no_warning(self, transpiler):
        result = transpiler.transpile("DELETE FROM users WHERE id = 1", "mysql", "postgres")
        assert result.success
        where_warnings = [
            w for w in result.warnings
            if "DELETE" in w and "WHERE" in w
        ]
        assert len(where_warnings) == 0, (
            f"Expected 0 DELETE-without-WHERE warnings, got: {where_warnings}"
        )

    def test_delete_without_where_different_source_dialects(self, transpiler):
        """Same behavior regardless of source dialect."""
        for src in ["mysql", "postgres", "oracle", "tsql"]:
            result = transpiler.transpile("DELETE FROM users", src, "postgres")
            assert result.success
            where_warnings = [
                w for w in result.warnings
                if "DELETE" in w and "WHERE" in w
            ]
            assert len(where_warnings) == 1, (
                f"Source={src}: expected 1 warning, got {len(where_warnings)}: {where_warnings}"
            )


class TestUpdateWithoutWhereWarnings:
    """UPDATE without WHERE produces exactly one warning."""

    def test_update_without_where_single_warning(self, transpiler):
        result = transpiler.transpile("UPDATE users SET active = false", "mysql", "postgres")
        assert result.success
        where_warnings = [
            w for w in result.warnings
            if "UPDATE" in w and "WHERE" in w
        ]
        assert len(where_warnings) == 1, (
            f"Expected exactly 1 UPDATE-without-WHERE warning, got {len(where_warnings)}: {where_warnings}"
        )

    def test_update_with_where_no_warning(self, transpiler):
        result = transpiler.transpile("UPDATE users SET active = false WHERE id = 1", "mysql", "postgres")
        assert result.success
        where_warnings = [
            w for w in result.warnings
            if "UPDATE" in w and "WHERE" in w
        ]
        assert len(where_warnings) == 0, (
            f"Expected 0 UPDATE-without-WHERE warnings, got: {where_warnings}"
        )

    def test_update_without_where_different_source_dialects(self, transpiler):
        for src in ["mysql", "postgres", "oracle", "tsql"]:
            result = transpiler.transpile("UPDATE users SET x = 1", src, "postgres")
            assert result.success
            where_warnings = [
                w for w in result.warnings
                if "UPDATE" in w and "WHERE" in w
            ]
            assert len(where_warnings) == 1, (
                f"Source={src}: expected 1 warning, got {len(where_warnings)}: {where_warnings}"
            )


class TestWarningContent:
    """The remaining warning uses the AST-scanner-based message."""

    def test_delete_warning_message_content(self, transpiler):
        result = transpiler.transpile("DELETE FROM users", "mysql", "postgres")
        assert result.success
        where_warnings = [
            w for w in result.warnings
            if "DELETE" in w and "WHERE" in w
        ]
        assert len(where_warnings) == 1
        # Should use the AST-scanner message format
        assert "may affect all rows" in where_warnings[0], (
            f"Expected AST-scanner message format, got: {where_warnings[0]}"
        )

    def test_update_warning_message_content(self, transpiler):
        result = transpiler.transpile("UPDATE users SET x = 1", "mysql", "postgres")
        assert result.success
        where_warnings = [
            w for w in result.warnings
            if "UPDATE" in w and "WHERE" in w
        ]
        assert len(where_warnings) == 1
        assert "may affect all rows" in where_warnings[0], (
            f"Expected AST-scanner message format, got: {where_warnings[0]}"
        )


class TestSecurityUnchanged:
    """Security blocking behavior is not affected by the deduplication."""

    def test_drop_table_still_blocked(self, transpiler):
        result = transpiler.transpile("DROP TABLE users", "mysql", "postgres")
        assert not result.success
        assert result.error_code == "SECURITY_VIOLATION"

    def test_truncate_still_blocked(self, transpiler):
        result = transpiler.transpile("TRUNCATE TABLE users", "mysql", "postgres")
        assert not result.success
        assert result.error_code == "SECURITY_VIOLATION"

    def test_multi_statement_still_blocked(self, transpiler):
        result = transpiler.transpile("SELECT 1; DROP TABLE users", "mysql", "postgres")
        assert not result.success
        # Could be blocked as dangerous operation or multi-statement
        assert not result.success
