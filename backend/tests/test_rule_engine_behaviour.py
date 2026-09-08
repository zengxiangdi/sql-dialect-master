from backend.core.rules import RuleCategory, RuleEngine, TransformRule


def make_rule(name: str, source: str = "mysql", target: str = "postgres", priority: int = 50) -> TransformRule:
    return TransformRule(
        name=name,
        source=source,
        target=target,
        pattern=r"FOO",
        replacement="BAR",
        note=name,
        category=RuleCategory.FUNCTION,
        priority=priority,
    )


def test_rules_are_sorted_deterministically_by_priority_then_name() -> None:
    engine = RuleEngine([
        make_rule("zeta", priority=50),
        make_rule("alpha", priority=50),
        make_rule("high", priority=80),
    ])

    assert [rule.name for rule in engine.rules] == ["high", "alpha", "zeta"]


def test_add_rule_rejects_duplicate_names_and_invalid_patterns() -> None:
    engine = RuleEngine([make_rule("existing")])

    try:
        engine.add_rule(make_rule("existing"))
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("duplicate rule name was accepted")

    invalid = make_rule("invalid")
    invalid.pattern = "["
    try:
        engine.add_rule(invalid)
    except ValueError as exc:
        assert "Invalid pattern" in str(exc)
    else:
        raise AssertionError("invalid rule pattern was accepted")


def test_validate_rules_uses_dialect_selector_intersection() -> None:
    engine = RuleEngine([
        make_rule("mysql_rule", source="mysql", target="postgres"),
        make_rule("oracle_rule", source="oracle", target="postgres"),
    ])

    warnings = engine.validate_rules()

    assert not any("mysql_rule" in warning and "oracle_rule" in warning for warning in warnings)
    assert RuleEngine._dialect_sets_intersect("mysql,oracle", "oracle")
    assert RuleEngine._dialect_sets_intersect("*", "oracle")
    assert not RuleEngine._dialect_sets_intersect("mysql", "oracle")


def test_added_rule_is_immediately_compiled_and_applied() -> None:
    engine = RuleEngine([])
    engine.add_rule(make_rule("foo_to_bar"))

    result, notes = engine.apply_rules("SELECT FOO", "mysql", "postgres")

    assert result == "SELECT BAR"
    assert notes == ["foo_to_bar"]


def test_dialect_selectors_ignore_whitespace_and_case() -> None:
    rule = make_rule(
        "multi_dialect",
        source="mysql, oracle",
        target="postgres, Hive",
    )

    assert rule.matches_dialects("ORACLE", "hive")
    assert rule.matches_dialects("mysql", "POSTGRES")
    assert not rule.matches_dialects("spark", "hive")

def test_rule_apply_surfaces_regex_execution_errors() -> None:
    rule = make_rule("bad_replacement")
    rule.replacement = r"\2"

    import re
    import pytest

    with pytest.raises(re.error, match="invalid group reference"):
        rule.apply("SELECT FOO")

