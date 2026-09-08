"""Generate sqlglot SQL ASTs from the NL2SQL Semantic IR."""
from __future__ import annotations

from typing import Any

from sqlglot import exp

from .schema_context import SchemaContext, SchemaTable
from .semantic_ir import (
    And,
    BooleanExpression,
    ComparisonPredicate,
    Not,
    NullPredicate,
    Or,
    RangePredicate,
    SemanticQuery,
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


def _column(field: str, schema: SchemaContext | None = None) -> exp.Column:
    """Build a column expression, optionally resolving it through schema metadata."""
    if not field or not field.strip():
        raise ValueError("Semantic field cannot be empty")
    requested = field.strip()
    if schema is None:
        return exp.column(requested)

    if "." in requested:
        table_name, column_name = requested.rsplit(".", 1)
        schema_table, schema_column = schema.resolve_column(column_name, table_name)
        return exp.column(
            schema_column.alias or schema_column.name,
            table=schema_table.alias or schema_table.name,
        )

    schema_table, schema_column = schema.resolve_column(requested)
    return exp.column(
        schema_column.alias or schema_column.name,
        table=schema_table.alias or schema_table.name,
    )


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


def _build(predicate: BooleanExpression, schema: SchemaContext | None = None) -> exp.Expression:
    if isinstance(predicate, ComparisonPredicate):
        expression_type = _COMPARISON_EXPRESSIONS[predicate.operator]
        return expression_type(
            this=_column(predicate.field, schema),
            expression=_literal(predicate.value),
        )

    if isinstance(predicate, RangePredicate):
        if not predicate.inclusive_lower or not predicate.inclusive_upper:
            lower = _COMPARISON_EXPRESSIONS[
                ">=" if predicate.inclusive_lower else ">"
            ](
                this=_column(predicate.field, schema),
                expression=_literal(predicate.lower),
            )
            upper = _COMPARISON_EXPRESSIONS[
                "<=" if predicate.inclusive_upper else "<"
            ](
                this=_column(predicate.field, schema),
                expression=_literal(predicate.upper),
            )
            return exp.And(this=lower, expression=upper)
        return exp.Between(
            this=_column(predicate.field, schema),
            low=_literal(predicate.lower),
            high=_literal(predicate.upper),
        )

    if isinstance(predicate, TextPredicate):
        pattern = exp.Literal.string(f"%{predicate.value}%")
        like = exp.Like(this=_column(predicate.field, schema), expression=pattern)
        return exp.Not(this=like) if predicate.operator == "not_contains" else like

    if isinstance(predicate, NullPredicate):
        is_null = exp.Is(this=_column(predicate.field, schema), expression=exp.Null())
        return exp.Not(this=is_null) if not predicate.is_null else is_null

    if isinstance(predicate, SetPredicate):
        values = [_literal(value) for value in predicate.values]
        membership = exp.In(this=_column(predicate.field, schema), expressions=values)
        return exp.Not(this=membership) if predicate.operator == "not_in" else membership

    if isinstance(predicate, And):
        return _fold_boolean(exp.And, predicate.operands, schema)

    if isinstance(predicate, Or):
        return _fold_boolean(exp.Or, predicate.operands, schema)

    if isinstance(predicate, Not):
        return exp.Not(this=_build(predicate.operand, schema))

    raise ValueError(f"Unsupported semantic expression: {type(predicate).__name__}")


def _fold_boolean(
    expression_type: type[exp.Expression],
    operands: tuple[BooleanExpression, ...],
    schema: SchemaContext | None = None,
) -> exp.Expression:
    """Fold N operands into the binary boolean AST used by sqlglot."""
    if len(operands) < 2:
        raise ValueError(f"{expression_type.__name__} requires at least two operands")
    result = _build(operands[0], schema)
    for operand in operands[1:]:
        result = expression_type(this=result, expression=_build(operand, schema))
    return result


def build_condition_ast(
    expression: BooleanExpression,
    schema: SchemaContext | None = None,
) -> exp.Expression:
    """Convert Semantic IR into a sqlglot expression tree."""
    return _build(expression, schema)


def build_select_ast(
    table: str,
    select_fields: tuple[str, ...] = (),
    where: BooleanExpression | None = None,
    schema: SchemaContext | None = None,
) -> exp.Select:
    """Build a complete SELECT AST, resolving identifiers through optional schema metadata."""
    if not table or not table.strip():
        raise ValueError("Semantic table cannot be empty")

    requested_table = table.strip()
    schema_table: SchemaTable | None = schema.resolve_table(requested_table) if schema else None
    source_name = schema_table.name if schema_table else requested_table
    source_alias = schema_table.alias if schema_table else None
    from_source = exp.Table(this=exp.Identifier(this=source_name, quoted=False))
    if source_alias:
        from_source = from_source.as_(source_alias)

    if select_fields:
        projection = [_column(field, schema) for field in select_fields]
    else:
        projection = [
            exp.Star(
                this=exp.Identifier(
                    this=schema_table.alias or schema_table.name
                )
            )
            if schema
            else exp.Star()
        ]

    # Use sqlglot's FROM builder instead of manually mutating Select.args;
    # this keeps the source attached to the canonical AST slot.
    query = exp.select(*projection).from_(from_source)
    if where is not None:
        query = query.where(build_condition_ast(where, schema))
    return query


def build_query_ast(
    query: SemanticQuery,
    schema: SchemaContext,
) -> exp.Select:
    """Build a query AST from a SemanticQuery and an explicit schema context."""
    if not query.table:
        raise ValueError("Semantic query table is required")
    return build_select_ast(
        query.table,
        query.select_fields,
        query.where,
        schema,
    )


__all__ = ["build_condition_ast", "build_query_ast", "build_select_ast"]
