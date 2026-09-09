#!/usr/bin/env python3
"""Semantics-aware function equivalence metadata for SQL dialect conversion.

The existing function catalog answers "is there syntax for this function?".
This module answers the stronger question "can this function be treated as
semantically equivalent for this source/target dialect pair?".

Only explicitly-reviewed functions and dialect pairs are classified as
semantic equivalence. Unreviewed pairs remain ``unknown`` instead of being
inferred from syntax availability or fuzzy matching.
"""
from typing import Any, Dict, Tuple


FunctionKey = Tuple[str, str, str]


_SEMANTIC_STATUS = {
    "equivalent": "equivalent",
    "supported-but-different": "supported-but-different",
    "unsupported": "unsupported",
    "unknown": "unknown",
}


# Explicit metadata for the initial high-risk cross-dialect corpus.
# Keep this registry intentionally small: additions require semantic review and
# a regression test rather than being inferred from functions_db.json syntax.
_FUNCTION_SEMANTICS: Dict[str, Dict[str, Any]] = {
    "DATEDIFF": {
        "argument_semantics": "calendar-day difference; argument order and/or unit syntax is dialect-sensitive",
        "return_shape": "scalar integer-like value",
        "null_behavior": "NULL-sensitive; follows source/target function semantics",
        "notes": "Dialect implementations differ in argument order and unit handling.",
        "pairs": {
            ("mysql", "tsql"): "supported-but-different",
            ("mysql", "postgres"): "supported-but-different",
        },
    },
    "DATE_FORMAT": {
        "argument_semantics": "format a date/time value using dialect-specific format tokens",
        "return_shape": "string",
        "null_behavior": "NULL input produces NULL",
        "notes": "Formatting token languages differ across dialects.",
        "pairs": {
            ("mysql", "postgres"): "supported-but-different",
        },
    },
    "LENGTH": {
        "argument_semantics": "string length; byte-vs-character semantics may differ",
        "return_shape": "scalar integer-like value",
        "null_behavior": "NULL input produces NULL",
        "notes": "MySQL LENGTH is byte-oriented while Oracle LENGTH is character-oriented.",
        "pairs": {
            ("mysql", "oracle"): "supported-but-different",
        },
    },
    "CONCAT": {
        "argument_semantics": "variadic string concatenation",
        "return_shape": "string",
        "null_behavior": "NULL propagation semantics differ by dialect",
        "notes": "MySQL CONCAT propagates NULL arguments; PostgreSQL CONCAT ignores NULL arguments.",
        "pairs": {
            ("mysql", "postgres"): "supported-but-different",
        },
    },
    "GET_JSON_OBJECT": {
        "argument_semantics": "extract a JSON path value with dialect-specific JSON path/operator semantics",
        "return_shape": "scalar text-like JSON value",
        "null_behavior": "path/input failures are dialect-sensitive",
        "notes": "Hive GET_JSON_OBJECT is not a semantic synonym for PostgreSQL JSON operators.",
        "pairs": {
            ("hive", "postgres"): "supported-but-different",
        },
    },
    "COLLECT_LIST": {
        "argument_semantics": "aggregate input values into a collection; ordering is not implied unless explicitly specified",
        "return_shape": "array/list-like aggregate",
        "null_behavior": "NULL inclusion/filtering is dialect-sensitive",
        "notes": "Spark COLLECT_LIST and PostgreSQL ARRAY_AGG differ in output type and ordering guarantees.",
        "pairs": {
            ("spark", "postgres"): "supported-but-different",
        },
    },
    "ROW_NUMBER": {
        "argument_semantics": "assign sequential row numbers within an optional window specification",
        "return_shape": "integer-like value",
        "null_behavior": "window ordering determines numbering; NULL ordering remains dialect-sensitive",
        "notes": "Core window semantics are equivalent for the reviewed pair when the same ORDER BY semantics are preserved.",
        "pairs": {
            ("postgres", "mysql"): "equivalent",
        },
    },
    "REGEXP_REPLACE": {
        "argument_semantics": "replace regex matches using dialect-specific regex engines and replacement rules",
        "return_shape": "string",
        "null_behavior": "NULL input produces NULL",
        "notes": "T-SQL has no native REGEXP_REPLACE equivalent in the reviewed baseline.",
        "pairs": {},
    },
}


class FunctionSemanticRegistry:
    """Resolve explicit semantic equivalence for reviewed SQL functions."""

    def __init__(self, semantics: Dict[str, Dict[str, Any]] = None) -> None:
        self._semantics = semantics if semantics is not None else _FUNCTION_SEMANTICS

    def resolve(self, function: str, source: str, target: str) -> Dict[str, Any]:
        """Return an explicit semantic classification for a function pair."""
        function_name = function.upper().strip()
        source_dialect = source.lower().strip()
        target_dialect = target.lower().strip()
        metadata = self._semantics.get(function_name)

        if metadata is None:
            return {
                "function": function_name,
                "source_dialect": source_dialect,
                "target_dialect": target_dialect,
                "status": _SEMANTIC_STATUS["unknown"],
                "equivalent": False,
                "reason": "Function is not present in the reviewed semantic registry.",
            }

        pair_status = metadata.get("pairs", {}).get((source_dialect, target_dialect))
        if pair_status is None:
            if function_name == "REGEXP_REPLACE" and target_dialect == "tsql":
                pair_status = _SEMANTIC_STATUS["unsupported"]
            else:
                pair_status = _SEMANTIC_STATUS["unknown"]

        return {
            "function": function_name,
            "source_dialect": source_dialect,
            "target_dialect": target_dialect,
            "status": pair_status,
            "equivalent": pair_status == _SEMANTIC_STATUS["equivalent"],
            "argument_semantics": metadata.get("argument_semantics", ""),
            "return_shape": metadata.get("return_shape", ""),
            "null_behavior": metadata.get("null_behavior", ""),
            "notes": metadata.get("notes", ""),
        }

    def get_metadata(self, function: str) -> Dict[str, Any]:
        """Return reviewed metadata without inferring semantic equivalence."""
        return self._semantics.get(function.upper().strip(), {})
