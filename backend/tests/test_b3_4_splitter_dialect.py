"""B3-4 — SQL statement splitter dialect boundaries.

The splitter documented ``dialect`` as unused.  The contract now:

* T-SQL: a standalone ``GO`` line (optionally ``GO <count>``) is a
  batch separator; ``GO`` inside strings/identifiers or on a mixed line
  is never a separator; other dialects do not treat ``GO`` specially.
* Oracle: semicolons inside PL/SQL blocks (``BEGIN … END``, nested
  ``CASE … END``, ``IF … END IF``) are internal — the block is ONE
  statement ending at its closing ``END;``.
* Statement content and boundaries are asserted exactly (the splitter
  never rewrites SQL), not just list lengths.
* Unterminated quotes/comments remain conservative (no crash, no
  fabricated splits).
"""
from __future__ import annotations

from backend.utils.validators import split_sql_statements


class TestB3_4_TsqlGoBatch:
    def test_go_on_own_line_splits(self):
        sql = "SELECT 1\nGO\nSELECT 2\nGO\nSELECT 3"
        result = split_sql_statements(sql, dialect="tsql")
        assert result == ["SELECT 1", "SELECT 2", "SELECT 3"]

    def test_go_with_count_splits(self):
        sql = "SELECT 1\nGO 5\nSELECT 2"
        result = split_sql_statements(sql, dialect="tsql")
        assert result == ["SELECT 1", "SELECT 2"]

    def test_go_case_insensitive(self):
        sql = "SELECT 1\ngo\nSELECT 2"
        result = split_sql_statements(sql, dialect="tsql")
        assert result == ["SELECT 1", "SELECT 2"]

    def test_go_inside_string_not_a_separator(self):
        sql = "SELECT 'GO' AS word"
        result = split_sql_statements(sql, dialect="tsql")
        assert result == [sql]

    def test_go_column_not_a_separator(self):
        sql = "SELECT GO FROM t"
        result = split_sql_statements(sql, dialect="tsql")
        assert result == [sql]

    def test_go_embedded_in_identifier_not_a_separator(self):
        sql = "SELECT gopher, cargo FROM t"
        result = split_sql_statements(sql, dialect="tsql")
        assert result == [sql]

    def test_go_on_line_with_sql_not_a_separator(self):
        sql = "SELECT 1 GO SELECT 2"
        result = split_sql_statements(sql, dialect="tsql")
        assert result == [sql]

    def test_go_not_a_separator_in_other_dialects(self):
        sql = "SELECT 1\nGO\nSELECT 2"
        for dialect in ("postgres", "mysql", "oracle", "hive"):
            result = split_sql_statements(sql, dialect=dialect)
            assert result == [sql], dialect


class TestB3_4_OraclePlsqlBlocks:
    def test_plsql_block_is_one_statement(self):
        sql = "BEGIN\n  UPDATE t SET a = 1;\n  UPDATE t SET b = 2;\nEND;"
        result = split_sql_statements(sql, dialect="oracle")
        assert len(result) == 1, result
        assert result[0] == "BEGIN\n  UPDATE t SET a = 1;\n  UPDATE t SET b = 2;\nEND"

    def test_block_with_trailing_sql_splits_after_end(self):
        sql = "BEGIN\n  NULL;\nEND;\nSELECT 1;"
        result = split_sql_statements(sql, dialect="oracle")
        assert result == ["BEGIN\n  NULL;\nEND", "SELECT 1"]

    def test_nested_begin_end(self):
        sql = "BEGIN\n  BEGIN\n    NULL;\n  END;\nEND;"
        result = split_sql_statements(sql, dialect="oracle")
        assert len(result) == 1, result

    def test_case_end_inside_block(self):
        sql = "BEGIN\n  x := CASE WHEN y THEN 1 ELSE 2 END;\nEND;"
        result = split_sql_statements(sql, dialect="oracle")
        assert len(result) == 1, result

    def test_if_end_if_inside_block(self):
        sql = "BEGIN\n  IF x > 0 THEN\n    x := x + 1;\n  END IF;\nEND;"
        result = split_sql_statements(sql, dialect="oracle")
        assert len(result) == 1, result

    def test_plain_select_case_end_still_splits(self):
        """A standalone SQL CASE...END must not swallow the statement
        terminator."""
        sql = "SELECT CASE WHEN x THEN 1 ELSE 2 END FROM t; SELECT 2;"
        result = split_sql_statements(sql, dialect="oracle")
        assert result == [
            "SELECT CASE WHEN x THEN 1 ELSE 2 END FROM t",
            "SELECT 2",
        ]

    def test_block_requires_oracle_dialect(self):
        """Block tracking is an Oracle-dialect feature; other dialects
        keep the plain semicolon behavior."""
        sql = "BEGIN\n  NULL;\nEND;"
        result = split_sql_statements(sql, dialect="postgres")
        assert len(result) == 2, result  # BEGIN; and NULL; END as plain statements


class TestB3_4_ContentPreservation:
    def test_fragment_content_is_exact(self):
        sql = "SELECT 'a;b' AS x; /* keep ; me */ SELECT `c;d`;"
        result = split_sql_statements(sql, dialect="mysql")
        assert result == ["SELECT 'a;b' AS x", "/* keep ; me */ SELECT `c;d`"]

    def test_unterminated_quote_conservative(self):
        sql = "SELECT 'unterminated"
        result = split_sql_statements(sql)
        assert result == [sql]  # no fabricated split, content preserved

    def test_unterminated_block_comment_conservative(self):
        sql = "SELECT 1; /* unterminated"
        result = split_sql_statements(sql)
        # The unterminated comment swallows the rest conservatively;
        # content must be preserved, never dropped.
        assert "".join(result).strip().endswith("/* unterminated")
