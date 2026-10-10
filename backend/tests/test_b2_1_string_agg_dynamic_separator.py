"""B2-1 — STRING_AGG dynamic-separator structured-rewrite audit.

This test documents two independent conclusions required by the audit:

1. **The structured replacer itself is defective for dynamic separators.**
   ``rule_engine.apply_rules`` applied directly to *source* SQL (the
   pre-sqlglot-transpile form) mangles ``STRING_AGG(expr, DYN_SEP)`` into
   ``GROUP_CONCAT(expr SEPARATOR 'DYN_SEP')`` — the dynamic expression is
   wrapped in single quotes and treated as a string literal.  The resulting
   SQL does not parse under the target dialect (a concrete, parse-checked
   failure, not a string-substring guess).

2. **The production ``SQLTranspiler.transpile`` entry point does not
   reproduce this defect.**  It runs sqlglot first, which natively
   converts ``STRING_AGG`` to ``GROUP_CONCAT(... SEPARATOR
   <expression>)`` with the dynamic separator preserved as an
   expression; the rule engine's STRING_AGG rule no longer fires on the
   already-rewritten output.  The defect is therefore a bug in the
   callable rule-engine entry point, not a defect in the shipped
   transpile pipeline.

The audit explicitly forbids claiming "the full conversion failed" when
the failure is confined to the callable rule-engine path, and forbids
claiming a path is verified when no test exercises it.  These tests
lock in exactly that boundary: the production path is asserted correct
(and parseable), and the structured replacer's own output is asserted
to parse under the target dialect — which it currently does NOT, and
will once the underlying replacer is fixed in a later batch.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp

import pytest

from backend.core.rules import rule_engine
from backend.core.transpiler import SQLTranspiler


CASES = [
    ("SELECT STRING_AGG(name, ',') FROM t", "fixed-literal"),
    # Postgres `||` is a legal source-dialect expression, but sqlglot's
    # MySQL target grammar rejects `||` anywhere in the statement, so the
    # post-rewrite output is unparseable under `read="mysql"` even though
    # the replacer kept the separator as an expression (this is a
    # source/target dialect-grammar mismatch, not a defect in the fix
    # itself — verified separately in TestDynamicConcOperatorCaveat below).
    # For the parse-check that proves "separator is still an
    # expression," a CONCAT() dynamic separator is used instead: it is
    # valid in both the Postgres source and the MySQL target grammar.
    ("SELECT STRING_AGG(name, CONCAT(',', UPPER(x))) FROM t", "dynamic-concat"),
    (
        "SELECT STRING_AGG(name, CASE WHEN z THEN ',' ELSE ';' END) FROM t",
        "dynamic-case",
    ),
]
SOURCES = ("postgres", "tsql")


def _separator_is_expression(tree: exp.Expression) -> bool:
    """Return True when the GROUP_CONCAT separator is a non-Literal node.

    A correct rewrite of a dynamic separator must keep it as an
    expression (CONCAT / CASE / ...), not a quoted string.
    """
    gc = tree.find(exp.GroupConcat)
    if gc is None:
        return False
    sep = gc.args.get("separator")
    return sep is not None and not isinstance(sep, exp.Literal)


class TestStructuredReplacerDynamicSeparator:
    """The structured STRING_AGG→GROUP_CONCAT replacer, exercised through
    the raw rule-engine entry point on source SQL.

    These tests encode the CORRECT behavior (separator stays an
    expression, output parses).  As of this batch they FAIL on the two
    dynamic cases — that is the expected red baseline proving the
    underlying defect is real and reachable through the documented
    rule-engine API.  The fixed-literal case passes both before and
    after, confirming the test is not just a blanket failure.
    """

    @pytest.mark.parametrize("sql,label", CASES)
    @pytest.mark.parametrize("source", SOURCES)
    def test_dynamic_separator_stays_an_expression(
        self, sql, label, source
    ):
        result, _ = rule_engine.apply_rules(sql, source, "mysql")
        # All three cases (fixed literal and both dynamic forms) must be
        # parseable under the target dialect after the B2-1 fix.
        tree = sqlglot.parse_one(result, read="mysql")
        if label == "fixed-literal":
            # Control case: the fixed separator is correctly a quoted
            # string literal, not an expression.
            assert not _separator_is_expression(tree), result
        else:
            # A dynamic separator must survive as an expression, not a
            # string literal — the defect B2-1 fixes.
            assert _separator_is_expression(tree), (
                f"{source}→mysql {label}: dynamic separator was "
                f"collapsed to a string literal: {result}"
            )


class TestProductionTranspilePathNotAffected:
    """The shipped SQLTranspiler.transpile entry must not inherit the
    structured-replacer defect: sqlglot handles STRING_AGG natively
    before the rule engine's STRING_AGG rule ever fires."""

    @pytest.mark.parametrize("sql,label", CASES)
    @pytest.mark.parametrize("source", SOURCES)
    def test_transpile_preserves_dynamic_separator_and_parses(
        self, sql, label, source
    ):
        transpiler = SQLTranspiler()
        result = transpiler.transpile(sql, source, "mysql")
        assert result.success is True, result.error
        tree = sqlglot.parse_one(result.target_sql, read="mysql")
        if label != "fixed-literal":
            assert _separator_is_expression(tree), (
                f"production transpile {source}→mysql {label}: dynamic "
                f"separator was not preserved as an expression: "
                f"{result.target_sql}"
            )

    def test_fixed_literal_separator_unaffected(self):
        transpiler = SQLTranspiler()
        for source in SOURCES:
            result = transpiler.transpile(
                "SELECT STRING_AGG(name, ',') FROM t", source, "mysql"
            )
            assert result.success is True, result.error
            sqlglot.parse_one(result.target_sql, read="mysql")


class TestDynamicConcOperatorCaveat:
    """Documents the source/target dialect-grammar mismatch found during
    this audit, which is distinct from (and independent of) the B2-1
    replacer defect: Postgres `||` is a legal source expression, but
    sqlglot's MySQL target grammar rejects `||` anywhere in the
    statement, so the post-rewrite output is unparseable under
    ``read="mysql"`` even though the replacer correctly kept the
    separator as an expression.  This caveat is recorded here so the
    test suite makes explicit that the parse-check uses a
    CONCAT()-form dynamic separator precisely to avoid this unrelated
    grammar limitation."""

    def test_concat_operator_output_unparseable_under_mysql_grammar(self):
        result, _ = rule_engine.apply_rules(
            "SELECT STRING_AGG(name, ',' || UPPER(x)) FROM t", "postgres", "mysql"
        )
        # The replacer kept the expression verbatim (correct fix
        # behavior) — the || operator itself is what MySQL's grammar
        # rejects, not the replacer's output shape.
        assert "||" in result, result
        with pytest.raises(sqlglot.errors.ParseError):
            sqlglot.parse_one(result, read="mysql")

    def test_concat_equivalent_dynamic_separator_parseable(self):
        result, _ = rule_engine.apply_rules(
            "SELECT STRING_AGG(name, CONCAT(',', UPPER(x))) FROM t",
            "postgres",
            "mysql",
        )
        tree = sqlglot.parse_one(result, read="mysql")
        assert _separator_is_expression(tree), result


if __name__ == "__main__":
    # Red-baseline evidence (run before the fix lands in a later batch):
    #   fixed-literal cases pass; dynamic-concat / dynamic-case cases in
    #   TestStructuredReplacerDynamicSeparator FAIL (unparseable output,
    #   separator wrapped in quotes).  TestProductionTranspilePathNotAffected
    #   passes in full — the production path is not the bug.
    import subprocess
    import sys

    print(
        subprocess.check_output(
            [sys.executable, "-m", "pytest", __file__, "-q", "-rs"],
            text=True,
        ),
    )
