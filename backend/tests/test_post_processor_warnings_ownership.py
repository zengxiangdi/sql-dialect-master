"""Regression tests for Phase D / D3: PostProcessor warnings ownership.

Verifies that PostProcessor._check_warnings is the single effective implementation,
never monkey-patched, and correctly ignores literals/comments/identifiers.
"""
import pytest

from backend.core.compatibility import install_compatibility_patches
from backend.core.post_processor import PostProcessor

install_compatibility_patches()


class TestPostProcessorWarningsOwnership:
    """Tests proving PostProcessor._check_warnings has unique ownership."""

    def test_owner_is_post_processor_method(self):
        """Verify effective runtime implementation."""
        assert PostProcessor._check_warnings.__qualname__ == "PostProcessor._check_warnings"
        assert PostProcessor._check_warnings.__module__ == "backend.core.post_processor"

    def test_literal_drop_table_does_not_trigger_warning(self):
        """Literal content must never trigger warnings."""
        p = PostProcessor()
        sql = "SELECT 'DROP TABLE users' AS msg FROM t"
        warnings = p._check_warnings(sql, "mysql", "postgres")
        assert warnings == []

    def test_comment_drop_table_does_not_trigger_warning(self):
        """Comment content must never trigger warnings."""
        p = PostProcessor()
        sql = "SELECT 1 -- DROP TABLE users\n"
        warnings = p._check_warnings(sql, "mysql", "postgres")
        assert warnings == []

    def test_quoted_identifier_drop_does_not_trigger_warning(self):
        """Quoted identifier substring must not trigger warnings."""
        p = PostProcessor()
        sql = 'SELECT "DROP TABLE" FROM t'
        warnings = p._check_warnings(sql, "mysql", "postgres")
        assert warnings == []

    def test_hive_insert_overwrite_warning(self):
        """Hive INSERT OVERWRITE to non-Hive dialects triggers warning."""
        p = PostProcessor()
        sql = "INSERT OVERWRITE TABLE t SELECT 1"
        warnings = p._check_warnings(sql, "hive", "postgres")
        assert len(warnings) == 1
        assert "INSERT OVERWRITE" in warnings[0]

    def test_oracle_connect_by_warning(self):
        """Oracle CONNECT BY to non-Oracle dialects triggers warning."""
        p = PostProcessor()
        sql = "SELECT * FROM t START WITH id = 1 CONNECT BY PRIOR id = parent_id"
        warnings = p._check_warnings(sql, "oracle", "postgres")
        assert len(warnings) == 1
        assert "CONNECT BY" in warnings[0]

    def test_hive_distribute_by_warning(self):
        """Hive DISTRIBUTE BY to non-Hive dialects triggers warning."""
        p = PostProcessor()
        sql = "SELECT * FROM t DISTRIBUTE BY col"
        warnings = p._check_warnings(sql, "hive", "mysql")
        assert len(warnings) == 1
        assert "DISTRIBUTE BY" in warnings[0]

    def test_procedural_code_warning(self):
        """Procedural code patterns trigger warnings."""
        p = PostProcessor()
        sql = "CREATE PROCEDURE foo AS BEGIN SELECT 1 END"
        warnings = p._check_warnings(sql, "tsql", "postgres")
        assert len(warnings) == 1
        assert "Procedural" in warnings[0]

    def test_materialized_view_warning(self):
        """Materialized view patterns trigger warnings."""
        p = PostProcessor()
        sql = "CREATE MATERIALIZED VIEW mv AS SELECT 1"
        warnings = p._check_warnings(sql, "postgres", "mysql")
        assert len(warnings) == 1
        assert "Materialized" in warnings[0]

    def test_normal_select_no_warnings(self):
        """Normal queries should produce no warnings."""
        p = PostProcessor()
        sql = "SELECT name FROM users WHERE id = 1"
        warnings = p._check_warnings(sql, "mysql", "postgres")
        assert warnings == []

    def test_process_method_includes_check_warnings(self):
        """PostProcessor.process() must include _check_warnings output in notes."""
        p = PostProcessor()
        sql = "INSERT OVERWRITE TABLE t SELECT 1"
        result, notes = p.process(sql, "hive", "postgres")
        assert any("INSERT OVERWRITE" in n for n in notes)
