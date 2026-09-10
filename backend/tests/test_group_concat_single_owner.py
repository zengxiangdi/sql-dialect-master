"""Regression tests proving GROUP_CONCAT conversion has a single owning implementation.

The effective runtime implementation is the structured_aggregation rule
(mysql_group_concat_to_postgres) which delegates to _replace_group_concat.

post_processor._fix_group_concat_default_separator is dead code — it never
fires because the rule engine handles all GROUP_CONCAT cases first, converting
GROUP_CONCAT to STRING_AGG before _fix_group_concat_default_separator runs.
"""
import pytest

from backend.core.compatibility import install_compatibility_patches
from backend.core.post_processor import PostProcessor
from backend.core.rules import rule_engine

install_compatibility_patches()


@pytest.mark.parametrize(
    ("name", "sql"),
    [
        ("simple_no_separator", "SELECT GROUP_CONCAT(name) FROM users"),
        ("with_separator", "SELECT GROUP_CONCAT(name SEPARATOR ';') FROM users"),
        ("distinct", "SELECT GROUP_CONCAT(DISTINCT name) FROM users"),
        ("distinct_order", "SELECT GROUP_CONCAT(DISTINCT name ORDER BY name) FROM users"),
        ("nested_expression", "SELECT GROUP_CONCAT(CONCAT(a, b)) FROM users"),
    ],
)
def test_group_concat_uses_single_effective_implementation(name, sql):
    """All GROUP_CONCAT conversions must go through the same path."""
    # Full process
    result_full, notes_full = PostProcessor().process(sql, "mysql", "postgres")

    # Rule engine alone (the effective implementation)
    result_rule, notes_rule = rule_engine.apply_rules(sql, "mysql", "postgres")

    # After rule engine, _fix_group_concat_default_separator is a no-op
    result_after_fix, notes_after_fix = PostProcessor()._fix_group_concat_default_separator(result_rule)

    # The effective result comes from the rule engine
    assert result_full == result_rule, (
        f"{name}: full process != rule engine"
    )
    assert result_full.startswith("SELECT STRING_AGG("), (
        f"{name}: expected STRING_AGG output, got {result_full}"
    )

    # _fix_group_concat_default_separator must be a no-op after rule engine
    assert result_after_fix == result_rule, (
        f"{name}: fix_group_concat changed rule engine output"
    )
    assert notes_after_fix == [], (
        f"{name}: fix_group_concat should return empty notes after rule engine"
    )
