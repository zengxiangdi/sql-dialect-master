from backend.core.rules import RuleCategory, TransformRule


def test_transform_rule_does_not_rewrite_single_quoted_literals():
    rule = TransformRule(
        name="test_ifnull",
        source="mysql",
        target="postgres",
        pattern=r"IFNULL\s*\(([^,]+),\s*([^)]+)\)",
        replacement=r"COALESCE(\1, \2)",
        note="test",
        category=RuleCategory.NULL_HANDLING,
    )

    sql = "SELECT 'IFNULL(name, unknown)' AS literal, IFNULL(name, unknown) AS value"
    result, applied = rule.apply(sql)

    assert applied is True
    assert "'IFNULL(name, unknown)'" in result
    assert "COALESCE(name, unknown)" in result


def test_transform_rule_preserves_mysql_backslash_escaped_quotes():
    rule = TransformRule(
        name="test_ifnull",
        source="mysql",
        target="postgres",
        pattern=r"IFNULL\s*\(([^,]+),\s*([^)]+)\)",
        replacement=r"COALESCE(\1, \2)",
        note="test",
        category=RuleCategory.NULL_HANDLING,
    )

    sql = r"SELECT 'it\'s IFNULL(name, unknown)' AS literal, IFNULL(name, unknown) AS value"
    result, applied = rule.apply(sql)

    assert applied is True
    assert r"'it\'s IFNULL(name, unknown)'" in result
    assert "COALESCE(name, unknown)" in result
