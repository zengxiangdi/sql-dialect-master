"""Generate sqlglot SQL ASTs from the NL2SQL Semantic IR.

This module is deliberately independent from the existing string-based SQL
builder. It provides the first AST-native generation path while keeping the
legacy generator available during migration.
"""
from __future__ import annotations

from typing import Any

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


_COMPARISON_EXPRESSIONS = {
    "=": exp.EQ,
    "!=": exp.NEQ,
    ">": exp.GT,
    ">=": exp.GTE,
    "<": exp.LT,
    "<=": exp.LTE,
}


def _column(field: str) -> exp.Column:
    """Build a column expression from a semantic field reference."""
    if not field or not field.strip():
        raise ValueError("Semantic field cannot be empty")
    return exp.column(field.strip())


def _literal(value: Any) -> exp.Expression:
    """Build a sqlglot literal from a native semantic value."""
    if value is None:
        return exp.Null()
    if isinstance(value, bool):
        return exp.Boolean(this=value)
    if isinstance(value, (int, float)):
        return exp.Literal.number(value)
    if isinstance(value, str):
        return exp.Literal.string(value)
    raise ValueError(f"Unsupported semantic literal type: {type(value).__name__}")


def _build(predicate: BooleanExpression) -> exp.Expression:
    if isinstance(predicate, ComparisonPredicate):
        expression_type = _COMPARISON_EXPRESSIONS[predicate.operator]
        return expression_type(this=_column(predicate.field), expression=_literal(predicate.value))

    if isinstance(predicate, RangePredicate):
        if not predicate.inclusive_lower or not predicate.inclusive_upper:
            lower = _COMPARISON_EXPRESSIONS[">=" if predicate.inclusive_lower else ">"](
                this=_column(predicate.field), expression=_literal(predicate.lower)
            )
            upper = _COMPARISON_EXPRESSIONS["<=" if predicate.inclusive_upper else "<"](
                this=_column(predicate.field), expression=_literal(predicate.upper)
            )
            return exp.And(this=lower, expression=upper)
        return exp.Between(
            this=_column(predicate.field),
            low=_literal(predicate.lower),
            high=_literal(predicate.upper),
        )

    if isinstance(predicate, TextPredicate):
        pattern = exp.Literal.string(f"%{predicate.value}%")
        like = exp.Like(this=_column(predicate.field), expression=pattern)
        return exp.Not(this=like) if predicate.operator == "not_contains" else like

    if isinstance(predicate, NullPredicate):
        is_null = exp.Is(this=_column(predicate.field), expression=exp.Null())
        return exp.Not(this=is_null) if not predicate.is_null else is_null

    if isinstance(predicate, SetPredicate):
        values = [_literal(value) for value in predicate.values]
        membership = exp.In(this=_column(predicate.field), expressions=values)
        return exp.Not(this=membership) if predicate.operator == "not_in" else membership

    if isinstance(predicate, And):
        return _fold_boolean(exp.And, predicate.operands)

    if isinstance(predicate, Or):
        return _fold_boolean(exp.Or, predicate.operands)

    if isinstance(predicate, Not):
        return exp.Not(this=_build(predicate.operand))

    raise ValueError(f"Unsupported semantic expression: {type(predicate).__name__}")


def _fold_boolean(expression_type: type[exp.Expression], operands: tuple[BooleanExpression, ...]) -> exp.Expression:
    """Fold N operands into the binary boolean AST used by sqlglot."""
    if len(operands) < 2:
        raise ValueError(f"{expression_type.__name__} requires at least two operands")
    result = _build(operands[0])
    for operand in operands[1:]:
        result = expression_type(this=result, expression=_build(operand))
    return result


def build_condition_ast(expression: BooleanExpression) -> exp.Expression:
    """Convert Semantic IR into a sqlglot expression tree."""
    return _build(expression)


def build_select_ast(
    table: str,
    select_fields: tuple[str, ...] = (),
    where: BooleanExpression | None = None,
) -> exp.Select:
    """Build a complete SELECT AST from minimal semantic query components."""
    if not table or not table.strip():
        raise ValueError("Semantic table cannot be empty")

    projection = [exp.column(field) for field in select_fields] if select_fields else [exp.Star()]
    query = exp.select(*projection).from_(table.strip())
    if where is not None:
        query = query.where(build_condition_ast(where))
    return query


__all__ = ["build_condition_ast", "build_select_ast"]
