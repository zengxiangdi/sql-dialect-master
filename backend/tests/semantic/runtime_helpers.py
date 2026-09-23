"""DuckDB runtime helpers for SQL dialect equivalence testing.

DuckDB serves as the universal execution engine because it accepts
the broadest subset of SQL syntax across all 12 supported dialects.
"""

import datetime
import math


def _get_duckdb():
    """Return the duckdb module or raise ImportError."""
    try:
        import duckdb
        return duckdb
    except ImportError:
        return None


def create_employees_connection():
    """Create an in-memory DuckDB connection populated with test data."""
    db = _get_duckdb()
    if db is None:
        raise ImportError("duckdb is not installed")

    conn = db.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE employees (
            id INTEGER,
            name VARCHAR,
            department VARCHAR,
            salary INTEGER,
            active BOOLEAN,
            created_at DATE,
            manager_id INTEGER
        )
        """
    )
    conn.executemany(
        "INSERT INTO employees VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (1, "Alice", "eng", 100000, True, "2024-01-15", None),
            (2, "Bob", "eng", 120000, True, "2024-01-16", 1),
            (3, "Carol", "sales", 80000, True, "2024-01-17", None),
            (4, "Dave", "sales", 70000, False, "2024-01-18", 3),
            (5, "Eve", "eng", None, True, "2024-01-19", 1),
            (6, "Frank", "sales", 90000, True, "2024-01-20", None),
            (7, None, "hr", 60000, True, "2024-01-21", None),
        ],
    )
    return conn


def normalize_rows(rows) -> list:
    """Normalize rows for comparison: round floats, sort unordered results.

    Handles nested types (arrays/lists) by converting to tuples for sorting.
    NULL values are converted to a sortable sentinel to enable consistent ordering.
    For DISTINCT aggregation comparison, converts comma-separated strings
    to sorted tuples to enable set-based comparison.
    """
    NULL_SENTINEL = "\x00NULL\x00"  # Sorts before any printable string

    normalized = []
    for row in rows:
        normed = []
        for v in row:
            if v is None:
                normed.append(NULL_SENTINEL)
            elif isinstance(v, float) and not math.isnan(v):  # not NaN
                normed.append(round(float(v), 6))
            elif isinstance(v, datetime.datetime):
                normed.append(v.strftime("%Y-%m-%d %H:%M:%S"))
            elif isinstance(v, (list, tuple)):
                # Convert arrays to sorted tuples for comparison
                normed.append(tuple(sorted(str(x) for x in v if x is not None)))
            elif isinstance(v, str) and "," in v:
                # Comma-separated aggregate results — split and sort
                normed.append(tuple(sorted(v.split(","))))
            else:
                normed.append(v)
        normalized.append(tuple(normed))
    return sorted(normalized)


def execute_or_skip(connection, sql: str) -> tuple:
    """Execute SQL, returning (rows, None) on success or (None, error) on failure.

    Intentional broad catch (BLE001, justified below): this helper
    serves both the in-process DuckDB and psycopg(PostgreSQL) drivers,
    whose failure classes are disjoint — the narrowest catch shared by
    both is Exception. The contract is to convert any engine error
    into the returned (None, error) pair so runtime test suites can
    inspect it; no exception may escape the helper.
    """
    try:
        result = connection.execute(sql).fetchall()
        return result, None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


# Semantic categories for runtime comparison
class SemanticCategory:
    """Classification of result-set semantic relationship."""

    EQUIVALENT = "equivalent"
    STRUCTURALLY_EQUIVALENT = "structurally_equivalent"
    KNOWN_DIFFERENCE = "known_dialect_difference"
    CONVERSION_BUG = "conversion_bug"
    UNKNOWN = "unknown"
    PARSE_ERROR = "parse_error"
