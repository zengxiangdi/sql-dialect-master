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
    "row_limit": {"Fetch", "Limit", "Offset", "Top"},
    "join": {"Join"},
    "aggregate": {"AggFunc", "Count", "Sum", "Avg", "Min", "Max"},
    "literal_or_type": {"Boolean", "DataType", "Date", "Interval", "Literal", "Null"},
}


@dataclass(frozen=True)
class StructuredSemanticDifference:
    """Actionable description of one semantic difference category."""

    category: str
    severity: str
    source_fragment: str
    target_fragment: str
    explanation: str


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
    structured_differences: List[StructuredSemanticDifference] = field(default_factory=list)
    semantic_classification: str = "definitely_different"


def _strip_redundant_parentheses(node: exp.Expression) -> exp.Expression:
    """Remove redundant Paren nodes while preserving operator nesting."""
    if isinstance(node, exp.Paren):
        return node.this.copy()
    return node.copy()


def _parse_and_normalize(sql: str, dialect: str) -> exp.Expression:
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("SQL must be a non-empty string")
    return sqlglot.parse_one(sql, read=dialect).transform(_strip_redundant_parentheses)


def _canonical_sql(tree: exp.Expression) -> str:
    return tree.sql(dialect="", pretty=False).strip()


def _node_counts(tree: exp.Expression) -> Counter[str]:
    return Counter(type(node).__name__ for node in tree.walk())


def _function_names(tree: exp.Expression) -> List[str]:
    names = []
    for node in tree.walk():
        sql_name = getattr(node, "sql_name", None)
        if not callable(sql_name):
            continue
        try:
            name = str(sql_name()).upper()
        except (AttributeError, TypeError, ValueError):
            continue
        if name and name not in {"SELECT", "COLUMN", "TABLE", "LITERAL"}:
            names.append(name)
    return sorted(names)


def _context_sensitive_functions(tree: exp.Expression) -> List[str]:
    names = set()
    for node in tree.walk():
        sql_name = getattr(node, "sql_name", None)
        if not callable(sql_name):
            continue
        try:
            name = str(sql_name()).upper()
        except (AttributeError, TypeError, ValueError):
            name = ""
        if name in _CONTEXT_SENSITIVE_FUNCTIONS:
            names.add(name)
    return sorted(names)


def _fragment_sql(node: Optional[exp.Expression]) -> str:
    if node is None:
        return ""
    return node.sql(dialect="", pretty=False).strip()


def _list_fragment_sql(nodes) -> str:
    return "\n".join(_fragment_sql(node) for node in nodes)


def _difference_categories(
    source_tree: exp.Expression,
    target_tree: exp.Expression,
    functions_differ: bool = False,
) -> List[str]:
    """Return categories whose semantic regions actually changed."""
    categories = set()
    source_select = source_tree if isinstance(source_tree, exp.Select) else source_tree.find(exp.Select)
    target_select = target_tree if isinstance(target_tree, exp.Select) else target_tree.find(exp.Select)

    if source_select is not None and target_select is not None:
        if _list_fragment_sql(source_select.expressions) != _list_fragment_sql(target_select.expressions):
            categories.add("projection")
        source_where = _fragment_sql(source_select.args.get("where"))
        target_where = _fragment_sql(target_select.args.get("where"))
        if source_where != target_where:
            categories.add("predicate")
            if any("NULL" in fragment.upper() for fragment in (source_where, target_where)):
                categories.add("null_semantics")
        if _fragment_sql(source_select.args.get("having")) != _fragment_sql(target_select.args.get("having")):
            categories.update({"predicate", "grouping"})
        if _fragment_sql(source_select.args.get("group")) != _fragment_sql(target_select.args.get("group")):
            categories.add("grouping")
        if _fragment_sql(source_select.args.get("order")) != _fragment_sql(target_select.args.get("order")):
            categories.add("ordering")
        if _fragment_sql(source_select.args.get("limit")) != _fragment_sql(target_select.args.get("limit")):
            categories.add("row_limit")
        if _fragment_sql(source_select.args.get("offset")) != _fragment_sql(target_select.args.get("offset")):
            categories.add("row_limit")

    source_joins = list(source_tree.find_all(exp.Join))
    target_joins = list(target_tree.find_all(exp.Join))
    if _list_fragment_sql(source_joins) != _list_fragment_sql(target_joins):
        categories.add("join")

    source_aggregates = list(source_tree.find_all(exp.AggFunc))
    target_aggregates = list(target_tree.find_all(exp.AggFunc))
    if _list_fragment_sql(source_aggregates) != _list_fragment_sql(target_aggregates):
        categories.add("aggregate")

    source_literals = [node for node in source_tree.walk() if type(node).__name__ in _CATEGORY_NODE_NAMES["literal_or_type"]]
    target_literals = [node for node in target_tree.walk() if type(node).__name__ in _CATEGORY_NODE_NAMES["literal_or_type"]]
    if _list_fragment_sql(source_literals) != _list_fragment_sql(target_literals):
        categories.add("literal_or_type")

    if functions_differ:
        categories.add("function")

    return sorted(categories) or ["structure"]


def _category_fragments(
    category: str,
    source_tree: exp.Expression,
    target_tree: exp.Expression,
) -> tuple[str, str]:
    source_select = source_tree if isinstance(source_tree, exp.Select) else source_tree.find(exp.Select)
    target_select = target_tree if isinstance(target_tree, exp.Select) else target_tree.find(exp.Select)
    if category in {"predicate", "null_semantics"} and source_select is not None and target_select is not None:
        return (
            _fragment_sql(source_select.args.get("where")),
            _fragment_sql(target_select.args.get("where")),
        )
    if category == "projection" and source_select is not None and target_select is not None:
        return _list_fragment_sql(source_select.expressions), _list_fragment_sql(target_select.expressions)
    if category == "grouping" and source_select is not None and target_select is not None:
        return _fragment_sql(source_select.args.get("group")), _fragment_sql(target_select.args.get("group"))
    if category == "ordering" and source_select is not None and target_select is not None:
        return _fragment_sql(source_select.args.get("order")), _fragment_sql(target_select.args.get("order"))
    if category == "row_limit" and source_select is not None and target_select is not None:
        source = _fragment_sql(source_select.args.get("limit")) or _fragment_sql(source_select.args.get("offset"))
        target = _fragment_sql(target_select.args.get("limit")) or _fragment_sql(target_select.args.get("offset"))
        return source, target
    if category == "join":
        return _list_fragment_sql(source_tree.find_all(exp.Join)), _list_fragment_sql(target_tree.find_all(exp.Join))
    if category == "aggregate":
        return _list_fragment_sql(source_tree.find_all(exp.AggFunc)), _list_fragment_sql(target_tree.find_all(exp.AggFunc))
    return _canonical_sql(source_tree), _canonical_sql(target_tree)


def _structured_explanations(
    categories: List[str],
    source_tree: exp.Expression,
    target_tree: exp.Expression,
) -> List[StructuredSemanticDifference]:
    explanations = {
        "predicate": ("error", "Predicate logic changed; boolean precedence or filtering behavior may differ."),
        "null_semantics": ("error", "NULL comparison semantics changed; SQL three-valued logic may produce different rows."),
        "projection": ("warning", "Projected expressions changed, which can alter returned values or columns."),
        "grouping": ("error", "Grouping or HAVING structure changed, which can alter row cardinality and aggregates."),
        "ordering": ("warning", "Ordering changed; result sequence is not preserved."),
        "row_limit": ("error", "Row limiting changed; the returned row set or pagination semantics may differ."),
        "join": ("error", "JOIN structure changed; matching rows or row cardinality may differ."),
        "aggregate": ("error", "Aggregate expressions changed; computed results may differ."),
        "function": ("warning", "Function expressions differ and require dialect-specific semantic review."),
        "literal_or_type": ("warning", "Literal or type representation changed and may affect coercion or comparison semantics."),
        "structure": ("error", "AST structure changed outside a more specific semantic category."),
    }
    records: List[StructuredSemanticDifference] = []
    for category in categories:
        severity, explanation = explanations.get(category, ("warning", "The SQL structure differs and requires semantic review."))
        source_fragment, target_fragment = _category_fragments(category, source_tree, target_tree)
        records.append(
            StructuredSemanticDifference(
                category=category,
                severity=severity,
                source_fragment=source_fragment,
                target_fragment=target_fragment,
                explanation=explanation,
            )
        )
    return records


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
    ``parse_error``. ``semantic_classification`` refines the result without
    changing those existing status values.
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
            semantic_classification="parse_error",
        )

    source_normalized = _canonical_sql(source_tree)
    target_normalized = _canonical_sql(target_tree)
    source_counts = _node_counts(source_tree)
    target_counts = _node_counts(target_tree)
    source_functions = _function_names(source_tree)
    target_functions = _function_names(target_tree)
    functions_differ = source_functions != target_functions

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
        categories = _difference_categories(source_tree, target_tree, functions_differ)
    elif functions_differ:
        differences.append("Function expression set differs")
        categories = ["function"]

    changed_nodes = sorted(set(source_counts) | set(target_counts))
    for node_name in changed_nodes:
        source_count = source_counts.get(node_name, 0)
        target_count = target_counts.get(node_name, 0)
        if source_count != target_count:
            differences.append(
                f"AST node count changed: {node_name} {source_count} -> {target_count}"
            )
            if not categories:
                categories = ["structure"]

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

    if context_sensitive:
        status = "unknown"
        semantic_classification = "potentially_different"
    elif differences:
        status = "different"
        semantic_classification = "definitely_different"
    else:
        status = "equivalent"
        semantic_classification = "structurally_equivalent" if source_sql.strip() != target_sql.strip() else "equivalent"

    structured = []
    if categories and status != "unknown":
        structured = _structured_explanations(categories, source_tree, target_tree)
    elif status == "unknown":
        structured = [
            StructuredSemanticDifference(
                category="context_sensitive",
                severity="warning",
                source_fragment=source_normalized,
                target_fragment=target_normalized,
                explanation=(
                    "The query contains context-sensitive functions whose values can vary by execution time or environment; "
                    "AST equality alone cannot prove runtime equivalence."
                ),
            )
        ]

    return SemanticDiff(
        equivalent=status == "equivalent",
        source_normalized=source_normalized,
        target_normalized=target_normalized,
        differences=differences,
        status=status,
        difference_categories=categories,
        structured_differences=structured,
        semantic_classification=semantic_classification,
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
