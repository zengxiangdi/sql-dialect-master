"""Behavior contracts for dialect rules and NL2SQL predicate extraction."""

import pytest

from backend.core.nl2sql_components.mappings import COLUMN_PATTERNS
from backend.core.nl2sql_pipeline.predicates import extract_conditions
from backend.core.rules import RuleEngine, TransformRule


@pytest.mark.parametrize(
    ("source", "target", "sql"),
    [
        ("postgres", "mysql", "SELECT STRING_AGG(name) FROM products"),
        ("postgres", "mysql", "SELECT STRING_AGG(name,) FROM products"),
        ("mysql", "postgres", "SELECT GROUP_CONCAT(name SEPARATOR) FROM products"),
        ("mysql", "postgres", "SELECT GROUP_CONCAT() FROM products"),
        ("mysql", "postgres", "SELECT JSON_EXTRACT(payload) FROM events"),
        ("mysql", "postgres", "SELECT JSON_EXTRACT(payload, path) FROM events"),
        ("mysql", "postgres", "SELECT JSON_EXTRACT(payload, '$.items[0]') FROM events"),
        ("oracle", "hive", "SELECT LISTAGG(name, ',') FROM products"),
        ("oracle", "hive", "SELECT LISTAGG_PREFIX, xLISTAGG(name, ',') WITHIN GROUP (ORDER BY id) FROM products"),
        ("oracle", "hive", "SELECT LISTAGG(name, ','"),
        ("oracle", "hive", "SELECT LISTAGG(name, ',') WITHIN GROUP ORDER BY id"),
        ("oracle", "hive", "SELECT LISTAGG(name, ',') WITHIN GROUP (ORDER BY id"),
        ("oracle", "hive", "SELECT LISTAGG(name, ',') WITHIN GROUP (GROUP BY id) FROM products"),
        ("oracle", "hive", "SELECT LISTAGG(name) WITHIN GROUP (ORDER BY id) FROM products"),
    ],
)
def test_rule_engine_preserves_unsupported_function_forms(source: str, target: str, sql: str) -> None:
    assert RuleEngine().apply_rules(sql, source, target) == (sql, [])


def test_group_concat_uses_only_top_level_separator_and_order() -> None:
    sql = "SELECT GROUP_CONCAT(CONCAT(separator_code, 'SEPARATOR') ORDER BY id SEPARATOR '|') FROM products"

    converted, notes = RuleEngine().apply_rules(sql, "mysql", "postgres")

    assert converted == "SELECT STRING_AGG(CONCAT(separator_code, 'SEPARATOR')::TEXT, '|' ORDER BY id) FROM products"
    assert notes == ["Converted GROUP_CONCAT to STRING_AGG"]


def test_listagg_accepts_nested_sort_expression_and_reports_dropped_order() -> None:
    sql = "SELECT LISTAGG (name, ',') WITHIN GROUP (ORDER BY COALESCE(rank, 0)) FROM products"

    converted, notes = RuleEngine().apply_rules(sql, "oracle", "hive")

    assert converted == "SELECT ARRAY_JOIN(COLLECT_LIST(name), ',') FROM products"
    assert notes == ["Converted LISTAGG to ARRAY_JOIN(COLLECT_LIST()). ORDER BY not preserved"]


def _rule(name: str, pattern: str, replacement: str, *, priority: int = 50) -> TransformRule:
    return TransformRule(name, "mysql", "postgres", pattern, replacement, name, priority=priority)


def test_rule_engine_applies_priority_and_keeps_cached_rules_isolated() -> None:
    high = _rule("first", r"\bFOO\b", "BAR", priority=80)
    low = _rule("second", r"\bBAR\b", "BAZ")
    engine = RuleEngine([low, high])
    sql = "SELECT FOO"

    applicable = engine.get_applicable_rules("mysql", "postgres")
    assert applicable == [high, low]
    applicable.clear()
    assert engine.apply_rules(sql, "mysql", "postgres") == ("SELECT BAZ", ["first", "second"])

    assert engine.disable_rule("missing") is False
    assert engine.enable_rule("missing") is False
    assert engine.disable_rule("first") is True
    assert engine.apply_rules(sql, "mysql", "postgres") == (sql, [])
    assert engine.enable_rule("first") is True
    assert engine.apply_rules(sql, "mysql", "postgres") == ("SELECT BAZ", ["first", "second"])
    assert engine.apply_rules(sql, "mysql", "hive") == (sql, [])


def test_rule_validation_reports_duplicate_empty_and_conflict() -> None:
    empty = _rule("empty", "", "BAR")
    duplicate = _rule("duplicate", r"\bFOO\b", "BAR")
    other = _rule("other", r"\bBAR\b", "BAZ", priority=10)
    engine = RuleEngine([empty, duplicate, duplicate, other])

    warnings = engine.validate_rules()

    assert set(warnings) == {
        "Duplicate rule name: duplicate",
        "Empty pattern in rule: empty",
        "Potential conflict: duplicate and empty have same priority/category and overlapping dialects",
    }


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("age greater than approximately 12", ["age > 12"]),
        ("age greater than", []),
        ("price between -2 and 4.5", ["price BETWEEN -2 AND 4.5"]),
        ("名称包含绿茶", ["name LIKE '%绿茶%'"]),
        ("description like 'summer'", ["description LIKE '%summer%'"]),
        ("description like", []),
        ("name contains ''", []),
        ("状态为空", ["status IS NULL"]),
        ("status is not null", ["status IS NOT NULL"]),
        ("名称包含绿茶且价格大于10", ["(name LIKE '%绿茶%') AND (price > 10)"]),
        ("status in (active, pending,)", ["status IN ('active', 'pending')"]),
        ("quantity not in (1.5, -2)", ["quantity NOT IN (1.5, -2)"]),
        ("status in (, )", []),
        ("color = 'unterminated", []),
        ("前天", ["date = DATE_SUB(CURRENT_DATE, 2)"]),
        ("last 2 months", ["date >= ADD_MONTHS(CURRENT_DATE, -2)"]),
        ("last 2 years", ["date >= ADD_MONTHS(CURRENT_DATE, -24)"]),
        ("created_at this year", ["YEAR(created_at) = YEAR(CURRENT_DATE)"]),
    ],
)
def test_extract_conditions_preserves_operation_and_value(text: str, expected: list[str]) -> None:
    assert extract_conditions(text.lower(), text, COLUMN_PATTERNS) == expected
