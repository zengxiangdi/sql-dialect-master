"""B3-2 — Parser function-argument-count metadata contract.

The parser counted ``len(func.args)`` — the number of AST *fields* on
the sqlglot node — which is not the number of actual operands:
``COUNT(*)`` reported 3 (this + expressions + big_int) and
``COALESCE(a, b, c)`` reported 4 (this + expressions + is_nvl +
is_null).  The contract is now: the number of real expression operands
the call carries (primary ``this`` operand when it is an expression,
plus variadic ``expressions`` items), ignoring the function name and
non-expression metadata.
"""
from __future__ import annotations

import pytest

from backend.core.parser import SQLParser


@pytest.fixture
def parser():
    return SQLParser(dialect="postgres")


def _arg_counts(parser: SQLParser, sql: str) -> list[tuple[str, int]]:
    result = parser.parse(sql)
    assert result.success is True, result.error
    return [(f["name"], f["args_count"]) for f in result.functions]


class TestB3_2_ArgCounts:
    @pytest.mark.parametrize(
        "sql,expected",
        [
            # (sql, [(function_name, actual_operand_count), ...])
            ("SELECT UPPER(x) FROM t", [("UPPER", 1)]),
            ("SELECT COUNT(*) FROM t", [("COUNT", 1)]),
            ("SELECT COUNT() FROM t", [("COUNT", 0)]),
            ("SELECT COUNT(DISTINCT x) FROM t", [("COUNT", 1)]),
            ("SELECT COALESCE(a, b, c) FROM t", [("COALESCE", 3)]),
            ("SELECT SUM(x) FROM t", [("SUM", 1)]),
            (
                "SELECT SUBSTRING(x FROM 1 FOR 2) FROM t",
                [("SUBSTRING", 3)],
            ),
            ("SELECT FOO(a, b) FROM t", [("ANONYMOUS", 2)]),
            (
                "SELECT ROW_NUMBER() OVER (ORDER BY x) FROM t",
                [("ROW_NUMBER", 0)],
            ),
            ("SELECT UPPER(LOWER(x)) FROM t", [("UPPER", 1), ("LOWER", 1)]),
            # The parser de-duplicates by function name; the outer call
            # carries the inner call plus one literal operand.
            ("SELECT COALESCE(COALESCE(a, b), c) FROM t",
             [("COALESCE", 2)]),
            ("SELECT CONCAT(a, b, c) FROM t", [("CONCAT", 3)]),
        ],
    )
    def test_actual_operand_count(self, parser, sql, expected):
        counts = _arg_counts(parser, sql)
        assert counts == expected, f"{sql!r}: {counts!r} != {expected!r}"

    def test_star_is_one_operand_not_three(self, parser):
        counts = _arg_counts(parser, "SELECT COUNT(*) FROM t")
        assert counts == [("COUNT", 1)]

    def test_no_args_is_zero_not_three(self, parser):
        counts = _arg_counts(parser, "SELECT COUNT() FROM t")
        assert counts == [("COUNT", 0)]

    def test_aggregate_with_distinct_is_one_operand(self, parser):
        counts = _arg_counts(parser, "SELECT SUM(DISTINCT x) FROM t")
        assert counts == [("SUM", 1)]
