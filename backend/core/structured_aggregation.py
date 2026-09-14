"""Structured aggregation rule installer — intentionally empty.

Aggregation rewrites are now handled directly by TransformRule's
structured_replacer and full_sql_rewriter fields.
This module exists only to preserve import compatibility.
"""


def install_structured_aggregation_rules() -> None:
    """No-op: structured aggregation is handled natively by TransformRule."""
