"""B2-1 / B2-1b / B2-1c — STRING_AGG dynamic-separator conversion audit.

Summary of verified behavior after B2-1 + B2-1b + B2-1c:

- A **fixed** string-literal separator converts to a valid, executable
  MySQL ``GROUP_CONCAT(... SEPARATOR '<literal>')`` via both the
  ``rule_engine.apply_rules`` entry point and the production
  ``SQLTranspiler.transpile`` pipeline.  Escape and quote semantics are
  preserved and re-quoted per MySQL's single-quoted-literal rules.
- A **dynamic** separator (function call, CASE expression, ``||`` /
  ``+`` concatenation, or a bare column reference) has no
  semantics-preserving MySQL equivalent — MySQL's ``SEPARATOR str_val``
  slot accepts only a string literal, and pre-computing a constant would
  change per-row semantics.  Both entry points now fail closed instead
  of reporting a successful conversion with unexecutable target SQL:
  * ``rule_engine.apply_rules`` leaves the source call untouched and
    appends ``DYNAMIC_SEPARATOR_FAIL_NOTE`` to the notes.
  * ``SQLTranspiler.transpile`` returns ``success=False`` with
    ``error_code=VALIDATION_FAILED`` when either the rule engine's
    fail-closed note is present OR the transpiled output contains a
    non-Literal ``GROUP_CONCAT`` SEPARATOR (a structural guard, since
    sqlglot's MySQL dialect accepts dynamic SEPARATOR values that real
    MySQL does not).
- **B2-1c** proves that fail-closed behavior does not alter the
  original SQL text: the internal sentinel token used to flag dynamic
  separators is stripped in place before any SQL is returned, so
  multi-line statements, multiple dynamic calls in one statement, and
  trailing text on the call's own line are all preserved exactly.
- **No real MySQL engine is available in this environment.**  All
  "parse-check" results here are sqlglot AST structural checks, which
  are explicitly *not* equivalent to execution on a real MySQL server.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp

import pytest

from backend.core.rules import (
    DYNAMIC_SEPARATOR_FAIL_NOTE,
    rule_engine,
)
from backend.core.transpiler import SQLTranspiler


# Fixed-literal cases
FIXED_CASES = [
    ("SELECT STRING_AGG(name, ',') FROM t", "fixed-literal"),
]
# Dynamic-separator cases: no executable MySQL equivalent exists.
DYNAMIC_CASES = [
    ("SELECT STRING_AGG(name, CONCAT(',', UPPER(x))) FROM t", "dynamic-concat"),
    (
        "SELECT STRING_AGG(name, CASE WHEN z THEN ',' ELSE ';' END) FROM t",
        "dynamic-case",
    ),
    ("SELECT STRING_AGG(name, ',' || UPPER(x)) FROM t", "dynamic-pipe"),
    ("SELECT STRING_AGG(name, ',' + UPPER(x)) FROM t", "dynamic-plus"),
]
SOURCES = ("postgres", "tsql")


def _separator_is_expression(tree: exp.Expression) -> bool:
    """True when any GROUP_CONCAT in the tree has a non-Literal separator."""
    for gc in tree.find_all(exp.GroupConcat):
        sep = gc.args.get("separator")
        if sep is not None and not isinstance(sep, exp.Literal):
            return True
    return False


class TestFixedLiteralSeparator:
    """Fixed literal separators must convert correctly through both paths."""

    @pytest.mark.parametrize("sql,label", FIXED_CASES)
    @pytest.mark.parametrize("source", SOURCES)
    def test_rule_engine_fixed_literal(self, sql, label, source):
        result, notes = rule_engine.apply_rules(sql, source, "mysql")
        assert DYNAMIC_SEPARATOR_FAIL_NOTE not in notes, notes
        tree = sqlglot.parse_one(result, read="mysql")
        assert not _separator_is_expression(tree), (
            f"fixed literal separator must remain a literal, got expression: {result}"
        )

    @pytest.mark.parametrize("sql,label", FIXED_CASES)
    @pytest.mark.parametrize("source", SOURCES)
    def test_transpile_fixed_literal(self, sql, label, source):
        result = SQLTranspiler().transpile(sql, source, "mysql")
        assert result.success is True, result.error
        tree = sqlglot.parse_one(result.target_sql, read="mysql")
        assert not _separator_is_expression(tree), result.target_sql


class TestDynamicSeparatorRuleEngineFailsClosed:
    """The rule-engine path must fail closed for every dynamic-separator form.

    The source call is left untouched and a fail-closed note is appended.
    No dynamic separator is silently rewritten into a string literal.
    """

    @pytest.mark.parametrize("sql,label", DYNAMIC_CASES)
    @pytest.mark.parametrize("source", SOURCES)
    def test_rule_engine_dynamic_separator_fail_closed(
        self, sql, label, source
    ):
        result, notes = rule_engine.apply_rules(sql, source, "mysql")
        assert DYNAMIC_SEPARATOR_FAIL_NOTE in notes, (
            f"dynamic separator ({label}) must produce a fail-closed note, "
            f"got notes: {notes}"
        )
        # The rewriter must not have collapsed the dynamic separator into
        # a GROUP_CONCAT SEPARATOR string literal: the source call stays
        # untouched and no GROUP_CONCAT appears where none was in source.
        assert "GROUP_CONCAT" not in result.upper() or "STRING_AGG" in result.upper(), (
            f"dynamic separator was silently rewritten to GROUP_CONCAT: {result}"
        )


class TestDynamicSeparatorTranspileFailsClosed:
    """The production transpile path must fail closed for dynamic separators.

    sqlglot's MySQL dialect is more permissive than real MySQL: it accepts
    dynamic expressions in the GROUP_CONCAT SEPARATOR slot.  The structural
    guard in SQLTranspiler (``_group_concat_dynamic_separator``) catches
    this and forces a fail-closed result rather than reporting success with
    unexecutable target SQL.
    """

    @pytest.mark.parametrize("sql,label", DYNAMIC_CASES)
    @pytest.mark.parametrize("source", SOURCES)
    def test_transpile_dynamic_separator_fail_closed(self, sql, label, source):
        result = SQLTranspiler().transpile(sql, source, "mysql")
        assert result.success is False, (
            f"dynamic separator ({label}) must fail closed, "
            f"got success=True target={result.target_sql!r}"
        )
        assert result.error_code == "VALIDATION_FAILED", result.error_code


class TestDynamicSeparatorTranspileDoesNotFalsePositiveOnValidMySQL:
    """The structural guard must not flag valid fixed-literal GROUP_CONCAT
    output as unsupported — only genuinely dynamic separators trigger it."""

    @pytest.mark.parametrize("sql", [
        "SELECT STRING_AGG(name, ',') FROM t",
        "SELECT STRING_AGG(name, ';') FROM t",
    ])
    @pytest.mark.parametrize("source", SOURCES)
    def test_fixed_literals_do_not_trigger_guard(self, sql, source):
        result = SQLTranspiler().transpile(sql, source, "mysql")
        assert result.success is True, (
            f"fixed-literal separator must still succeed: {result.error}"
        )
        # Confirm the structural guard itself does not fire on valid output.
        transpiler = SQLTranspiler()
        guard = transpiler._group_concat_dynamic_separator(result.target_sql)
        assert guard is False, (
            f"structural guard must not fire on valid literal separator: "
            f"{result.target_sql}"
        )


class TestLiteralFidelity:
    """Double-quoted and escaped-quote arguments must be interpreted per
    source dialect with escape/content semantics preserved.

    In PostgreSQL/Oracle double quotes mark IDENTIFIERS, not string
    literals — so a double-quoted separator in Postgres is a dynamic
    (identifier-based) expression and must fail closed.  In T-SQL double
    quotes mark string literals, so a double-quoted separator in T-SQL
    is a valid fixed literal.
    """

    @pytest.mark.parametrize(
        "sql,source,expect_fail_closed",
        [
            ('SELECT STRING_AGG(name, "separator_col") FROM t', "postgres", True),
            ('SELECT STRING_AGG(name, "foo") FROM t', "postgres", True),
            ('SELECT STRING_AGG(name, "foo") FROM t', "tsql", False),
        ],
    )
    def test_double_quote_interpretation(self, sql, source, expect_fail_closed):
        result, notes = rule_engine.apply_rules(sql, source, "mysql")
        is_fail_closed = DYNAMIC_SEPARATOR_FAIL_NOTE in notes
        assert is_fail_closed == expect_fail_closed, (
            f"{source} double-quoted separator: expected "
            f"{'fail-closed' if expect_fail_closed else 'success'}, "
            f"got fail_closed={is_fail_closed} result={result!r}"
        )

    def test_escaped_single_quote_literal_preserved(self):
        """PostgreSQL's doubled-quote escape must normalize to MySQL's
        backslash-escape without changing the literal's content."""
        result, notes = rule_engine.apply_rules(
            "SELECT STRING_AGG(name, 'a''b') FROM t", "postgres", "mysql"
        )
        assert DYNAMIC_SEPARATOR_FAIL_NOTE not in notes
        tree = sqlglot.parse_one(result, read="mysql")
        gc = tree.find(exp.GroupConcat)
        sep = gc.args.get("separator")
        assert isinstance(sep, exp.Literal), result
        # The literal's VALUE must be a'b — escape form may differ per
        # dialect, but the content must survive.
        assert sep.this == "a'b", f"literal content mangled: {sep.this!r}"

    def test_escaped_double_quote_literal_preserved_tsql(self):
        result, notes = rule_engine.apply_rules(
            'SELECT STRING_AGG(name, "a""b") FROM t', "tsql", "mysql"
        )
        assert DYNAMIC_SEPARATOR_FAIL_NOTE not in notes
        tree = sqlglot.parse_one(result, read="mysql")
        gc = tree.find(exp.GroupConcat)
        sep = gc.args.get("separator")
        assert isinstance(sep, exp.Literal), result
        assert sep.this == 'a"b', f"literal content mangled: {sep.this!r}"


class TestB2_1C_OriginalTextPreservedOnFailClosed:
    """B2-1c: when a dynamic separator triggers fail-closed, the SQL text
    returned by the rule engine must be byte-identical to the input
    (no text lost, no text added, no line-boundary dependence).

    The old B2-1b implementation appended a marker *comment line* after
    the call and then deleted the entire line containing it — which
    consumed any trailing SQL text on the same line and, for multi-line
    statements, swallowed content after the marker's own line.  The
    B2-1c sentinel-token mechanism fixes this: the token is an exact
    substring stripped in place, with no lexical side effects.

    These tests assert on the raw returned string, not on sqlglot AST
    shape, so they specifically guard against text truncation.
    """

    # (input_sql, source_dialect)
    PRESERVATION_CASES = [
        # Single-line, trailing text after the call on the same line
        (
            "SELECT STRING_AGG(name, CONCAT(',', UPPER(x))) AS s, id FROM t WHERE id > 10",
            "postgres",
        ),
        # Multi-line statement with WHERE and GROUP BY
        (
            "SELECT STRING_AGG(name, CASE WHEN z THEN ',' ELSE ';' END)\n"
            "FROM t\nWHERE active = 1\nGROUP BY category",
            "postgres",
        ),
        # Two aggregate expressions, only the first is dynamic
        (
            "SELECT STRING_AGG(a, CONCAT(',', x)), COUNT(*)\nFROM t\nWHERE id > 10",
            "postgres",
        ),
        # Two dynamic STRING_AGG calls in one statement
        (
            "SELECT STRING_AGG(name, CONCAT(',', UPPER(x))), "
            "STRING_AGG(val, CASE WHEN z THEN ',' ELSE ';' END) FROM t",
            "postgres",
        ),
        # T-SQL with pipe operator (also dynamic, also multi-line)
        (
            "SELECT STRING_AGG(name, ',' + UPPER(x)) AS s, id\nFROM t\nWHERE id > 10",
            "tsql",
        ),
    ]

    @pytest.mark.parametrize("sql,source", PRESERVATION_CASES)
    def test_returned_sql_is_byte_identical_to_input(self, sql, source):
        result, notes = rule_engine.apply_rules(sql, source, "mysql")
        # The returned SQL must equal the input exactly — no text lost,
        # no text added, no whitespace normalization.
        assert result == sql, (
            f"fail-closed SQL altered the original text.\n"
            f"input : {sql!r}\n"
            f"output: {result!r}"
        )
        # And the fail-closed note must still be present.
        assert DYNAMIC_SEPARATOR_FAIL_NOTE in notes, (
            f"original text preserved but fail-closed note missing: {notes}"
        )

    def test_no_internal_sentinel_leaks_to_caller(self):
        """The internal sentinel token must never appear in returned SQL."""
        from backend.core.rules import _DYNAMIC_SEPARATOR_SENTINEL
        sql = "SELECT STRING_AGG(name, CONCAT(',', UPPER(x))) FROM t"
        result, _ = rule_engine.apply_rules(sql, "postgres", "mysql")
        assert _DYNAMIC_SEPARATOR_SENTINEL not in result, (
            f"internal sentinel token leaked to caller: {result!r}"
        )

    def test_transpile_path_also_preserves_original_on_fail_closed(self):
        """SQLTranspiler.transpile's error message must not embed the
        sentinel token either."""
        from backend.core.rules import _DYNAMIC_SEPARATOR_SENTINEL
        sql = "SELECT STRING_AGG(name, CONCAT(',', UPPER(x))) AS s, id FROM t WHERE id > 10"
        result = SQLTranspiler().transpile(sql, "postgres", "mysql")
        assert result.success is False, "dynamic separator must fail closed"
        assert _DYNAMIC_SEPARATOR_SENTINEL not in (result.error or ""), (
            f"sentinel leaked into error message: {result.error!r}"
        )


if __name__ == "__main__":
    import subprocess, sys
    print(subprocess.check_output(
        [sys.executable, "-m", "pytest", __file__, "-v", "-p", "no:cacheprovider"],
        text=True,
    ))
