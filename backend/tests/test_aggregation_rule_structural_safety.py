import pytest

from backend.core.rules import TRANSFORM_RULES


def _rule(name: str):
    for rule in TRANSFORM_RULES:
        if rule.name == name:
            return rule
    raise AssertionError(f"Missing rule: {name}")


@pytest.mark.parametrize(
    ("rule_name", "sql", "expected"),
    [
        (
            "tsql_string_agg_to_mysql",
            "SELECT STRING_AGG(CONCAT(first_name, last_name), ',') FROM users",
            "SELECT GROUP_CONCAT(CONCAT(first_name, last_name) SEPARATOR ',') FROM users",
        ),
        (
            "mysql_group_concat_to_postgres",
            "SELECT GROUP_CONCAT(CONCAT(first_name, last_name) SEPARATOR ',') FROM users",
            "SELECT STRING_AGG(CONCAT(first_name, last_name)::TEXT, ',') FROM users",
        ),
        (
            "postgres_string_agg_to_mysql",
            "SELECT STRING_AGG(CONCAT(first_name, last_name), ',') FROM users",
            "SELECT GROUP_CONCAT(CONCAT(first_name, last_name) SEPARATOR ',') FROM users",
        ),
    ],
)
def test_string_aggregation_rules_consume_complete_nested_arguments(rule_name, sql, expected):
    """Aggregation rewrites must not stop at an inner comma or parenthesis."""
    transformed, applied = _rule(rule_name).apply(sql)

    assert applied is True
    assert transformed == expected


def test_listagg_rule_accepts_nested_expression_and_order_expression():
    """LISTAGG must consume the complete value and ORDER BY expressions."""
    rule = _rule("oracle_listagg_to_hive")
    sql = (
        "SELECT LISTAGG(CONCAT(first_name, last_name), ',') "
        "WITHIN GROUP (ORDER BY LOWER(last_name)) FROM users"
    )

    transformed, applied = rule.apply(sql)

    assert applied is True
    assert transformed == "SELECT ARRAY_JOIN(COLLECT_LIST(CONCAT(first_name, last_name)), ',') FROM users"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 'GROUP_CONCAT(CONCAT(a, b))' FROM users",
        'SELECT "STRING_AGG(CONCAT(a, b), \',\')" FROM users',
        "SELECT GROUP_CONCAT(name) -- GROUP_CONCAT(CONCAT(a, b))\nFROM users",
        "SELECT /* STRING_AGG(CONCAT(a, b), ',') */ STRING_AGG(name, ',') FROM users",
    ],
)
def test_aggregation_rules_do_not_cross_lexical_boundaries(sql):
    """Function tokens in literals, identifiers, and comments are not SQL calls."""
    rules = (
        _rule("mysql_group_concat_to_postgres"),
        _rule("postgres_string_agg_to_mysql"),
    )

    for rule in rules:
        transformed, _ = rule.apply(sql)
        assert "GROUP_CONCAT(CONCAT(a, b))" in transformed or "STRING_AGG(CONCAT(a, b), ',')" in transformed


def test_malformed_aggregation_expression_remains_unchanged():
    """An incomplete function call must fail closed rather than partially rewrite."""
    rule = _rule("postgres_string_agg_to_mysql")
    sql = "SELECT STRING_AGG(CONCAT(first_name, last_name), ',' FROM users"

    transformed, applied = rule.apply(sql)

    assert applied is False
    assert transformed == sql
