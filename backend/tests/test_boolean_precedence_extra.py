"""Additional AST regression for nested boolean groups."""

from sqlglot import exp

from backend.tests.test_boolean_precedence import parse_where


def test_nested_parentheses_keep_group_structure():
    boolean = parse_where(
        "find products with ((price greater than 100 or quantity less than 10) and status active) or amount greater than 500"
    )

    assert isinstance(boolean, exp.Or)
    left = boolean.this
    assert isinstance(left, exp.Paren)
    assert isinstance(left.this, exp.And)
    assert isinstance(left.this.this, exp.Paren)
    assert isinstance(left.this.this.this, exp.Or)
    assert isinstance(boolean.expression, exp.Paren)
    assert isinstance(boolean.expression.this, exp.GT)
