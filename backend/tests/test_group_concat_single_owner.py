"""Regression tests proving GROUP_CONCAT conversion has a single owning implementation.

The effective runtime implementation is the rule engine's
structured aggregation rewrite (mysql_group_concat_to_postgres) which
delegates to _replace_group_concat.

The PostProcessor's custom transformation step contributes no GROUP_CONCAT
rewrite for mysql→postgres: the rule engine owns all cases. This test
locks in that invariant by asserting the full PostProcessor.process
output equals the rule engine output for every observed case.
"""
import pytest

from backend.core.post_processor import PostProcessor
from backend.core.rules import rule_engine


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
    """All GROUP_CONCAT conversions must go through the rule engine only."""
    result_full, _ = PostProcessor().process(sql, "mysql", "postgres")
    result_rule, _ = rule_engine.apply_rules(sql, "mysql", "postgres")

    # The effective result comes entirely from the rule engine
    assert result_full == result_rule, (
        f"{name}: full process != rule engine"
    )
    assert result_full.startswith("SELECT STRING_AGG("), (
        f"{name}: expected STRING_AGG output, got {result_full}"
    )
