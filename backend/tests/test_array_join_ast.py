"""P5: AST-first ClickHouse ARRAY JOIN → UNNEST migration tests.

Covers the helper-level transform and the full production pipeline for
clickhouse → postgres.  The lexical rule
``clickhouse_array_join_to_postgres`` was shadowed by this AST transform
and removed from the rule engine; these tests lock the production contract
so the removal is provably safe.

Expected outputs are hardcoded from the verified production contract; the
``CROSS JOIN LATERAL UNNEST`` form that the old regex emitted is no longer
required (Postgres treats ``CROSS JOIN UNNEST(...)`` and
``CROSS JOIN LATERAL UNNEST(...)`` equivalently for non-correlated
expressions, and the non-LATERAL form is the one sqlglot serializes).
"""
import pytest
import sqlglot
from sqlglot import exp

from backend.core.transpiler import SQLTranspiler

NOTE = "Converted ARRAY JOIN to CROSS JOIN UNNEST"

# (input, expected normalized output) — from verified production contract
EXPECTED = [
    ("SELECT * FROM t ARRAY JOIN arr",
     "SELECT * FROM t CROSS JOIN UNNEST(arr) AS t(value)"),
    ("SELECT * FROM t ARRAY JOIN arr AS x",
     "SELECT * FROM t CROSS JOIN UNNEST(arr) AS x(value)"),
    ("SELECT id FROM orders o ARRAY JOIN o.tags",
     "SELECT id FROM orders AS o CROSS JOIN UNNEST(o.tags) AS t(value)"),
    # combined with the groupArray transform (both fire)
    ("SELECT groupArray(name), * FROM t ARRAY JOIN tags",
     "SELECT ARRAY_AGG(name), * FROM t CROSS JOIN UNNEST(tags) AS t(value)"),
    # ARRAY JOIN inside a string literal: not a join, left untouched
    ("SELECT 'ARRAY JOIN arr' AS label FROM t",
     "SELECT 'ARRAY JOIN arr' AS label FROM t"),
    # no ARRAY JOIN present: transform is a no-op
    ("SELECT a FROM t", "SELECT a FROM t"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _helper(sql: str, target: str = "postgres") -> tuple[exp.Expression, list[str]]:
    """Parse sql as clickhouse and run the ARRAY JOIN AST transform directly."""
    t = SQLTranspiler.__new__(SQLTranspiler)
    ast = sqlglot.parse_one(sql, read="clickhouse")
    return t._ast_clickhouse_array_join_to_unnest(ast, target)


def _norm(sql: str) -> str:
    return " ".join(sql.split())


# ---------------------------------------------------------------------------
# Helper-level tests (no PostProcessor, no transpile pipeline)
# ---------------------------------------------------------------------------

class TestHelperAcceptCases:
    """ARRAY JOIN must be rewritten to CROSS JOIN UNNEST in every case."""

    def test_bare_form(self):
        ast, notes = _helper("SELECT * FROM t ARRAY JOIN arr")
        assert notes == [NOTE]
        assert _norm(ast.sql(dialect="postgres")) == "SELECT * FROM t CROSS JOIN UNNEST(arr) AS t(value)"

    def test_explicit_alias_preserved(self):
        """User-provided alias ('ARRAY JOIN arr AS x') must survive as the
        UNNEST table alias, not be clobbered by the default 't'."""
        ast, notes = _helper("SELECT * FROM t ARRAY JOIN arr AS x")
        assert notes == [NOTE]
        out = _norm(ast.sql(dialect="postgres"))
        assert "UNNEST(arr) AS x(value)" in out, out
        assert out == "SELECT * FROM t CROSS JOIN UNNEST(arr) AS x(value)"

    def test_qualified_column(self):
        ast, notes = _helper("SELECT id FROM orders o ARRAY JOIN o.tags")
        assert notes == [NOTE]
        out = _norm(ast.sql(dialect="postgres"))
        assert "UNNEST(o.tags)" in out, out

    def test_string_literal_no_transform(self):
        """ARRAY JOIN inside a string literal must not fire (a literal is
        not a join node in the AST)."""
        sql = "SELECT 'ARRAY JOIN arr' AS label FROM t"
        ast, notes = _helper(sql)
        assert notes == []
        out = _norm(ast.sql(dialect="postgres"))
        assert "'ARRAY JOIN arr'" in out
        assert "UNNEST" not in out
        assert out == "SELECT 'ARRAY JOIN arr' AS label FROM t"

    def test_no_array_join_is_noop(self):
        sql = "SELECT a FROM t"
        ast, notes = _helper(sql)
        assert notes == []
        assert _norm(ast.sql(dialect="postgres")) == _norm(
            sqlglot.transpile(sql, read="clickhouse", write="postgres", pretty=False)[0]
        )

    def test_multiple_array_joins(self):
        """Every ARRAY JOIN node is rewritten independently."""
        ast, notes = _helper("SELECT * FROM t ARRAY JOIN a ARRAY JOIN b")
        assert notes == [NOTE]
        out = _norm(ast.sql(dialect="postgres"))
        assert out.count("CROSS JOIN UNNEST") == 2, out


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

    def test_note_is_recorded(self):
        result = self.t.transpile(
            "SELECT * FROM t ARRAY JOIN arr",
            source="clickhouse", target="postgres", validate=False,
        )
        assert NOTE in result.transformations

    def test_target_is_valid_postgres(self):
        """The rewritten output must parse as valid Postgres — the whole point
        of the migration is that 'ARRAY JOIN' no longer reaches the target."""
        result = self.t.transpile(
            "SELECT * FROM t ARRAY JOIN arr",
            source="clickhouse", target="postgres", validate=True,
        )
        assert result.success is True
        assert result.target_validation_state == "target_valid"
        assert "ARRAY JOIN" not in result.target_sql.upper()
        sqlglot.parse_one(result.target_sql, read="postgres")  # raises if invalid

    def test_lexical_rule_is_gone(self):
        """The shadowed regex rule must no longer be present in the engine."""
        from backend.core.rules import TRANSFORM_RULES
        assert not any(
            r.name == "clickhouse_array_join_to_postgres" for r in TRANSFORM_RULES
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
