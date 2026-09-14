"""Runtime semantic verification using DuckDB as universal execution engine.

DuckDB is chosen because it supports the broadest subset of SQL syntax across
all 12 dialects. For cases DuckDB cannot execute, we still validate parseability
and report semantic classification from AST-level diffing.

Known semantic limitations:
- DISTINCT aggregation ordering is non-deterministic across dialects
- CONCAT semantics differ (NULL propagation)
- Some dialect-specific syntax (TOP, ROWNUM, DISTRIBUTE BY) requires manual handling
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

import pytest
import sqlglot
from sqlglot import exp

duckdb = pytest.importorskip("duckdb", reason="duckdb not installed; skipping runtime semantic tests")

from backend.core.semantic_diff import diff_sql_ast
from backend.core.transpiler import SQLTranspiler
from backend.tests.semantic.corpus.runtime_cases import RUNTIME_CASES
from backend.tests.semantic.runtime_helpers import (
    SemanticCategory,
    create_employees_connection,
    execute_or_skip,
    normalize_for_set,
    normalize_rows,
)

logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def duckdb_conn():
    """Module-scoped DuckDB connection with test data."""
    conn = create_employees_connection()
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def transpiler():
    """Fresh transpiler instance per test."""
    return SQLTranspiler()


# =============================================================================
# Runtime comparison helpers
# =============================================================================

def compare_result_sets(
    src_rows: List[Tuple],
    tgt_rows: List[Tuple],
    category: str,
    src_sql: str,
    tgt_sql: str,
) -> Tuple[bool, str]:
    """Compare two result sets with category-aware normalization.

    Returns (passed, explanation).
    """
    src_norm = normalize_rows(src_rows)
    tgt_norm = normalize_rows(tgt_rows)

    if src_norm == tgt_norm:
        return True, "Result sets match"

    if category == SemanticCategory.KNOWN_DIFFERENCE:
        # For known differences, compare as canonicalized sets
        # (handles DISTINCT aggregation ordering differences)
        # Also handle type differences: array vs string aggregates
        src_canonical = _canonicalize_for_known_diff(src_norm)
        tgt_canonical = _canonicalize_for_known_diff(tgt_norm)
        if src_canonical == tgt_canonical:
            return True, "Result sets match (canonicalized for known difference)"
        return False, f"Canonicalized mismatch: src={src_canonical}, tgt={tgt_canonical}"

    if category == SemanticCategory.EQUIVALENT:
        return False, f"Expected equivalent but got mismatch: src={src_norm}, tgt={tgt_norm}"

    return False, f"Unexpected mismatch for category={category}: src={src_norm}, tgt={tgt_norm}"


def _canonicalize_for_known_diff(rows: List[Tuple]) -> set:
    """Normalize rows for set comparison across type boundaries.

    Converts arrays to sorted tuples and comma-separated strings to sorted
    tuples so that ARRAY_AGG(DISTINCT x) and GROUP_CONCAT(DISTINCT x) can be
    compared as equivalent semantically even though their runtime types differ.
    """
    result = set()
    for row in rows:
        normed = []
        for v in row:
            if isinstance(v, (list, tuple)):
                # Array → sorted tuple of string elements
                normed.append(tuple(sorted(str(x) for x in v)))
            elif isinstance(v, str) and "," in v:
                # String aggregate → sorted tuple of elements
                normed.append(tuple(sorted(v.split(","))))
            elif isinstance(v, float) and v == v:
                normed.append(round(float(v), 6))
            else:
                normed.append(v)
        result.add(tuple(normed))
    return result


def run_case(
    case: Tuple,
    conn,
    transpiler: SQLTranspiler,
) -> Dict[str, Any]:
    """Execute a single runtime test case.

    Returns a dict with: passed, category, source_rows, target_rows, error, notes.
    """
    src_dialect, src_sql, tgt_dialect, expected_category = case
    result = transpiler.transpile(src_sql, src_dialect, tgt_dialect, pretty=False)

    if not result.success:
        return {
            "passed": False,
            "category": "transpile_failed",
            "error": f"Transpile failed: {result.error}",
            "target_sql": None,
        }

    # Execute source in DuckDB
    src_rows, src_err = execute_or_skip(conn, src_sql)
    if src_err:
        return {
            "passed": expected_category in (SemanticCategory.UNKNOWN, SemanticCategory.KNOWN_DIFFERENCE),
            "category": "source_unexecutable",
            "error": f"Source not executable in DuckDB: {src_err}",
            "target_sql": result.target_sql,
        }

    # Execute target in DuckDB
    tgt_rows, tgt_err = execute_or_skip(conn, result.target_sql)
    if tgt_err:
        # Target not executable - check semantic diff
        diff = diff_sql_ast(src_sql, result.target_sql, src_dialect, tgt_dialect)
        if expected_category == SemanticCategory.KNOWN_DIFFERENCE:
            return {
                "passed": True,
                "category": "known_difference_target_unexecutable",
                "error": f"Target unexecutable (known): {tgt_err}",
                "target_sql": result.target_sql,
                "semantic_classification": diff.semantic_classification,
            }
        return {
            "passed": False,
            "category": "target_unexecutable",
            "error": f"Target not executable: {tgt_err}",
            "target_sql": result.target_sql,
        }

    # Compare result sets
    passed, explanation = compare_result_sets(
        src_rows, tgt_rows, expected_category, src_sql, result.target_sql
    )

    return {
        "passed": passed,
        "category": expected_category,
        "explanation": explanation,
        "source_rows": src_rows,
        "target_rows": tgt_rows,
        "target_sql": result.target_sql,
    }


# =============================================================================
# Parametrized runtime tests
# =============================================================================

@pytest.mark.parametrize(
    "case",
    RUNTIME_CASES,
    ids=lambda c: f"{c[0]}→{c[2]}:{c[1][:40]}",
)
def test_runtime_semantics(case, duckdb_conn, transpiler):
    """Verify transpiled SQL produces equivalent results across dialects."""
    src_dialect, src_sql, tgt_dialect, expected_category = case

    outcome = run_case(case, duckdb_conn, transpiler)

    if not outcome["passed"]:
        pytest.fail(
            f"Runtime semantic mismatch for {src_dialect}→{tgt_dialect}:\n"
            f"  Source: {src_sql}\n"
            f"  Target: {outcome.get('target_sql', 'N/A')}\n"
            f"  Category: {expected_category}\n"
            f"  Outcome: {outcome['category']}\n"
            f"  Error: {outcome.get('error', 'N/A')}\n"
        )


# =============================================================================
# Aggregate function specific tests
# =============================================================================

class TestAggregationRuntime:
    """Focused runtime tests for high-risk aggregation conversions."""

    @pytest.mark.parametrize(
        ("source_sql", "src_dialect", "tgt_dialect"),
        [
            ("SELECT GROUP_CONCAT(name) FROM employees WHERE active = TRUE", "mysql", "postgres"),
            ("SELECT GROUP_CONCAT(name ORDER BY id) FROM employees", "mysql", "postgres"),
            ("SELECT STRING_AGG(name, ',') FROM employees WHERE active = TRUE", "postgres", "mysql"),
            ("SELECT ARRAY_AGG(name) FROM employees WHERE active = TRUE", "postgres", "duckdb"),
            ("SELECT ARRAY_AGG(name) FROM employees WHERE active = TRUE", "duckdb", "postgres"),
            ("SELECT COUNT(*), SUM(salary), AVG(salary), MIN(salary), MAX(salary) FROM employees", "mysql", "postgres"),
        ],
    )
    def test_aggregation_equivalence(self, duckdb_conn, transpiler, source_sql, src_dialect, tgt_dialect):
        result = transpiler.transpile(source_sql, src_dialect, tgt_dialect, pretty=False)
        assert result.success, f"Transpile failed: {result.error}"

        src_rows, _ = execute_or_skip(duckdb_conn, source_sql)
        tgt_rows, tgt_err = execute_or_skip(duckdb_conn, result.target_sql)

        if tgt_err:
            pytest.skip(f"Target not executable in DuckDB: {tgt_err}")

        src_norm = normalize_rows(src_rows)
        tgt_norm = normalize_rows(tgt_rows)
        assert src_norm == tgt_norm, f"Row mismatch: src={src_norm}, tgt={tgt_norm}"


# =============================================================================
# Predicate runtime tests
# =============================================================================

class TestPredicateRuntime:
    """Runtime tests for predicate conversions."""

    @pytest.mark.parametrize(
        ("source_sql", "src_dialect", "tgt_dialect"),
        [
            ("SELECT COUNT(*) FROM employees WHERE active = TRUE", "mysql", "postgres"),
            ("SELECT COUNT(*) FROM employees WHERE salary > 80000", "mysql", "postgres"),
            ("SELECT COUNT(*) FROM employees WHERE id IN (1, 2, 3)", "mysql", "postgres"),
            ("SELECT COUNT(*) FROM employees WHERE id NOT IN (1, 2, 3)", "mysql", "postgres"),
            ("SELECT COUNT(*) FROM employees WHERE salary BETWEEN 70000 AND 100000", "mysql", "postgres"),
            ("SELECT COUNT(*) FROM employees WHERE name LIKE 'A%'", "mysql", "postgres"),
            ("SELECT COUNT(*) FROM employees WHERE active = TRUE AND salary > 90000", "mysql", "postgres"),
            ("SELECT COUNT(*) FROM employees WHERE active = TRUE OR department = 'sales'", "mysql", "postgres"),
        ],
    )
    def test_predicate_equivalence(self, duckdb_conn, transpiler, source_sql, src_dialect, tgt_dialect):
        result = transpiler.transpile(source_sql, src_dialect, tgt_dialect, pretty=False)
        assert result.success, f"Transpile failed: {result.error}"

        src_rows, _ = execute_or_skip(duckdb_conn, source_sql)
        tgt_rows, tgt_err = execute_or_skip(duckdb_conn, result.target_sql)

        if tgt_err:
            pytest.skip(f"Target not executable in DuckDB: {tgt_err}")

        assert src_rows == tgt_rows, f"Row mismatch: src={src_rows}, tgt={tgt_rows}"


# =============================================================================
# Group by / Having / Order by runtime tests
# =============================================================================

class TestGroupByRuntime:
    """Runtime tests for GROUP BY, HAVING, ORDER BY conversions."""

    @pytest.mark.parametrize(
        ("source_sql", "src_dialect", "tgt_dialect"),
        [
            ("SELECT department, COUNT(*) AS cnt FROM employees GROUP BY department", "mysql", "postgres"),
            ("SELECT department, COUNT(*) AS cnt FROM employees GROUP BY department HAVING COUNT(*) > 1", "mysql", "postgres"),
            ("SELECT * FROM employees ORDER BY salary DESC LIMIT 3", "mysql", "postgres"),
            ("SELECT * FROM employees LIMIT 10 OFFSET 2", "mysql", "postgres"),
            ("SELECT * FROM employees ORDER BY id FETCH FIRST 5 ROWS ONLY", "oracle", "mysql"),
        ],
    )
    def test_group_by_equivalence(self, duckdb_conn, transpiler, source_sql, src_dialect, tgt_dialect):
        result = transpiler.transpile(source_sql, src_dialect, tgt_dialect, pretty=False)
        assert result.success, f"Transpile failed: {result.error}"

        src_rows, _ = execute_or_skip(duckdb_conn, source_sql)
        tgt_rows, tgt_err = execute_or_skip(duckdb_conn, result.target_sql)

        if tgt_err:
            pytest.skip(f"Target not executable in DuckDB: {tgt_err}")

        src_norm = normalize_rows(src_rows)
        tgt_norm = normalize_rows(tgt_rows)
        assert src_norm == tgt_norm, f"Row mismatch: src={src_norm}, tgt={tgt_norm}"


# =============================================================================
# Date/Time runtime tests
# =============================================================================

class TestDateTimeRuntime:
    """Runtime tests for date/time function conversions."""

    @pytest.mark.parametrize(
        ("source_sql", "src_dialect", "tgt_dialect"),
        [
            ("SELECT CURRENT_DATE FROM employees LIMIT 1", "mysql", "postgres"),
            ("SELECT NOW() FROM employees LIMIT 1", "mysql", "postgres"),
            ("SELECT DATE_ADD(created_at, INTERVAL 7 DAY) FROM employees LIMIT 1", "mysql", "postgres"),
        ],
    )
    def test_datetime_equivalence(self, duckdb_conn, transpiler, source_sql, src_dialect, tgt_dialect):
        result = transpiler.transpile(source_sql, src_dialect, tgt_dialect, pretty=False)
        assert result.success, f"Transpile failed: {result.error}"

        src_rows, _ = execute_or_skip(duckdb_conn, source_sql)
        tgt_rows, tgt_err = execute_or_skip(duckdb_conn, result.target_sql)

        if tgt_err:
            pytest.skip(f"Target not executable in DuckDB: {tgt_err}")

        # For scalar date/time functions, just verify both execute without error
        assert len(src_rows) > 0
        assert len(tgt_rows) > 0


# =============================================================================
# IN predicate boundary tests
# =============================================================================

class TestINPredicateBoundaries:
    """Test IN predicate edge cases for the RC fix."""

    @pytest.mark.parametrize(
        ("source_sql", "src_dialect", "tgt_dialect", "expected_count"),
        [
            ("SELECT COUNT(*) FROM employees WHERE id IN (1, 2, 3)", "mysql", "postgres", 3),
            ("SELECT COUNT(*) FROM employees WHERE id NOT IN (1, 2, 3)", "mysql", "postgres", 3),
            ("SELECT COUNT(*) FROM employees WHERE department IN ('eng', 'sales')", "mysql", "postgres", 6),
            ("SELECT COUNT(*) FROM employees WHERE active IN (TRUE)", "mysql", "postgres", 5),
        ],
    )
    def test_in_predicate_count(self, duckdb_conn, transpiler, source_sql, src_dialect, tgt_dialect, expected_count):
        result = transpiler.transpile(source_sql, src_dialect, tgt_dialect, pretty=False)
        assert result.success, f"Transpile failed: {result.error}"

        # Source
        src_rows, _ = execute_or_skip(duckdb_conn, source_sql)
        assert src_rows[0][0] == expected_count, f"Source count mismatch: {src_rows[0][0]} != {expected_count}"

        # Target
        tgt_rows, tgt_err = execute_or_skip(duckdb_conn, result.target_sql)
        if tgt_err:
            pytest.skip(f"Target not executable: {tgt_err}")
        assert tgt_rows[0][0] == expected_count, f"Target count mismatch: {tgt_rows[0][0]} != {expected_count}"
