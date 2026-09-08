"""Translate SQL WHERE expressions into the dialect-neutral NL2SQL Semantic IR.

This adapter intentionally parses the SQL expression produced by the existing
NL2SQL condition extractor. It lets the project introduce structured semantics
without changing the existing generation path yet.
"""
from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot import exp

from .semantic_ir import (
    And,
    BooleanExpression,
    ComparisonPredicate,
    Not,
    NullPredicate,
    Or,
    RangePredicate,
    SetPredicate,
    TextPredicate,
)


_COMPARISON_TYPES = {
    exp.EQ: "=",
    exp.NEQ: "!=",
    exp.GT: ">",
    exp.GTE: ">=",
    exp.LT: "<",
    exp.LTE: "<=",
}


def _literal_value(node: exp.Expression) -> Any:
    """Convert common sqlglot literal nodes to native Python values."""
    if isinstance(node, exp.Literal):
        if node.is_string:
            return node.this
        try:
            return int(node.this)
        except (TypeError, ValueError):
            try:
                return float(node.this)
            except (TypeError, ValueError):
                return node.this
    if isinstance(node, exp.Null):
        return None
    return node.sql()


def _column_name(node: exp.Expression) -> str:
    """Return a normalized column name and reject non-column predicates."""
    if not isinstance(node, exp.Column):
        raise ValueError(f"Expected column expression, got {type(node).__name__}")
    return node.sql()


def _convert(node: exp.Expression) -> BooleanExpression:
    if isinstance(node, exp.Paren):
        return _convert(node.this)

    if isinstance(node, exp.And):
        return And(operands=(_convert(node.this), _convert(node.expression)))

    if isinstance(node, exp.Or):
        return Or(operands=(_convert(node.this), _convert(node.expression)))

    if isinstance(node, exp.Not):
        return Not(operand=_convert(node.this))

    for node_type, operator in _COMPARISON_TYPES.items():
        if isinstance(node, node_type):
            return ComparisonPredicate(
                field=_column_name(node.this),
                operator=operator,
                value=_literal_value(node.expression),
            )

    if isinstance(node, exp.Between):
        return RangePredicate(
            field=_column_name(node.this),
            lower=_literal_value(node.args["low"]),
            upper=_literal_value(node.args["high"]),
        )

    if isinstance(node, exp.Like):
        pattern = _literal_value(node.expression)
        if not isinstance(pattern, str):
            raise ValueError("LIKE pattern must be a string literal")
        value = pattern[1:-1] if len(pattern) >= 2 and pattern.startswith("%") and pattern.endswith("%") else pattern
        return TextPredicate(field=_column_name(node.this), operator="contains", value=value)

    if isinstance(node, exp.Is):
        value = node.expression
        if not isinstance(value, exp.Null):
            raise ValueError("Only IS NULL / IS NOT NULL are supported")
        return NullPredicate(
            field=_column_name(node.this),
            is_null=" IS NOT NULL" not in f" {node.sql().upper()}",
        )

    if isinstance(node, exp.In):
        values = tuple(_literal_value(item) for item in node.expressions)
        return SetPredicate(
            field=_column_name(node.this),
            operator="not_in" if bool(node.args.get("not")) else "in",
            values=values,
        )

    raise ValueError(f"Unsupported semantic expression: {type(node).__name__}")


def parse_condition_expression(expression: str, dialect: str = "postgres") -> BooleanExpression:
    """Parse a boolean SQL expression into Semantic IR.

    Args:
        expression: WHERE expression without the ``WHERE`` keyword.
        dialect: sqlglot dialect used to parse the expression.

    Raises:
        ValueError: If the expression cannot be represented by the current IR.
    """
    if not expression or not expression.strip():
        raise ValueError("Condition expression is empty")

    try:
        tree = sqlglot.parse_one(
            f"SELECT * FROM __semantic_ir__ WHERE {expression}",
            read=dialect,
        )
    except Exception as exc:
        raise ValueError(f"Invalid condition expression: {exc}") from exc

    where = tree.find(exp.Where)
    if where is None or where.this is None:
        raise ValueError("No WHERE expression found")
    return _convert(where.this)


def parse_condition_list(conditions: list[str], dialect: str = "postgres") -> BooleanExpression | None:
    """Parse the first boolean expression from an extracted condition list."""
    if not conditions:
        return None
    if len(conditions) != 1:
        raise ValueError("Expected one combined boolean condition expression")
    return parse_condition_expression(conditions[0], dialect=dialect)


__all__ = ["parse_condition_expression", "parse_condition_list"]
