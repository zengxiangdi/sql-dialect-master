"""Compatibility integration for exposing Semantic IR during NL2SQL generation.

The existing generator remains responsible for SQL generation. This module adds
structured semantic metadata after generation when the dedicated boolean parser
can produce it, allowing callers/tests to consume the IR before SQL generation
is migrated to AST-based output.
"""
from __future__ import annotations

from typing import Any

from .semantic_parser import parse_condition_list


def enrich_result_with_semantic_ir(result: Any, conditions: list[str], dialect: str) -> Any:
    """Attach a dialect-neutral semantic IR payload to an NL2SQL result."""
    if not conditions:
        return result
    try:
        expression = parse_condition_list(conditions, dialect=dialect)
    except ValueError:
        return result
    if expression is not None:
        result.parsed_elements["semantic_ir"] = expression.to_dict()
    return result


__all__ = ["enrich_result_with_semantic_ir"]
