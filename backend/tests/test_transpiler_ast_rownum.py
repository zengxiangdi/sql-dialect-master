#!/usr/bin/env python3
"""G6-A1: AST-first ROWNUM -> LIMIT migration.

Behavior tests for the AST transform added to ``SQLTranspiler``:
``_ast_rownum_to_limit`` plus the production ``transpile()`` pipeline.

Covers:
* Accepted shapes (bare ROWNUM <= N, with AND-companion predicates).
* Rejected shapes (non->= operators, string/float bounds, reversed,
  multiple predicates, OR, ORDER BY, GROUP BY, HAVING, DISTINCT,
  UNION/INTERSECT/EXCEPT, no qualifying predicate).
* Production-path tests (the full ``transpile()`` method) for the
  four supported targets, confirming the note is recorded in
  ``transformations``.
* String-literal ROWNUM invariance.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp

from backend.core.transpiler import SQLTranspiler


def _helper(sql: str, target: str = "postgres") -> tuple[exp.Expression, list[str]]:
    """Parse ``sql`` as Oracle and run the helper transform directly."""
    t = SQLTranspiler.__new__(SQLTranspiler)
    ast = sqlglot.parse_one(sql, read="oracle")
    return t._ast_rownum_to_limit(ast, target)


# ---------------------------------------------------------------------------
# Helper-level behavior (no PostProcessor involved)
# ---------------------------------------------------------------------------

ACCEPTED_CASES = [
    ("SELECT * FROM t WHERE ROWNUM <= 5", "ok"),
    ("SELECT a, b FROM t WHERE ROWNUM <= 10", "named-cols"),
    ("SELECT * FROM t WHERE ROWNUM <= 5 AND dept = 1", "companion-and"),
    ("SELECT * FROM t WHERE dept = 1 AND ROWNUM <= 5", "companion-right"),
    ("SELECT * FROM t WHERE a = 1 AND ROWNUM <= 5 AND b = 2", "two-companions"),
]


class TestHelperAcceptCases:
    """Qualifying ROWNUM <= N predicates must be migrated to LIMIT N."""

    def test_bare_rownum_le_migrated(self) -> None:
        ast, notes = _helper("SELECT * FROM t WHERE ROWNUM <= 5")
        assert len(notes) == 1
        assert "LIMIT 5" in ast.sql(dialect="postgres")
        assert "ROWNUM" not in ast.sql(dialect="postgres")

    def test_companion_predicate_preserved(self) -> None:
        ast, notes = _helper("SELECT * FROM t WHERE ROWNUM <= 5 AND dept = 1")
        assert len(notes) == 1
        sql = ast.sql(dialect="postgres")
        assert "dept = 1" in sql
        assert "LIMIT 5" in sql
        assert "ROWNUM" not in sql

    def test_companion_on_right_side(self) -> None:
        ast, notes = _helper("SELECT * FROM t WHERE dept = 1 AND ROWNUM <= 5")
        assert len(notes) == 1
        sql = ast.sql(dialect="postgres")
        assert "dept = 1" in sql
        assert "LIMIT 5" in sql
        assert "ROWNUM" not in sql

    def test_note_text_records_migration(self) -> None:
        _, notes = _helper("SELECT * FROM t WHERE ROWNUM <= 5")
        assert notes == ["ROWNUM <= 5 converted to LIMIT 5 (AST)"]

    def test_each_accepted_case_produces_exactly_one_note(self) -> None:
        for sql, label in ACCEPTED_CASES:
            ast, notes = _helper(sql)
            assert len(notes) == 1, f"{label}: expected 1 note, got {notes}"
            assert "ROWNUM" not in ast.sql(dialect="postgres"), label


REJECTED_CASES = [
    # non->= operators
    ("SELECT * FROM t WHERE ROWNUM = 5", "eq"),
    ("SELECT * FROM t WHERE ROWNUM < 5", "lt"),
    ("SELECT * FROM t WHERE ROWNUM > 5", "gt"),
    ("SELECT * FROM t WHERE 5 >= ROWNUM", "reversed"),
    # string / float bounds
    ("SELECT * FROM t WHERE ROWNUM <= '5'", "string-bound"),
    ("SELECT * FROM t WHERE ROWNUM <= 5.0", "float-bound"),
    # multiple qualifying predicates
    ("SELECT * FROM t WHERE ROWNUM <= 10 AND ROWNUM <= 5", "double-rownum"),
    # OR / ORDER BY / GROUP BY / HAVING / DISTINCT
    ("SELECT * FROM t WHERE ROWNUM <= 5 OR a = 1", "or"),
    ("SELECT * FROM t WHERE ROWNUM <= 5 ORDER BY id", "order-by"),
    ("SELECT * FROM t WHERE ROWNUM <= 5 GROUP BY x", "group-by"),
    ("SELECT * FROM t WHERE ROWNUM <= 5 HAVING x > 1", "having"),
    ("SELECT DISTINCT * FROM t WHERE ROWNUM <= 5", "distinct"),
    # set operations (root is not a single Select)
    ("SELECT * FROM a UNION SELECT * FROM b", "union"),
    ("SELECT * FROM a INTERSECT SELECT * FROM b", "intersect"),
    ("SELECT * FROM a EXCEPT SELECT * FROM b", "except"),
    # no qualifying predicate
    ("SELECT * FROM t WHERE a = 1", "no-pred"),
    ("SELECT * FROM t", "no-where"),
]


class TestHelperRejectCases:
    """Out-of-scope shapes must be left unchanged with no note."""

    def test_each_rejected_case_produces_no_notes(self) -> None:
        for sql, label in REJECTED_CASES:
            ast, notes = _helper(sql)
            assert notes == [], f"{label}: expected no notes, got {notes}"
            out = ast.sql(dialect="postgres")
            assert out == sqlglot.transpile(sql, read="oracle", write="postgres", pretty=False)[0], (
                f"{label}: rejected shape must be unchanged, got {out!r}"
            )

    def test_order_by_rownum_not_converted_to_limit(self) -> None:
        """``ROWNUM <= 5 ORDER BY id`` must be skipped, never rewritten
        to ``ORDER BY id LIMIT 5``."""
        ast, notes = _helper("SELECT * FROM t WHERE ROWNUM <= 5 ORDER BY id")
        assert notes == []
        out = ast.sql(dialect="postgres")
        assert "LIMIT" not in out

    def test_string_literal_rownum_unchanged(self) -> None:
        """ROWNUM appearing inside a string literal must remain intact."""
        sql = "SELECT * FROM t WHERE name = 'ROWNUM'"
        ast, notes = _helper(sql)
        assert notes == []
        out = ast.sql(dialect="postgres")
        assert "'ROWNUM'" in out

    def test_float_bound_not_migrated(self) -> None:
        """``ROWNUM <= 5.0`` must be rejected (legacy corrupted the output)."""
        ast, notes = _helper("SELECT * FROM t WHERE ROWNUM <= 5.0")
        assert notes == []
        assert "LIMIT" not in ast.sql(dialect="postgres")

    def test_double_rownum_not_migrated(self) -> None:
        """Two ROWNUM <= N predicates leave the query unchanged (no residual)."""
        sql = "SELECT * FROM t WHERE ROWNUM <= 10 AND ROWNUM <= 5"
        ast, notes = _helper(sql)
        assert notes == []
        out = ast.sql(dialect="postgres")
        assert "ROWNUM" in out
        assert "LIMIT" not in out


# ---------------------------------------------------------------------------
# Production pipeline tests (SQLTranspiler.transpile)
# ---------------------------------------------------------------------------

SUPPORTED_TARGETS = ["postgres", "mysql", "hive", "spark"]


class TestProductionPipeline:
    """The production transpile() path must record the AST note and
    emit the migrated LIMIT, for each supported target."""

    @classmethod
    def setup_class(cls) -> None:
        cls.t = SQLTranspiler()

    @staticmethod
    def _normalize(sql: str) -> str:
        return " ".join(sql.split())

    @staticmethod
    def _contains(sub: str, hay: str) -> bool:
        return sub in hay

    def test_bare_rownum_migrated_to_postgres(self) -> None:
        r = self.t.transpile("SELECT * FROM t WHERE ROWNUM <= 5", source="oracle", target="postgres")
        assert r.success is True
        assert self._contains("LIMIT 5", self._normalize(r.target_sql))
        assert not self._contains("ROWNUM", r.target_sql.upper())
        assert any("ROWNUM" in note and "LIMIT 5" in note for note in r.transformations)

    def test_companion_predicate_preserved(self) -> None:
        r = self.t.transpile(
            "SELECT * FROM t WHERE ROWNUM <= 5 AND dept = 1",
            source="oracle", target="postgres",
        )
        assert r.success is True
        norm = self._normalize(r.target_sql)
        assert self._contains("dept = 1", norm)
        assert self._contains("LIMIT 5", norm)
        assert not self._contains("ROWNUM", r.target_sql.upper())

    def test_all_supported_targets_fire_the_transform(self) -> None:
        for target in SUPPORTED_TARGETS:
            r = self.t.transpile("SELECT * FROM t WHERE ROWNUM <= 3", source="oracle", target=target)
            assert r.success is True, f"{target}: {r.error}"
            assert self._contains("LIMIT 3", self._normalize(r.target_sql)), target
            assert any("(AST)" in note for note in r.transformations), target

    def test_order_by_rownum_not_migrated(self) -> None:
        r = self.t.transpile("SELECT * FROM t WHERE ROWNUM <= 5 ORDER BY id", source="oracle", target="postgres")
        assert r.success is True
        # The AST path correctly declines ORDER BY; no ROWNUM → LIMIT
        # conversion happens anywhere in the pipeline.
        assert not any("(AST)" in note for note in r.transformations)
        assert "ROWNUM <= 5" in r.target_sql.upper()
        assert "LIMIT 5" not in r.target_sql.upper()

    def test_rejected_shape_leaves_limit_absent(self) -> None:
        r = self.t.transpile("SELECT * FROM t WHERE ROWNUM = 5", source="oracle", target="postgres")
        assert r.success is True
        # The AST path declines (operator is =, not <=); the legacy post-
        # processor also declines (its regex requires <=). No LIMIT is added.
        assert "LIMIT" not in r.target_sql.upper()
        # ROWNUM remains in the output because no AST migration happened.
        assert "ROWNUM" in r.target_sql.upper()
        assert not any("(AST)" in note for note in r.transformations)

    def test_unsupported_target_skips_transform(self) -> None:
        """Targets outside the four-dialect set must not fire the AST path."""
        r = self.t.transpile("SELECT * FROM t WHERE ROWNUM <= 5", source="oracle", target="tsql")
        assert r.success is True
        # tsql is not in the four supported targets; the AST note must be absent.
        assert not any("(AST)" in note for note in r.transformations)

    def test_string_literal_rownum_unchanged_in_pipeline(self) -> None:
        r = self.t.transpile("SELECT * FROM t WHERE name = 'ROWNUM'", source="oracle", target="postgres")
        assert r.success is True
        assert "'ROWNUM'" in r.target_sql
        assert not any("(AST)" in note for note in r.transformations)

class TestFloatBoundaryBehavior:
    """After G6-A2 removed the legacy ROWNUM handler, the float-boundary
    case must pass through the pipeline cleanly:

    * AST transform skips it (float literal is not a bare integer).
    * No post-processor ROWNUM rewriting remains.
    * The target parser gate accepts the unchanged string.
    * The production result is ``success=True`` with the original ROWNUM
      predicate intact.
    """

    @classmethod
    def setup_class(cls) -> None:
        cls.t = SQLTranspiler()

    def test_float_bound_not_migrated_by_ast_path(self) -> None:
        """``ROWNUM <= 5.0`` must not be migrated by the AST path.

        No ``(AST)`` note is recorded because the RHS is a float literal,
        not a bare integer.
        """
        r = self.t.transpile("SELECT * FROM t WHERE ROWNUM <= 5.0", source="oracle", target="postgres")
        assert r.success is True
        assert not any("(AST)" in note for note in r.transformations)

    def test_float_bound_survives_pipeline_unchanged(self) -> None:
        """The float-bound predicate must survive the production pipeline
        intact — no corruption, no stray ``.0`` token, no spurious LIMIT.
        The legacy handler that previously corrupted this case has been
        removed (G6-A2), so the result is a clean pass-through.
        """
        r = self.t.transpile(
            "SELECT * FROM users WHERE ROWNUM <= 5.0",
            source="oracle",
            target="postgres",
            validate=True,
        )
        assert r.success is True, f"float-bound case should now succeed: {r.error}"
        norm = " ".join((r.target_sql or "").split())
        assert "ROWNUM <= 5.0" in norm, f"expected ROWNUM predicate preserved, got {norm!r}"
        assert not any("(AST)" in note for note in r.transformations)
        # No stray '.0' token detached from the ROWNUM predicate.
        assert ".0 LIMIT" not in norm
        assert "LIMIT 5" not in norm


class TestDoubleRownumBehavior:
    """Two ROWNUM <= N predicates are a reject case for the AST path
    (exactly-one-predicate rule). After G6-A2 removed the legacy handler,
    both predicates must survive the pipeline unchanged — the old residual
    ``WHERE ROWNUM <= 5 LIMIT 5`` must not appear.
    """

    @classmethod
    def setup_class(cls) -> None:
        cls.t = SQLTranspiler()

    def test_double_rownum_not_migrated(self) -> None:
        r = self.t.transpile(
            "SELECT * FROM users WHERE ROWNUM <= 5 AND ROWNUM <= 3",
            source="oracle",
            target="postgres",
            validate=True,
        )
        assert r.success is True
        norm = " ".join((r.target_sql or "").split())
        assert "ROWNUM <= 5" in norm, f"expected first predicate preserved, got {norm!r}"
        assert "ROWNUM <= 3" in norm, f"expected second predicate preserved, got {norm!r}"
        assert "LIMIT" not in norm.upper()
        assert not any("(AST)" in note for note in r.transformations)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
