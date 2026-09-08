"""Tests for Semantic IR to sqlglot AST generation."""

import sqlglot
from sqlglot import exp
import pytest

from backend.core.semantic_ir import (
    And,
    ComparisonPredicate,
    Not,
    NullPredicate,
    Or,
    RangePredicate,
    SemanticQuery,
    SetPredicate,
    TextPredicate,
)
from backend.core.semantic_sql import build_condition_ast, build_select_ast


def test_build_comparison_ast():
    tree = build_condition_ast(
        ComparisonPredicate(field="age", operator=">", value=18)
    )

    assert isinstance(tree, exp.GT)
    assert tree.this.name == "age"
    assert tree.expression.this == "18"


def test_build_nested_boolean_ast_preserves_structure():
    tree = build_condition_ast(
        And(
            operands=(
                ComparisonPredicate(field="age", operator=">", value=18),
                Or(
                    operands=(
                        ComparisonPredicate(field="status", operator="=", value="active"),
                        SetPredicate(field="category", operator="in", values=("A", "B")),
                    )
                ),
            )
        )
    )

    assert isinstance(tree, exp.And)
    assert isinstance(tree.expression, exp.Or)
    assert isinstance(tree.this, exp.GT)
    assert isinstance(tree.expression.this, exp.EQ)
    assert isinstance(tree.expression.expression, exp.In)


def test_build_not_in_and_not_null_ast():
    not_in = build_condition_ast(
        SetPredicate(field="status", operator="not_in", values=("inactive", "deleted"))
    )
    assert isinstance(not_in, exp.Not)
    assert isinstance(not_in.this, exp.In)

    not_null = build_condition_ast(NullPredicate(field="deleted_at", is_null=False))
    assert isinstance(not_null, exp.Not)
    assert isinstance(not_null.this, exp.Is)


def test_build_range_and_text_ast():
    between = build_condition_ast(RangePredicate(field="price", lower=10, upper=20))
    assert isinstance(between, exp.Between)

    contains = build_condition_ast(TextPredicate(field="name", operator="contains", value="alice"))
    assert isinstance(contains, exp.Like)
    assert contains.expression.this == "%alice%"


def test_build_select_ast_is_valid_sqlglot_tree():
    semantic = SemanticQuery(
        table="users",
        select_fields=("id", "name"),
        where=And(
            operands=(
                ComparisonPredicate(field="age", operator=">=", value=18),
                NullPredicate(field="deleted_at", is_null=True),
            )
        ),
    )
    tree = build_select_ast(
        semantic.table,
        semantic.select_fields,
        semantic.where,
    )

    sql = tree.sql(dialect="postgres")
    reparsed = sqlglot.parse_one(sql, read="postgres")
    assert isinstance(reparsed, exp.Select)
    assert reparsed.find(exp.Where) is not None
    assert {column.name for column in reparsed.find_all(exp.Column)} >= {
        "id",
        "name",
        "age",
        "deleted_at",
    }


def test_build_select_ast_rejects_empty_table():
    with pytest.raises(ValueError, match="Semantic table cannot be empty"):
        build_select_ast("")
