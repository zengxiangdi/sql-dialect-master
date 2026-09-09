from backend.core.rules import RuleCategory, TransformRule


def _rule() -> TransformRule:
    return TransformRule(
        name="test_ifnull",
        source="mysql",
        target="postgres",
        pattern=r"IFNULL\s*\(([^,]+),\s*([^)]+)\)",
        replacement=r"COALESCE(\1, \2)",
        note="test",
        category=RuleCategory.NULL_HANDLING,
    )


def test_transform_rule_does_not_rewrite_double_quoted_identifiers():
    sql = 'SELECT "IFNULL(name, unknown)" AS identifier, IFNULL(name, unknown) AS value'
    result, applied = _rule().apply(sql)

    assert applied is True
    assert '"IFNULL(name, unknown)"' in result
    assert "COALESCE(name, unknown)" in result


def test_transform_rule_does_not_rewrite_backtick_quoted_identifiers():
    sql = "SELECT `IFNULL(name, unknown)` AS identifier, IFNULL(name, unknown) AS value"
    result, applied = _rule().apply(sql)

    assert applied is True
    assert "`IFNULL(name, unknown)`" in result
    assert "COALESCE(name, unknown)" in result


def test_transform_rule_does_not_rewrite_bracket_quoted_identifiers():
    sql = "SELECT [IFNULL(name, unknown)] AS identifier, IFNULL(name, unknown) AS value"
    result, applied = _rule().apply(sql)

    assert applied is True
    assert "[IFNULL(name, unknown)]" in result
    assert "COALESCE(name, unknown)" in result


def test_transform_rule_does_not_rewrite_postgres_dollar_quoted_body():
    sql = "SELECT $$IFNULL(name, unknown)$$ AS body, IFNULL(name, unknown) AS value"
    result, applied = _rule().apply(sql)

    assert applied is True
    assert "$$IFNULL(name, unknown)$$" in result
    assert "COALESCE(name, unknown)" in result


def test_transform_rule_does_not_rewrite_inside_multiline_comment():
    sql = "SELECT IFNULL(name, unknown) AS value /* IFNULL(fake, value) */"
    result, applied = _rule().apply(sql)

    assert applied is True
    assert "COALESCE(name, unknown)" in result
    assert "/* IFNULL(fake, value) */" in result


def test_transform_rule_preserves_nested_argument_text_without_crossing_non_code():
    sql = "SELECT IFNULL(name, unknown), 'IFNULL(fake, value)' FROM t"
    result, applied = _rule().apply(sql)

    assert applied is True
    assert "COALESCE(name, unknown)" in result
    assert "'IFNULL(fake, value)'" in result
