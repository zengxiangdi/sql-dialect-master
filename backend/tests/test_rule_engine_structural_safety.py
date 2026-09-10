import pytest

from backend.core.rules import TRANSFORM_RULES, RuleCategory, TransformRule



def _rule(name: str) -> TransformRule:
    for rule in TRANSFORM_RULES:
        if rule.name == name:
            return rule
    raise AssertionError(f"Missing rule: {name}")


@pytest.mark.parametrize(
    ("rule_name", "sql", "expected"),
    [
        (
            "mysql_ifnull_to_coalesce",
            "SELECT IFNULL(COALESCE(first_name, ''), 'unknown') FROM users",
            "SELECT COALESCE(COALESCE(first_name, ''), 'unknown') FROM users",
        ),
        (
            "oracle_nvl_to_coalesce",
            "SELECT NVL(CASE WHEN active = 1 THEN name ELSE NULL END, 'unknown') FROM users",
            "SELECT COALESCE(CASE WHEN active = 1 THEN name ELSE NULL END, 'unknown') FROM users",
        ),
        (
            "tsql_isnull_to_coalesce",
            "SELECT ISNULL(CAST(score AS DECIMAL(10, 2)), 0) FROM users",
            "SELECT COALESCE(CAST(score AS DECIMAL(10, 2)), 0) FROM users",
        ),
    ],
)
def test_null_function_rules_preserve_nested_arguments(rule_name, sql, expected):
    """Function rewrites must consume complete nested arguments, not stop at inner commas/parentheses."""
    transformed, applied = _rule(rule_name).apply(sql)

    assert applied is True
    assert transformed == expected



def test_aggregate_rule_preserves_nested_function_argument():
    rule = _rule("hive_collect_list_to_postgres")
    sql = "SELECT COLLECT_LIST(CONCAT(first_name, last_name)) FROM users"

    transformed, applied = rule.apply(sql)

    assert applied is True
    assert transformed == "SELECT ARRAY_AGG(CONCAT(first_name, last_name)) FROM users"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 'IFNULL(COALESCE(a, b), c)' FROM users",
        'SELECT "IFNULL(COALESCE(a, b), c)" FROM users',
        "SELECT IFNULL(a, b) -- IFNULL(COALESCE(a, b), c)\nFROM users",
        "SELECT /* IFNULL(COALESCE(a, b), c) */ IFNULL(a, b) FROM users",
    ],
)
def test_nested_rules_do_not_cross_lexical_boundaries(sql):
    """Rule application must remain limited to executable SQL regions."""
    rule = _rule("mysql_ifnull_to_coalesce")
    transformed, _ = rule.apply(sql)

    assert "'IFNULL(COALESCE(a, b), c)'" in transformed
    assert "IFNULL(COALESCE(a, b), c)" in transformed
    assert "-- IFNULL(COALESCE(a, b), c)" in transformed
    assert "/* IFNULL(COALESCE(a, b), c) */" in transformed



def test_custom_rule_with_nested_parentheses_uses_complete_expression():
    rule = TransformRule(
        name="nested_test",
        source="mysql",
        target="postgres",
        pattern=r"IFNULL\\s*\\(([^,]+),\\s*([^)]+)\\)",
        replacement=r"COALESCE(\\1, \\2)",
        note="nested test",
        category=RuleCategory.NULL_HANDLING,
    )
    sql = "SELECT IFNULL(JSON_EXTRACT(payload, '$.name'), CONCAT(first_name, last_name)) FROM users"

    transformed, applied = rule.apply(sql)

    assert applied is True
    assert transformed == (
        "SELECT COALESCE(JSON_EXTRACT(payload, '$.name'), "
        "CONCAT(first_name, last_name)) FROM users"
    )
