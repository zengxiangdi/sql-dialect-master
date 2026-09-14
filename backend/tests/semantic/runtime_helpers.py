#!/usr/bin/env python3
"""DuckDB runtime helpers for SQL dialect equivalence testing.

DuckDB is intentionally chosen as the universal execution engine because it
accepts the broadest subset of SQL syntax across all 12 supported dialects.
For dialects DuckDB cannot execute natively (ROWNUM, TOP, DISTRIBUTE BY),
we still validate that the target SQL parses in the target dialect and
report the semantic classification from AST-level diffing.
"""

import datetime
from typing import Any, List, Optional, Tuple


def _get_duckdb():
    """Return the duckdb module or raise ImportError."""
    import duckdb
    return duckdb


def create_employees_connection():
    """Create an in-memory DuckDB connection populated with test data.

    Raises ImportError if duckdb is not available.
    """
    db = _get_duckdb()
    conn = db.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE employees (
            id INTEGER,
            name VARCHAR,
            department VARCHAR,
            salary INTEGER,
            active BOOLEAN,
            created_at DATE
        )
        """
    )
    conn.executemany(
        "INSERT INTO employees VALUES (?, ?, ?, ?, ?, ?)",
        [
            (1, "Alice", "eng", 100000, True, "2024-01-15"),
            (2, "Bob", "eng", 120000, True, "2024-01-16"),
            (3, "Carol", "sales", 80000, True, "2024-01-17"),
            (4, "Dave", "sales", 70000, False, "2024-01-18"),
            (5, "Eve", "eng", None, True, "2024-01-19"),
            (6, "Frank", "sales", 90000, True, "2024-01-20"),
        ],
    )
    return conn


def normalize_rows(rows: List[Tuple]) -> List[Tuple]:
    """Normalize rows for comparison: round floats, sort unordered results.

    Handles nested types (arrays/lists) by converting to tuples for sorting.
    """
    normalized = []
    for row in rows:
        normed = []
        for v in row:
            if isinstance(v, float) and v == v:  # not NaN
                normed.append(round(float(v), 6))
            elif isinstance(v, datetime.datetime):
                normed.append(v.strftime("%Y-%m-%d %H:%M:%S"))
            elif isinstance(v, (list, tuple)):
                # Convert arrays to tuples for hashability
                normed.append(tuple(normalize_rows([v])[0]))
            else:
                normed.append(v)
        normalized.append(tuple(normed))
    return sorted(normalized)


def normalize_for_set(rows: List[Tuple]) -> set:
    """Convert rows to a hashable set for DISTINCT aggregation comparison.

    Handles comma-separated string aggregates (GROUP_CONCAT/STRING_AGG) by
    splitting on commas and sorting the individual elements before building
    the set, since DISTINCT aggregation ordering is non-deterministic across
    dialects.
    """
    result = set()
    for row in rows:
        normed = []
        for v in row:
            if isinstance(v, float) and v == v:
                normed.append(round(float(v), 6))
            elif isinstance(v, (list, tuple)):
                normed.append(tuple(v))
            elif isinstance(v, str) and "," in v:
                # Comma-separated aggregate result — split and sort
                # to enable set-based comparison regardless of dialect order
                normed.append(tuple(sorted(v.split(","))))
            else:
                normed.append(v)
        result.add(tuple(normed))
    return result


def execute_or_skip(conn, sql: str) -> Tuple[Optional[List], Optional[str]]:
    """Execute SQL, returning (rows, None) on success or (None, error) on failure."""
    db = _get_duckdb()
    try:
        result = conn.execute(sql).fetchall()
        return result, None
    except Exception as e:
        return None, str(e)


# Semantic categories for runtime comparison
class SemanticCategory:
    """Classification of result-set semantic relationship."""

    # Fully equivalent - same result set, same semantics
    EQUIVALENT = "equivalent"
    # Structurally equivalent AST but runtime order may differ
    STRUCTURALLY_EQUIVALENT = "structurally_equivalent"
    # Documented dialect semantic difference (e.g., DISTINCT ordering)
    KNOWN_DIFFERENCE = "known_dialect_difference"
    # Conversion bug - semantics changed unexpectedly
    CONVERSION_BUG = "conversion_bug"
    # Cannot determine - source or target unexecutable
    UNKNOWN = "unknown"
    # Parse error
    PARSE_ERROR = "parse_error"
