"""G6-R2: AST-first groupArray → ARRAY_AGG migration tests.

Covers the helper-level transform and the full production pipeline for
clickhouse → postgres.  Expected outputs are hardcoded from the verified
production contract; no dependency on the legacy rule-engine rule.
"""
import pytest
import sqlglot
from sqlglot import exp

from backend.core.transpiler import SQLTranspiler

NOTE = "Converted groupArray to ARRAY_AGG"

# (input, expected normalized output) — from verified production contract
EXPECTED = [
    ("SELECT groupArray(x) FROM t", "SELECT ARRAY_AGG(x) FROM t"),
    ("SELECT groupArray(DISTINCT x) FROM t", "SELECT ARRAY_AGG(DISTINCT x) FROM t"),
    ("SELECT groupArray(CONCAT(a, b)) FROM t", "SELECT ARRAY_AGG(a || b) FROM t"),
    ("SELECT groupArray(a), groupArray(b) FROM t", "SELECT ARRAY_AGG(a), ARRAY_AGG(b) FROM t"),
    ("SELECT dept FROM t GROUP BY dept HAVING groupArray(x) IS NOT NULL",
     "SELECT dept FROM t GROUP BY dept HAVING NOT ARRAY_AGG(x) IS NULL"),
    ("SELECT groupArray(x), groupArray(DISTINCT y) FROM t",
     "SELECT ARRAY_AGG(x), ARRAY_AGG(DISTINCT y) FROM t"),
    ("SELECT 'groupArray(x)' AS label FROM t", "SELECT 'groupArray(x)' AS label FROM t"),
    ("SELECT groupArray(x) FROM t -- groupArray(fake)",
     "SELECT ARRAY_AGG(x) FROM t /* groupArray(fake) */"),
    ("SELECT groupArrayIf(x, x > 1) FROM t", "SELECT GROUPARRAYIF(x, x > 1) FROM t"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _helper(sql: str, target: str = "postgres") -> tuple[exp.Expression, list[str]]:
    """Parse sql as clickhouse and run the AST transform directly."""
    t = SQLTranspiler.__new__(SQLTranspiler)
    ast = sqlglot.parse_one(sql, read="clickhouse")
    return t._ast_grouparray_to_arrayagg(ast, target)


def _norm(sql: str) -> str:
    return " ".join(sql.split())


# ---------------------------------------------------------------------------
# Helper-level tests (no PostProcessor, no transpile pipeline)
# ---------------------------------------------------------------------------

class TestHelperAcceptCases:
    """groupArray must be rewritten to ARRAY_AGG in every applicable case."""

    def test_simple(self):
        ast, notes = _helper("SELECT groupArray(x) FROM t")
        assert notes == [NOTE]
        assert _norm(ast.sql(dialect="postgres")) == "SELECT ARRAY_AGG(x) FROM t"

    def test_distinct(self):
        """DISTINCT must survive as the inner expression of ArrayAgg."""
        ast, notes = _helper("SELECT groupArray(DISTINCT x) FROM t")
        assert notes == [NOTE]
        out = _norm(ast.sql(dialect="postgres"))
        assert "ARRAY_AGG(DISTINCT x)" in out
        assert out == "SELECT ARRAY_AGG(DISTINCT x) FROM t"

    def test_nested_expression(self):
        ast, notes = _helper("SELECT groupArray(CONCAT(a, b)) FROM t")
        assert notes == [NOTE]
        assert _norm(ast.sql(dialect="postgres")) == "SELECT ARRAY_AGG(a || b) FROM t"

    def test_multiple_calls(self):
        ast, notes = _helper("SELECT groupArray(a), groupArray(b) FROM t")
        assert notes == [NOTE]
        out = _norm(ast.sql(dialect="postgres"))
        assert "ARRAY_AGG(a)" in out
        assert "ARRAY_AGG(b)" in out
        assert out == "SELECT ARRAY_AGG(a), ARRAY_AGG(b) FROM t"

    def test_having(self):
        ast, notes = _helper("SELECT dept FROM t GROUP BY dept HAVING groupArray(x) IS NOT NULL")
        assert notes == [NOTE]
        assert _norm(ast.sql(dialect="postgres")) == (
            "SELECT dept FROM t GROUP BY dept HAVING NOT ARRAY_AGG(x) IS NULL"
        )

    def test_mixed_normal_and_distinct(self):
        ast, notes = _helper("SELECT groupArray(x), groupArray(DISTINCT y) FROM t")
        assert notes == [NOTE]
        out = _norm(ast.sql(dialect="postgres"))
        assert "ARRAY_AGG(x)" in out
        assert "ARRAY_AGG(DISTINCT y)" in out
        assert out == "SELECT ARRAY_AGG(x), ARRAY_AGG(DISTINCT y) FROM t"

    def test_string_literal_no_transform(self):
        """groupArray inside a string literal must be left untouched."""
        ast, notes = _helper("SELECT 'groupArray(x)' AS label FROM t")
        assert notes == []
        out = _norm(ast.sql(dialect="postgres"))
        assert "'groupArray(x)'" in out
        assert "ARRAY_AGG" not in out
        assert out == "SELECT 'groupArray(x)' AS label FROM t"

    def test_comment_no_cross_boundary(self):
        """groupArray inside a line comment must not be rewritten;
        sqlglot's postgres serializer rewrites the comment to block form —
        this is a native sqlglot artifact, not a transform bug."""
        ast, notes = _helper("SELECT groupArray(x) FROM t -- groupArray(fake)")
        assert notes == [NOTE]
        out = _norm(ast.sql(dialect="postgres"))
        assert "ARRAY_AGG(x)" in out
        assert out == "SELECT ARRAY_AGG(x) FROM t /* groupArray(fake) */"

    def test_grouparrayif_not_matched(self):
        """groupArrayIf is a different function and must not fire."""
        sql = "SELECT groupArrayIf(x, x > 1) FROM t"
        ast, notes = _helper(sql)
        # groupArrayIf is not parsed as AnonymousAggFunc with this='groupArray',
        # so the transform should not fire on it.
        assert notes == []
        out = _norm(ast.sql(dialect="postgres"))
        expected = _norm(sqlglot.transpile(sql, read="clickhouse", write="postgres", pretty=False)[0])
        assert out == expected


# ---------------------------------------------------------------------------
# Production-path tests (full SQLTranspiler.transpile pipeline)
# ---------------------------------------------------------------------------

class TestProductionPipeline:
    """The full transpile() path must produce the expected output and notes
    for every clickhouse→postgres case."""

    @classmethod
    def setup_class(cls):
        cls.t = SQLTranspiler()

    @pytest.mark.parametrize(
        ("sql", "expected"),
        EXPECTED,
    )
    def test_output_matches_expected(self, sql, expected):
        result = self.t.transpile(sql, source="clickhouse", target="postgres", validate=False)
        assert result.success is True, result.error
        assert _norm(result.target_sql) == expected, f"output mismatch for: {sql}"

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT groupArray(x) FROM t",
            "SELECT groupArray(DISTINCT x) FROM t",
            "SELECT groupArray(CONCAT(a, b)) FROM t",
            "SELECT groupArray(a), groupArray(b) FROM t",
        ],
    )
    def test_note_is_recorded(self, sql):
        result = self.t.transpile(sql, source="clickhouse", target="postgres", validate=False)
        assert NOTE in result.transformations

    def test_string_literal_no_note(self):
        """groupArray inside a string literal: no transformation should fire."""
        result = self.t.transpile(
            "SELECT 'groupArray(x)' AS label FROM t",
            source="clickhouse", target="postgres", validate=False,
        )
        assert result.success is True
        assert "'groupArray(x)'" in result.target_sql
        assert "ARRAY_AGG" not in result.target_sql
        assert NOTE not in result.transformations

    def test_comment_case(self):
        """Real groupArray call is converted; comment reformatting is a
        native sqlglot artifact (line → block comment)."""
        result = self.t.transpile(
            "SELECT groupArray(x) FROM t -- groupArray(fake)",
            source="clickhouse", target="postgres", validate=False,
        )
        assert result.success is True
        assert "ARRAY_AGG(x)" in result.target_sql
        assert NOTE in result.transformations

    def test_distinct_preserved_in_pipeline(self):
        result = self.t.transpile(
            "SELECT groupArray(DISTINCT x) FROM t",
            source="clickhouse", target="postgres", validate=False,
        )
        assert result.success is True
        assert "ARRAY_AGG(DISTINCT x)" in result.target_sql

    def test_no_grouparray_in_output(self):
        """No executable groupArray occurrence must remain in the target output."""
        for sql in [
            "SELECT groupArray(x) FROM t",
            "SELECT groupArray(DISTINCT x) FROM t",
            "SELECT groupArray(a), groupArray(b) FROM t",
        ]:
            result = self.t.transpile(sql, source="clickhouse", target="postgres", validate=False)
            assert "GROUPARRAY" not in result.target_sql.upper()
