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


def test_comparison_predicate_is_dialect_neutral():
    predicate = ComparisonPredicate(field="age", operator=">", value=18)

    assert predicate.field == "age"
    assert predicate.operator == ">"
    assert predicate.value == 18
    assert predicate.to_dict() == {
        "field": "age",
        "operator": ">",
        "value": 18,
    }


def test_range_predicate_defaults_to_inclusive_bounds():
    predicate = RangePredicate(field="price", lower=10, upper=20)

    assert predicate.lower == 10
    assert predicate.upper == 20
    assert predicate.inclusive_lower is True
    assert predicate.inclusive_upper is True


def test_text_null_and_set_predicates_are_distinct_semantic_types():
    contains = TextPredicate(field="name", operator="contains", value="alice")
    is_null = NullPredicate(field="deleted_at")
    in_set = SetPredicate(field="status", operator="in", values=("active", "pending"))

    assert contains.to_dict() == {
        "field": "name",
        "operator": "contains",
        "value": "alice",
    }
    assert is_null.to_dict() == {"field": "deleted_at", "is_null": True}
    assert in_set.to_dict() == {
        "field": "status",
        "operator": "in",
        "values": ("active", "pending"),
    }


def test_boolean_expression_preserves_nested_precedence():
    age = ComparisonPredicate(field="age", operator=">", value=18)
    status = ComparisonPredicate(field="status", operator="=", value="active")
    category = SetPredicate(field="category", operator="in", values=("A", "B"))

    expression = And(operands=(age, Or(operands=(status, category))))

    assert expression.operands[0] is age
    assert isinstance(expression.operands[1], Or)
    assert expression.operands[1].operands == (status, category)


def test_not_can_wrap_any_boolean_expression():
    predicate = NullPredicate(field="deleted_at", is_null=True)
    expression = Not(operand=predicate)

    assert expression.operand is predicate


def test_semantic_query_can_hold_the_where_expression():
    predicate = ComparisonPredicate(field="amount", operator=">=", value=100)
    query = SemanticQuery(
        table="orders",
        select_fields=("id", "amount"),
        where=predicate,
    )

    assert query.table == "orders"
    assert query.select_fields == ("id", "amount")
    assert query.to_dict()["where"]["operator"] == ">="


def test_and_and_or_require_at_least_two_operands():
    predicate = ComparisonPredicate(field="age", operator=">", value=18)

    with pytest.raises(ValueError, match="And requires at least two operands"):
        And(operands=(predicate,))

    with pytest.raises(ValueError, match="Or requires at least two operands"):
        Or(operands=(predicate,))


def test_set_predicate_requires_a_non_empty_value_set():
    with pytest.raises(ValueError, match="SetPredicate requires at least one value"):
        SetPredicate(field="status", operator="in", values=())
