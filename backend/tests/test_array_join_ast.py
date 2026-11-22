"""P5: AST-first ClickHouse ARRAY JOIN → UNNEST migration tests.

Covers the helper-level transform and the full production pipeline for
clickhouse → postgres.  The lexical rule
``clickhouse_array_join_to_postgres`` was shadowed by this AST transform
and removed from the rule engine; these tests lock the production contract
so the removal is provably safe.

The supported form expands a single array column and preserves the names
and values of explicit projections. Other ARRAY JOIN shapes require manual
conversion.
"""
from typing import cast

import pytest
import sqlglot
from sqlglot import exp

from backend.core.exceptions import ErrorCode
from backend.core.transpiler import SQLTranspiler, TranspileResult

NOTE = "Converted ARRAY JOIN to CROSS JOIN UNNEST"

# (input, expected normalized output) — from verified production contract
EXPECTED = [
    (
        "SELECT arr FROM t ARRAY JOIN arr",
        "SELECT _sdm_array._sdm_array_item AS arr FROM t CROSS JOIN UNNEST(arr) AS _sdm_array(_sdm_array_item)",
    ),
    (
        "SELECT arr, x FROM t ARRAY JOIN arr AS x",
        "SELECT arr, _sdm_array._sdm_array_item AS x FROM t CROSS JOIN UNNEST(arr) AS _sdm_array(_sdm_array_item)",
    ),
    ("SELECT id FROM orders o ARRAY JOIN o.tags",
     "SELECT id FROM orders AS o CROSS JOIN UNNEST(o.tags) AS _sdm_array(_sdm_array_item)"),
    # combined with the groupArray transform (both fire)
    ("SELECT groupArray(name) FROM t ARRAY JOIN tags",
     "SELECT ARRAY_AGG(name) FROM t CROSS JOIN UNNEST(tags) AS _sdm_array(_sdm_array_item)"),
    # ARRAY JOIN inside a string literal: not a join, left untouched
    ("SELECT 'ARRAY JOIN arr' AS label FROM t",
     "SELECT 'ARRAY JOIN arr' AS label FROM t"),
    # no ARRAY JOIN present: transform is a no-op
    ("SELECT a FROM t", "SELECT a FROM t"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _helper(sql: str) -> tuple[exp.Expression, list[str], list[str]]:
    """Parse sql as clickhouse and run the ARRAY JOIN AST transform directly."""
    t = SQLTranspiler.__new__(SQLTranspiler)
    ast = cast(exp.Expression, sqlglot.parse_one(sql, read="clickhouse"))
    return t._ast_clickhouse_array_join_to_unnest(ast)


def _norm(sql: str) -> str:
    return " ".join(sql.split())


def _target_sql(result: TranspileResult) -> str:
    assert result.target_sql is not None
    return result.target_sql


# ---------------------------------------------------------------------------
# Helper-level tests (no PostProcessor, no transpile pipeline)
# ---------------------------------------------------------------------------

class TestHelperAcceptCases:
    """Rewrite supported ARRAY JOIN shapes to CROSS JOIN UNNEST."""

    def test_bare_form(self):
        ast, notes, blockers = _helper("SELECT arr FROM t ARRAY JOIN arr")
        assert notes == [NOTE]
        assert not blockers
        assert _norm(ast.sql(dialect="postgres")) == EXPECTED[0][1]

    def test_explicit_alias_preserved(self):
        """The element alias remains the output column label."""
        ast, notes, blockers = _helper("SELECT arr, x FROM t ARRAY JOIN arr AS x")
        assert notes == [NOTE]
        assert not blockers
        assert _norm(ast.sql(dialect="postgres")) == EXPECTED[1][1]

    def test_qualified_column(self):
        ast, notes, blockers = _helper("SELECT id FROM orders o ARRAY JOIN o.tags")
        assert notes == [NOTE]
        assert not blockers
        out = _norm(ast.sql(dialect="postgres"))
        assert "UNNEST(o.tags)" in out, out

    def test_string_literal_no_transform(self):
        """ARRAY JOIN inside a string literal must not fire (a literal is
        not a join node in the AST)."""
        sql = "SELECT 'ARRAY JOIN arr' AS label FROM t"
        ast, notes, blockers = _helper(sql)
        assert notes == []
        assert not blockers
        out = _norm(ast.sql(dialect="postgres"))
        assert "'ARRAY JOIN arr'" in out
        assert "UNNEST" not in out
        assert out == "SELECT 'ARRAY JOIN arr' AS label FROM t"

    def test_no_array_join_is_noop(self):
        sql = "SELECT a FROM t"
        ast, notes, blockers = _helper(sql)
        assert notes == []
        assert not blockers
        assert _norm(ast.sql(dialect="postgres")) == _norm(
            sqlglot.transpile(sql, read="clickhouse", write="postgres", pretty=False)[0]
        )

# ---------------------------------------------------------------------------
# Production-path tests (full SQLTranspiler.transpile pipeline)
# ---------------------------------------------------------------------------

class TestProductionPipeline:
    """The full transpile() path must produce the expected output and notes
    for every clickhouse→postgres case."""

    t: SQLTranspiler

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
        assert _norm(_target_sql(result)) == expected, f"output mismatch for: {sql}"

    def test_note_is_recorded(self):
        result = self.t.transpile(
            "SELECT arr FROM t ARRAY JOIN arr",
            source="clickhouse", target="postgres", validate=False,
        )
        assert NOTE in result.transformations

    def test_target_is_valid_postgres(self):
        """The rewritten output must parse as valid Postgres — the whole point
        of the migration is that 'ARRAY JOIN' no longer reaches the target."""
        result = self.t.transpile(
            "SELECT arr FROM t ARRAY JOIN arr",
            source="clickhouse", target="postgres", validate=True,
        )
        assert result.success is True
        assert result.target_validation_state == "target_valid"
        target_sql = _target_sql(result)
        assert "ARRAY JOIN" not in target_sql.upper()
        sqlglot.parse_one(target_sql, read="postgres")  # raises if invalid

    def test_lexical_rule_is_gone(self):
        """The shadowed regex rule must no longer be present in the engine."""
        from backend.core.rules import TRANSFORM_RULES
        assert not any(
            r.name == "clickhouse_array_join_to_postgres" for r in TRANSFORM_RULES
        )


@pytest.mark.parametrize("sql", [
    "SELECT tag FROM t LEFT ARRAY JOIN tags AS tag",
    "SELECT a, b FROM t ARRAY JOIN tags AS a, scores AS b",
    "SELECT a, b FROM t ARRAY JOIN a ARRAY JOIN b",
    "SELECT * FROM t ARRAY JOIN tags",
    "SELECT t.* FROM t ARRAY JOIN tags",
    "SELECT db.t.tags FROM db.t ARRAY JOIN tags",
    "SELECT id FROM t ARRAY JOIN tags LIMIT 2 BY id",
    "SELECT count(*) FROM t ARRAY JOIN range(3) AS tag",
    "SELECT tags FROM (SELECT tags FROM t ARRAY JOIN tags) AS q",
])
def test_unsupported_array_join_returns_structured_failure(sql: str):
    for validate in (True, False):
        result = SQLTranspiler().transpile(sql, "clickhouse", "postgres", validate=validate)
        assert result.success is False
        assert result.target_sql is None
        assert result.error_code == ErrorCode.VALIDATION_FAILED
        assert result.target_validation_state == "invalid"
        assert result.error and "ARRAY JOIN requires manual conversion" in result.error
        assert NOTE not in result.transformations


@pytest.mark.parametrize(
    ("sql", "expected_labels", "expected_rows"),
    [
        (
            "SELECT tags FROM items ARRAY JOIN tags WHERE tags > 1 ORDER BY tags",
            ["tags"],
            [(2,), (3,)],
        ),
        (
            "SELECT q.tags FROM items q ARRAY JOIN q.tags WHERE q.tags > 1 ORDER BY q.tags",
            ["tags"],
            [(2,), (3,)],
        ),
        (
            "SELECT tags, tag FROM items ARRAY JOIN tags AS tag WHERE tag > 1 ORDER BY tag",
            ["tags", "tag"],
            [([1, 2, 3], 2), ([1, 2, 3], 3)],
        ),
        (
            (
                "SELECT _sdm_array.id, _sdm_array.tags FROM items AS _sdm_array "
                "ARRAY JOIN _sdm_array.tags ORDER BY _sdm_array.tags"
            ),
            ["id", "tags"],
            [(1, 1), (1, 2), (1, 3)],
        ),
    ],
)
def test_array_join_preserves_element_bindings_at_runtime(sql, expected_labels, expected_rows):
    duckdb = pytest.importorskip("duckdb")
    result = SQLTranspiler().transpile(sql, "clickhouse", "postgres")
    assert result.success and result.target_sql is not None, result.error
    with duckdb.connect() as connection:
        connection.execute("CREATE TABLE items(id INTEGER, tags INTEGER[])")
        connection.execute("INSERT INTO items VALUES (1, [1, 2, 3]), (2, [])")
        execution = connection.execute(result.target_sql)
        assert [field[0] for field in execution.description] == expected_labels
        assert execution.fetchall() == expected_rows


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
