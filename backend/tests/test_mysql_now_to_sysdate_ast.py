"""G6-R1: AST-first MySQL NOW() → Oracle SYSDATE migration tests.

Covers the helper-level transform and the full production pipeline for
mysql → oracle.  Expected outputs are hardcoded from the verified
production contract; no dependency on the legacy rule-engine rule.
"""
import pytest
import sqlglot
from sqlglot import exp

from backend.core.transpiler import SQLTranspiler

NOTE = "Converted NOW to SYSDATE (AST)"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _helper(sql: str, target: str = "oracle") -> tuple[exp.Expression, list[str]]:
    """Parse sql as mysql and run the AST transform directly."""
    t = SQLTranspiler.__new__(SQLTranspiler)
    ast = sqlglot.parse_one(sql, read="mysql")
    return t._ast_mysql_now_to_sysdate(ast, target)


def _norm(sql: str) -> str:
    return " ".join(sql.split())


# ---------------------------------------------------------------------------
# Helper-level tests (no PostProcessor, no transpile pipeline)
# ---------------------------------------------------------------------------

class TestHelperAcceptCases:
    """NOW() with zero arguments must be rewritten to SYSDATE."""

    def test_simple(self):
        ast, notes = _helper("SELECT NOW() FROM t")
        assert notes == [NOTE]
        assert _norm(ast.sql(dialect="oracle")) == "SELECT SYSDATE FROM t"

    def test_multiple_now(self):
        ast, notes = _helper("SELECT NOW(), NOW() FROM t")
        assert notes == [NOTE]
        assert _norm(ast.sql(dialect="oracle")) == "SELECT SYSDATE, SYSDATE FROM t"

    def test_nested_in_expression(self):
        ast, notes = _helper("SELECT CONCAT(NOW(), 'x') FROM t")
        assert notes == [NOTE]
        assert _norm(ast.sql(dialect="oracle")) == "SELECT CONCAT(SYSDATE, 'x') FROM t"

    def test_in_where(self):
        ast, notes = _helper("SELECT NOW() FROM t WHERE x = NOW()")
        assert notes == [NOTE]
        out = _norm(ast.sql(dialect="oracle"))
        assert out == "SELECT SYSDATE FROM t WHERE x = SYSDATE"

    def test_interval_arithmetic(self):
        ast, notes = _helper("SELECT NOW() + INTERVAL 1 DAY FROM t")
        assert notes == [NOTE]
        out = _norm(ast.sql(dialect="oracle"))
        assert "SYSDATE + INTERVAL '1' DAY" in out

    def test_with_alias(self):
        ast, notes = _helper("SELECT NOW() AS ts FROM t")
        assert notes == [NOTE]
        assert _norm(ast.sql(dialect="oracle")) == "SELECT SYSDATE AS ts FROM t"


class TestHelperNoTransformCases:
    """Forms that must NOT fire the transform."""

    def test_now_with_precision_arg(self):
        """NOW(6) has a non-empty expressions list — not matched."""
        ast, notes = _helper("SELECT NOW(6) FROM t")
        assert notes == []
        out = _norm(ast.sql(dialect="oracle"))
        assert "NOW(6)" in out
        assert "SYSDATE" not in out

    def test_string_literal_no_transform(self):
        """NOW() inside a string literal must not be rewritten."""
        ast, notes = _helper("SELECT 'NOW()' AS label FROM t")
        assert notes == []
        out = _norm(ast.sql(dialect="oracle"))
        assert "'NOW()'" in out
        assert "SYSDATE" not in out

    def test_comment_now_not_transformed(self):
        """NOW() inside a comment: the real NOW() in the SELECT is
        converted; the comment text is preserved as a block comment."""
        ast, notes = _helper("SELECT NOW() FROM t -- NOW() comment")
        assert notes == [NOTE]
        out = _norm(ast.sql(dialect="oracle"))
        assert "SYSDATE" in out
        assert "NOW() comment" in out

    def test_mylist_now_identifier_no_transform(self):
        """MYNOW is an identifier, not a NOW() call — not matched."""
        ast, notes = _helper("SELECT MYNOW FROM t")
        assert notes == []
        assert _norm(ast.sql(dialect="oracle")) == "SELECT MYNOW FROM t"


# ---------------------------------------------------------------------------
# Production-path tests (full SQLTranspiler.transpile pipeline)
# ---------------------------------------------------------------------------

class TestProductionPipeline:
    """The full transpile() path must produce the expected output and notes
    for every mysql → oracle NOW() case."""

    @classmethod
    def setup_class(cls):
        cls.t = SQLTranspiler()

    @pytest.mark.parametrize(
        ("sql", "expected"),
        [
            ("SELECT NOW() FROM t", "SELECT SYSDATE FROM t"),
            ("SELECT NOW(6) FROM t", "SELECT NOW(6) FROM t"),
            ("SELECT NOW(), NOW() FROM t", "SELECT SYSDATE, SYSDATE FROM t"),
            ("SELECT CONCAT(NOW(), 'x') FROM t", "SELECT CONCAT(SYSDATE, 'x') FROM t"),
            ("SELECT 'NOW()' AS label FROM t", "SELECT 'NOW()' AS label FROM t"),
            ("SELECT NOW() FROM t WHERE x = NOW()", "SELECT SYSDATE FROM t WHERE x = SYSDATE"),
            ("SELECT MYNOW FROM t", "SELECT MYNOW FROM t"),
        ],
    )
    def test_output_matches_expected(self, sql, expected):
        result = self.t.transpile(sql, source="mysql", target="oracle", validate=False)
        assert result.success is True, result.error
        assert _norm(result.target_sql) == expected, f"output mismatch for: {sql}"

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT NOW() FROM t",
            "SELECT NOW(), NOW() FROM t",
            "SELECT NOW() FROM t WHERE x = NOW()",
        ],
    )
    def test_note_is_recorded(self, sql):
        result = self.t.transpile(sql, source="mysql", target="oracle", validate=False)
        assert NOTE in result.transformations

    def test_now_with_arg_no_note(self):
        """NOW(6) is not converted; no AST note emitted."""
        result = self.t.transpile("SELECT NOW(6) FROM t", source="mysql", target="oracle", validate=False)
        assert result.success is True
        assert "NOW(6)" in result.target_sql
        assert NOTE not in result.transformations

    def test_string_literal_no_note(self):
        result = self.t.transpile("SELECT 'NOW()' AS label FROM t", source="mysql", target="oracle", validate=False)
        assert result.success is True
        assert "'NOW()'" in result.target_sql
        assert "SYSDATE" not in result.target_sql
        assert NOTE not in result.transformations

    def test_mylist_identifier_no_note(self):
        result = self.t.transpile("SELECT MYNOW FROM t", source="mysql", target="oracle", validate=False)
        assert result.success is True
        assert "MYNOW" in result.target_sql
        assert NOTE not in result.transformations
