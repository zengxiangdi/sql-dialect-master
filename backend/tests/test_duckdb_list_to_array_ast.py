"""G6-L: AST-first DuckDB LIST datatype → ARRAY migration tests.

Covers the helper-level transform and the full production pipeline for
duckdb → hive/spark.  Expected outputs are hardcoded from the verified
production contract; no dependency on the legacy rule-engine rule.
"""
import pytest
import sqlglot
from sqlglot import exp

from backend.core.transpiler import SQLTranspiler

NOTE = "Converted LIST to ARRAY (AST)"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _helper(sql: str, target: str = "hive") -> tuple[exp.Expression, list[str]]:
    """Parse sql as duckdb and run the AST transform directly."""
    t = SQLTranspiler.__new__(SQLTranspiler)
    ast = sqlglot.parse_one(sql, read="duckdb")
    return t._ast_duckdb_list_to_array(ast, target)


def _norm(sql: str) -> str:
    return " ".join(sql.split())


# ---------------------------------------------------------------------------
# Helper-level tests (no PostProcessor, no transpile pipeline)
# ---------------------------------------------------------------------------

class TestHelperListTypeForms:
    """LIST datatype in CAST expressions must be rewritten to ARRAY."""

    def test_bare_list(self):
        ast, notes = _helper("SELECT CAST(x AS LIST) FROM t")
        assert notes == [NOTE]
        assert _norm(ast.sql(dialect="hive")) == "SELECT CAST(x AS ARRAY) FROM t"

    def test_list_int(self):
        ast, notes = _helper("SELECT CAST(x AS LIST(INT)) FROM t")
        assert notes == [NOTE]
        assert _norm(ast.sql(dialect="hive")) == "SELECT CAST(x AS ARRAY<INT>) FROM t"

    def test_list_varchar(self):
        ast, notes = _helper("SELECT CAST(x AS LIST(VARCHAR(10))) FROM t")
        assert notes == [NOTE]
        assert _norm(ast.sql(dialect="hive")) == "SELECT CAST(x AS ARRAY<STRING>) FROM t"

    def test_list_interval(self):
        ast, notes = _helper("SELECT CAST(x AS LIST(INTERVAL)) FROM t")
        assert notes == [NOTE]
        assert _norm(ast.sql(dialect="hive")) == "SELECT CAST(x AS ARRAY<INTERVAL>) FROM t"

    def test_nested_double_cast(self):
        ast, notes = _helper("SELECT CAST(CAST(x AS LIST) AS LIST) FROM t")
        assert notes == [NOTE]
        assert _norm(ast.sql(dialect="hive")) == "SELECT CAST(CAST(x AS ARRAY) AS ARRAY) FROM t"

    def test_multiple_casts(self):
        ast, notes = _helper("SELECT CAST(a AS LIST), CAST(b AS LIST) FROM t")
        assert notes == [NOTE]
        assert _norm(ast.sql(dialect="hive")) == "SELECT CAST(a AS ARRAY), CAST(b AS ARRAY) FROM t"

    def test_spark_target_bare(self):
        ast, notes = _helper("SELECT CAST(x AS LIST) FROM t", target="spark")
        assert notes == [NOTE]
        assert _norm(ast.sql(dialect="spark")) == "SELECT CAST(x AS ARRAY) FROM t"

    def test_spark_target_param(self):
        ast, notes = _helper("SELECT CAST(x AS LIST(INT)) FROM t", target="spark")
        assert notes == [NOTE]
        assert _norm(ast.sql(dialect="spark")) == "SELECT CAST(x AS ARRAY<INT>) FROM t"


class TestHelperNoTransformCases:
    """Function forms, identifiers, and literals must NOT fire the transform."""

    def test_list_function_no_transform(self):
        """LIST(x) parses as exp.ArrayAgg, not exp.DataType(LIST) — no transform."""
        ast, notes = _helper("SELECT LIST(x) FROM t GROUP BY g")
        assert notes == []
        out = _norm(ast.sql(dialect="hive"))
        assert out == "SELECT COLLECT_LIST(x) FROM t GROUP BY g"

    def test_list_distinct_function_no_transform(self):
        """LIST(DISTINCT x) parses as exp.ArrayAgg with Distinct inner — no transform."""
        ast, notes = _helper("SELECT LIST(DISTINCT x) FROM t GROUP BY g")
        assert notes == []
        out = _norm(ast.sql(dialect="hive"))
        assert out == "SELECT COLLECT_LIST(DISTINCT x) FROM t GROUP BY g"

    def test_mylist_identifier_no_transform(self):
        """MYLIST is an identifier, not a LIST type — no transform."""
        ast, notes = _helper("SELECT MYLIST FROM t")
        assert notes == []
        assert _norm(ast.sql(dialect="hive")) == "SELECT MYLIST FROM t"

    def test_string_literal_list_no_transform(self):
        """LIST inside a string literal must not be rewritten."""
        ast, notes = _helper("SELECT 'LIST(x)' AS label FROM t")
        assert notes == []
        out = _norm(ast.sql(dialect="hive"))
        assert "'LIST(x)'" in out
        assert "ARRAY" not in out

    def test_comment_list_no_transform(self):
        """LIST inside a comment must not affect the transform decision.
        The real CAST is still converted; the comment text is preserved
        as a block comment by the native serializer."""
        ast, notes = _helper("SELECT CAST(x AS LIST) FROM t -- LIST(fake)")
        assert notes == [NOTE]
        out = _norm(ast.sql(dialect="hive"))
        assert "CAST(x AS ARRAY)" in out
        assert "LIST(fake)" in out


# ---------------------------------------------------------------------------
# Production-path tests (full SQLTranspiler.transpile pipeline)
# ---------------------------------------------------------------------------

class TestProductionPipeline:
    """The full transpile() path must produce the expected output and notes
    for every duckdb→hive/spark case."""

    @classmethod
    def setup_class(cls):
        cls.t = SQLTranspiler()

    def _run(self, sql: str, target: str) -> dict:
        return self.t.transpile(sql, source="duckdb", target=target, validate=False)

    # -- Expected outputs (normalized) for each case × target --

    @pytest.mark.parametrize(
        ("sql", "expected_hive", "expected_spark"),
        [
            (
                "SELECT CAST(x AS LIST) FROM t",
                "SELECT CAST(x AS ARRAY) FROM t",
                "SELECT CAST(x AS ARRAY) FROM t",
            ),
            (
                "SELECT CAST(x AS LIST(INT)) FROM t",
                "SELECT CAST(x AS ARRAY<INT>) FROM t",
                "SELECT CAST(x AS ARRAY<INT>) FROM t",
            ),
            (
                "SELECT CAST(x AS LIST(VARCHAR(10))) FROM t",
                "SELECT CAST(x AS ARRAY<STRING>) FROM t",
                "SELECT CAST(x AS ARRAY<STRING>) FROM t",
            ),
            (
                "SELECT CAST(x AS LIST(INTERVAL)) FROM t",
                "SELECT CAST(x AS ARRAY<INTERVAL>) FROM t",
                "SELECT CAST(x AS ARRAY<INTERVAL>) FROM t",
            ),
            (
                "SELECT CAST(CAST(x AS LIST) AS LIST) FROM t",
                "SELECT CAST(CAST(x AS ARRAY) AS ARRAY) FROM t",
                "SELECT CAST(CAST(x AS ARRAY) AS ARRAY) FROM t",
            ),
            (
                "SELECT CAST(a AS LIST), CAST(b AS LIST) FROM t",
                "SELECT CAST(a AS ARRAY), CAST(b AS ARRAY) FROM t",
                "SELECT CAST(a AS ARRAY), CAST(b AS ARRAY) FROM t",
            ),
            (
                "SELECT CAST(x AS LIST) || y FROM t",
                "SELECT CAST(x AS ARRAY) || y FROM t",
                "SELECT CAST(x AS ARRAY) || y FROM t",
            ),
        ],
    )
    def test_output_matches_expected(self, sql, expected_hive, expected_spark):
        r_hive = self._run(sql, "hive")
        assert r_hive.success is True, r_hive.error
        assert _norm(r_hive.target_sql) == expected_hive, f"hive: {sql}"

        r_spark = self._run(sql, "spark")
        assert r_spark.success is True, r_spark.error
        assert _norm(r_spark.target_sql) == expected_spark, f"spark: {sql}"

    def test_note_recorded_hive(self):
        r = self._run("SELECT CAST(x AS LIST) FROM t", "hive")
        assert NOTE in r.transformations

    def test_note_recorded_spark(self):
        r = self._run("SELECT CAST(x AS LIST) FROM t", "spark")
        assert NOTE in r.transformations

    def test_string_literal_no_note(self):
        """LIST inside a string literal: no transformation should fire."""
        r = self._run("SELECT 'LIST(x)' AS label FROM t", "hive")
        assert r.success is True
        assert "'LIST(x)'" in r.target_sql
        assert "ARRAY" not in r.target_sql
        assert NOTE not in r.transformations

    def test_comment_case(self):
        """Real CAST is converted; comment preserved as block comment."""
        r = self._run("SELECT CAST(x AS LIST) FROM t -- LIST(fake)", "hive")
        assert r.success is True
        assert "CAST(x AS ARRAY)" in r.target_sql
        assert NOTE in r.transformations

    def test_list_function_no_note(self):
        """LIST(x) aggregate is handled natively; no AST note emitted."""
        r = self._run("SELECT LIST(x) FROM t GROUP BY g", "hive")
        assert r.success is True
        assert "COLLECT_LIST(x)" in r.target_sql
        assert NOTE not in r.transformations

    def test_list_distinct_function_no_note(self):
        r = self._run("SELECT LIST(DISTINCT x) FROM t GROUP BY g", "hive")
        assert r.success is True
        assert "COLLECT_LIST(DISTINCT x)" in r.target_sql
        assert NOTE not in r.transformations

    def test_mylist_identifier_no_note(self):
        r = self._run("SELECT MYLIST FROM t", "hive")
        assert r.success is True
        assert "MYLIST" in r.target_sql
        assert NOTE not in r.transformations

    def test_no_list_type_in_output(self):
        """No executable LIST type occurrence must remain in the target output."""
        for sql in [
            "SELECT CAST(x AS LIST) FROM t",
            "SELECT CAST(x AS LIST(INT)) FROM t",
            "SELECT CAST(CAST(x AS LIST) AS LIST) FROM t",
        ]:
            for tgt in ("hive", "spark"):
                r = self._run(sql, tgt)
                assert "LIST" not in r.target_sql.upper() or "LIST" in sql.replace("CAST", "").strip(), (
                    f"unexpected LIST in {tgt} output for: {sql}\n{r.target_sql}"
                )
