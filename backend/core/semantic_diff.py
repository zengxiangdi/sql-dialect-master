"""AST-based SQL semantic diff helpers.

The differ deliberately compares SQLGlot's dialect-independent generated SQL and
its AST node shape. It is a structural regression detector, not a proof of
runtime equivalence across database engines.
"""
from collections import Counter
from dataclasses import dataclass, field
from difflib import unified_diff
from typing import List, Optional

import sqlglot
from sqlglot import exp


@dataclass
class SemanticDiff:
    """Structural comparison of two SQL statements."""

    equivalent: bool
    source_normalized: Optional[str]
    target_normalized: Optional[str]
    differences: List[str] = field(default_factory=list)
    parse_error: Optional[str] = None


def _parse_and_normalize(sql: str, dialect: str) -> exp.Expression:
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("SQL must be a non-empty string")
    return sqlglot.parse_one(sql, read=dialect).transform(lambda node: node.copy())


def _canonical_sql(tree: exp.Expression) -> str:
    return tree.sql(dialect="", pretty=False).strip()


def _node_counts(tree: exp.Expression) -> Counter[str]:
    return Counter(type(node).__name__ for node in tree.walk())


def diff_sql_ast(
    source_sql: str,
    target_sql: str,
    source_dialect: str = "",
    target_dialect: str = "",
) -> SemanticDiff:
    """Compare two SQL ASTs after parsing them in their native dialects.

    Equality means SQLGlot produced the same dialect-independent canonical SQL
    and the same AST node-type shape. A difference means the conversion should
    be reviewed; it does not by itself prove the target query is wrong.
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
        )

    source_normalized = _canonical_sql(source_tree)
    target_normalized = _canonical_sql(target_tree)
    source_counts = _node_counts(source_tree)
    target_counts = _node_counts(target_tree)

    differences: List[str] = []
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

    changed_nodes = sorted(set(source_counts) | set(target_counts))
    for node_name in changed_nodes:
        source_count = source_counts.get(node_name, 0)
        target_count = target_counts.get(node_name, 0)
        if source_count != target_count:
            differences.append(
                f"AST node count changed: {node_name} {source_count} -> {target_count}"
            )

    return SemanticDiff(
        equivalent=not differences,
        source_normalized=source_normalized,
        target_normalized=target_normalized,
        differences=differences,
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
