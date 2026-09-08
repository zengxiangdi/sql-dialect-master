"""Regression tests for SQL-expression to Semantic IR conversion."""

from backend.core.semantic_ir import (
    And,
    ComparisonPredicate,
    Not,
    NullPredicate,
    Or,
    RangePredicate,
    SetPredicate,
    TextPredicate,
)
from backend.core.semantic_parser import parse_condition_expression, parse_condition_list


def test_parse_comparison():
    result = parse_condition_expression("(age > 18)")
    assert result == ComparisonPredicate(field="age", operator=">", value=18)


def test_parse_nested_boolean_precedence():
    result = parse_condition_expression(
        "(age > 18) AND ((status = 'active') OR (category IN ('A', 'B')))"
    )
    assert isinstance(result, And)
    assert isinstance(result.operands[0], ComparisonPredicate)
    assert isinstance(result.operands[1], Or)
    assert isinstance(result.operands[1].operands[0], ComparisonPredicate)
    assert result.operands[1].operands[1] == SetPredicate(
        field="category", operator="in", values=("A", "B")
    )


def test_parse_not_in_and_not_null():
    not_in = parse_condition_expression("status NOT IN ('inactive', 'deleted')")
    assert isinstance(not_in, Not)
    assert not_in.operand == SetPredicate(
        field="status", operator="in", values=("inactive", "deleted")
    )

    not_null = parse_condition_expression("name IS NOT NULL")
    assert isinstance(not_null, Not)
    assert not_null.operand == NullPredicate(field="name", is_null=True)


def test_parse_range_and_text_predicates():
    assert parse_condition_expression("price BETWEEN 10 AND 20") == RangePredicate(
        field="price", lower=10, upper=20
    )
    assert parse_condition_expression("name LIKE '%alice%'") == TextPredicate(
        field="name", operator="contains", value="alice"
    )


def test_parse_condition_list_requires_one_combined_expression():
    assert parse_condition_list([]) is None
    assert parse_condition_list(["(age > 18) AND (status = 'active')"]) == And(
        operands=(
            ComparisonPredicate(field="age", operator=">", value=18),
            ComparisonPredicate(field="status", operator="=", value="active"),
        )
    )


def test_parse_rejects_multiple_uncombined_conditions():
    try:
        parse_condition_list(["age > 18", "status = 'active'"])
    except ValueError as exc:
        assert "Expected one combined boolean condition expression" in str(exc)
    else:
        raise AssertionError("expected ValueError")
