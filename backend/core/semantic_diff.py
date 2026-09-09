"""AST-based SQL semantic diff helpers.

The differ compares SQLGlot AST structure and canonical SQL. It distinguishes
syntax failures, structural/semantic differences, and cases where SQL semantics
cannot be proven from the AST alone.
"""
from collections import Counter
from dataclasses import dataclass, field
from difflib import unified_diff
from typing import List, Optional

import sqlglot
from sqlglot import exp


_CONTEXT_SENSITIVE_FUNCTIONS = {
    "CURRENT_DATE",
    "CURRENT_TIME",
    "CURRENT_TIMESTAMP",
    "LOCALTIME",
    "LOCALTIMESTAMP",
    "NOW",
    "RAND",
    "RANDOM",
    "UUID",
}

_CATEGORY_NODE_NAMES = {
    "predicate": {
        "And", "Between", "Eq", "Exists", "Greater", "GreaterThan", "GT",
        "GTE", "In", "Is", "Like", "Not", "Or", "RegExp", "Where",
    },
    "projection": {"Alias", "Column", "Select", "Star"},
    "grouping": {"Group", "Having"},
    "ordering": {"Order", "Ordered"},
    "row_limit": {"Fetch", "Limit", "Offset"},
    "join": {"Join"},
    "aggregate": {"AggFunc", "Count", "Sum", "Avg", "Min", "Max"},
    "literal_or_type": {"Boolean", "DataType", "Date", "Interval", "Literal", "Null"},
}


@dataclass
class SemanticDiff:
    """Comparison result with an explicit semantic confidence status."""

    equivalent: bool
    source_normalized: Optional[str]
    target_normalized: Optional[str]
    differences: List[str] = field(default_factory=list)
    parse_error: Optional[str] = None
    status: str = "different"
    difference_categories: List[str] = field(default_factory=list)


def _parse_and_normalize(sql: str, dialect: str) -> exp.Expression:
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("SQL must be a non-empty string")
    return sqlglot.parse_one(sql, read=dialect).transform(lambda node: node.copy())


def _canonical_sql(tree: exp.Expression) -> str:
    return tree.sql(dialect="", pretty=False).strip()


def _node_counts(tree: exp.Expression) -> Counter[str]:
    return Counter(type(node).__name__ for node in tree.walk())


def _context_sensitive_functions(tree: exp.Expression) -> List[str]:
    names = set()
    for node in tree.walk():
        sql_name = getattr(node, "sql_name", None)
        if not callable(sql_name):
            continue
        try:
            name = str(sql_name()).upper()
        except Exception:
            continue
        if name in _CONTEXT_SENSITIVE_FUNCTIONS:
            names.add(name)
    return sorted(names)


def _difference_categories(source_tree: exp.Expression, target_tree: exp.Expression) -> List[str]:
    categories = set()
    node_names = {type(node).__name__ for node in source_tree.walk()} | {
        type(node).__name__ for node in target_tree.walk()
    }
    for category, candidates in _CATEGORY_NODE_NAMES.items():
        if node_names & candidates:
            categories.add(category)
    return sorted(categories) or ["structure"]


def diff_sql_ast(
    source_sql: str,
    target_sql: str,
    source_dialect: str = "",
    target_dialect: str = "",
) -> SemanticDiff:
    """Compare two SQL ASTs and report semantic confidence explicitly.

    ``equivalent`` remains backward-compatible: it is true only when the ASTs
    match and no known context-sensitive construct prevents a safe conclusion.
    ``status`` is one of ``equivalent``, ``different``, ``unknown``, or
    ``parse_error``.
    """
    try:
        source_tree = _parse_and_normalize(source_sql, source_dialect)
        target_tree = _parse_and_normalize(target_sql, target_dialect)
    except Exception as exc:
        return SemanticDiff(
            equivalent=False,
            source_normalized=None,
            target_normalized=None,
            differences=["Unable to parse one or both SQL statements"],
            parse_error=str(exc),
            status="parse_error",
        )

    source_normalized = _canonical_sql(source_tree)
    target_normalized = _canonical_sql(target_tree)
    source_counts = _node_counts(source_tree)
    target_counts = _node_counts(target_tree)

    differences: List[str] = []
    categories: List[str] = []
    if source_normalized != target_normalized:
        diff_lines = list(
            unified_diff(
                source_normalized.splitlines(),
                target_normalized.splitlines(),
                fromfile="source",
                tofile="target",
                lineterm="",
            )
        )
        differences.append("Canonical AST SQL differs")
        differences.extend(diff_lines[:20])
        categories = _difference_categories(source_tree, target_tree)

    changed_nodes = sorted(set(source_counts) | set(target_counts))
    for node_name in changed_nodes:
        source_count = source_counts.get(node_name, 0)
        target_count = target_counts.get(node_name, 0)
        if source_count != target_count:
            differences.append(
                f"AST node count changed: {node_name} {source_count} -> {target_count}"
            )

    context_sensitive = sorted(
        set(_context_sensitive_functions(source_tree))
        | set(_context_sensitive_functions(target_tree))
    )
    if context_sensitive:
        differences.append(
            "Semantic equivalence is unknown for context-sensitive functions: "
            + ", ".join(context_sensitive)
        )
        categories = sorted(set(categories) | {"context_sensitive"})

    if source_normalized == target_normalized and not changed_nodes:
        status = "unknown" if context_sensitive else "equivalent"
    elif source_normalized == target_normalized and not context_sensitive:
        status = "equivalent"
    else:
        status = "unknown" if context_sensitive else "different"

    return SemanticDiff(
        equivalent=status == "equivalent",
        source_normalized=source_normalized,
        target_normalized=target_normalized,
        differences=differences,
        status=status,
        difference_categories=categories,
    )


class SQLSemanticDiffer:
    """Object-oriented facade for callers that prefer a reusable service."""

    @staticmethod
    def compare(
        source_sql: str,
        target_sql: str,
        source_dialect: str = "",
        target_dialect: str = "",
    ) -> SemanticDiff:
        return diff_sql_ast(source_sql, target_sql, source_dialect, target_dialect)
