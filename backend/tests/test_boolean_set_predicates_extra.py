"""Extra AST regressions for mixed IN/NULL/range boolean predicates."""

from sqlglot import exp

from backend.tests.test_boolean_predicate_types import parse_where


def test_mixed_membership_null_and_comparison_precedence():
    boolean = parse_where(
        "find products with category in ('phone', 'tablet') and description is not null or price greater than 500"
    )
    assert isinstance(boolean, exp.Or)
    assert isinstance(boolean.this, exp.And)
    assert len(list(boolean.find_all(exp.In))) == 1
    assert len(list(boolean.find_all(exp.Is))) == 1
    assert len(list(boolean.find_all(exp.GT))) == 1
