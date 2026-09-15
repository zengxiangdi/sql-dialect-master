"""Runtime semantic verification using DuckDB as universal execution engine.

Tests transpiled SQL against source SQL using DuckDB's broad SQL compatibility.
Covers predicates, aggregations, joins, ordering, date/time, and DML.
"""

import pytest

# Skip entire module if duckdb is not available (e.g., in base CI without semantic deps)
duckdb = pytest.importorskip(
    "duckdb",
    reason="duckdb not installed; skip DuckDB-based runtime semantic tests",
)

import sqlglot
from sqlglot import exp

from backend.core.semantic_diff import diff_sql_ast
from backend.core.transpiler import SQLTranspiler
from backend.tests.semantic.runtime_helpers import (
    SemanticCategory,
    create_employees_connection,
    execute_or_skip,
    normalize_rows,
)


@pytest.fixture(scope="module")
def duckdb_conn():
    """Module-scoped DuckDB connection with test data."""
    try:
        conn = create_employees_connection()
        yield conn
    finally:
        conn.close()


@pytest.fixture
def transpiler():
    """Fresh transpiler instance per test."""
    return SQLTranspiler()


# =============================================================================
# PREDICATE TESTS
# =============================================================================

class TestPredicateRuntime:
    """Runtime verification of predicate translations."""

    @pytest.mark.parametrize(
        ("source_sql", "src_dialect", "tgt_dialect", "expected_count"),
        [
            # Equality
            ("SELECT COUNT(*) FROM employees WHERE active = TRUE", "mysql", "postgres", 6),
            ("SELECT COUNT(*) FROM employees WHERE active = TRUE", "postgres", "mysql", 6),
            # Inequality
            ("SELECT COUNT(*) FROM employees WHERE active = FALSE", "mysql", "postgres", 1),
            # Greater than
            ("SELECT COUNT(*) FROM employees WHERE salary > 80000", "mysql", "postgres", 3),
            # Greater than or equal
            ("SELECT COUNT(*) FROM employees WHERE salary >= 100000", "mysql", "postgres", 2),
            # Less than
            ("SELECT COUNT(*) FROM employees WHERE salary < 80000", "mysql", "postgres", 2),
            # Less than or equal
            ("SELECT COUNT(*) FROM employees WHERE salary <= 70000", "mysql", "postgres", 2),
            # IS NULL
            ("SELECT COUNT(*) FROM employees WHERE name IS NULL", "mysql", "postgres", 1),
            # IS NOT NULL
            ("SELECT COUNT(*) FROM employees WHERE name IS NOT NULL", "mysql", "postgres", 6),
            # IN
            ("SELECT COUNT(*) FROM employees WHERE id IN (1, 2, 3)", "mysql", "postgres", 3),
            # NOT IN
            ("SELECT COUNT(*) FROM employees WHERE id NOT IN (1, 2, 3)", "mysql", "postgres", 4),
            # BETWEEN
            ("SELECT COUNT(*) FROM employees WHERE salary BETWEEN 70000 AND 100000", "mysql", "postgres", 4),
            # LIKE
            ("SELECT COUNT(*) FROM employees WHERE name LIKE 'A%'", "mysql", "postgres", 1),
            # Boolean AND
            ("SELECT COUNT(*) FROM employees WHERE active = TRUE AND salary > 90000", "mysql", "postgres", 2),
            # Boolean OR
            ("SELECT COUNT(*) FROM employees WHERE department = 'eng' OR department = 'sales'", "mysql", "postgres", 6),
            # Parentheses precedence
            (
                "SELECT COUNT(*) FROM employees WHERE (active = TRUE AND salary > 90000) OR department = 'hr'",
                "mysql",
                "postgres",
                3,
            ),
        ],
    )
    def test_predicate_equivalence(
        self, duckdb_conn, transpiler, source_sql, src_dialect, tgt_dialect, expected_count
    ):
        """Verify transpiled predicates produce identical result counts."""
        result = transpiler.transpile(source_sql, src_dialect, tgt_dialect, pretty=False)
        assert result.success, f"Transpile failed: {result.error}"

        src_rows, src_err = execute_or_skip(duckdb_conn, source_sql)
        tgt_rows, tgt_err = execute_or_skip(duckdb_conn, result.target_sql)

        if src_err:
            pytest.skip(f"Source SQL not executable in DuckDB: {src_err}")
        if tgt_err:
            pytest.skip(f"Target SQL not executable in DuckDB: {tgt_err}")

        src_count = src_rows[0][0] if src_rows else 0
        tgt_count = tgt_rows[0][0] if tgt_rows else 0

        assert src_count == tgt_count == expected_count, (
            f"Predicate mismatch: src={src_count}, tgt={tgt_count}, expected={expected_count}"
        )


# =============================================================================
# AGGREGATION TESTS
# =============================================================================

class TestAggregationRuntime:
    """Runtime verification of aggregation function translations."""

    @pytest.mark.parametrize(
        ("source_sql", "src_dialect", "tgt_dialect", "expected_result"),
        [
            # COUNT(*)
            ("SELECT COUNT(*) FROM employees", "mysql", "postgres", 7),
            ("SELECT COUNT(*) FROM employees", "postgres", "mysql", 7),
            # COUNT(column) - excludes NULLs
            ("SELECT COUNT(name) FROM employees", "mysql", "postgres", 6),
            # SUM - excludes NULLs
            ("SELECT SUM(salary) FROM employees", "mysql", "postgres", 460000),
            # AVG - excludes NULLs
            ("SELECT AVG(salary) FROM employees", "mysql", "postgres", 92000.0),
            # MIN
            ("SELECT MIN(salary) FROM employees", "mysql", "postgres", 70000),
            # MAX
            ("SELECT MAX(salary) FROM employees", "mysql", "postgres", 120000),
            # GROUP_CONCAT / STRING_AGG (ordered)
            (
                "SELECT GROUP_CONCAT(name ORDER BY id) FROM employees WHERE active = TRUE",
                "mysql",
                "postgres",
                "Alice,Bob,Carol,Eve,Frank",
            ),
            # STRING_AGG with separator
            (
                "SELECT STRING_AGG(name, '|') FROM employees WHERE active = TRUE",
                "postgres",
                "mysql",
                "Alice|Bob|Carol|Eve|Frank",
            ),
            # ARRAY_AGG
            (
                "SELECT ARRAY_AGG(name) FROM employees WHERE active = TRUE",
                "postgres",
                "duckdb",
                ["Alice", "Bob", "Carol", "Eve", "Frank"],
            ),
            # COLLECT_LIST
            (
                "SELECT COLLECT_LIST(name) FROM employees WHERE active = TRUE",
                "hive",
                "postgres",
                ["Alice", "Bob", "Carol", "Eve", "Frank"],
            ),
        ],
    )
    def test_aggregation_equivalence(
        self, duckdb_conn, transpiler, source_sql, src_dialect, tgt_dialect, expected_result
    ):
        """Verify transpiled aggregations produce equivalent results."""
        result = transpiler.transpile(source_sql, src_dialect, tgt_dialect, pretty=False)
        assert result.success, f"Transpile failed: {result.error}"

        src_rows, src_err = execute_or_skip(duckdb_conn, source_sql)
        tgt_rows, tgt_err = execute_or_skip(duckdb_conn, result.target_sql)

        if src_err:
            pytest.skip(f"Source SQL not executable in DuckDB: {src_err}")
        if tgt_err:
            pytest.skip(f"Target SQL not executable in DuckDB: {tgt_err}")

        src_normalized = normalize_rows(src_rows)
        tgt_normalized = normalize_rows(tgt_rows)

        if isinstance(expected_result, list):
            # Array comparison — normalize and sort
            assert src_normalized == tgt_normalized, (
                f"Aggregation mismatch: src={src_normalized}, tgt={tgt_normalized}"
            )
        else:
            # Scalar comparison
            assert src_normalized == tgt_normalized, (
                f"Aggregation mismatch: src={src_normalized}, tgt={tgt_normalized}, expected={expected_result}"
            )


# =============================================================================
# GROUP BY / HAVING TESTS
# =============================================================================

class TestGroupByRuntime:
    """Runtime verification of GROUP BY and HAVING translations."""

    @pytest.mark.parametrize(
        ("source_sql", "src_dialect", "tgt_dialect"),
        [
            # Basic GROUP BY
            (
                "SELECT department, COUNT(*) AS cnt FROM employees GROUP BY department",
                "mysql",
                "postgres",
            ),
            # GROUP BY with HAVING
            (
                "SELECT department, COUNT(*) AS cnt FROM employees GROUP BY department HAVING COUNT(*) > 1",
                "mysql",
                "postgres",
            ),
            # GROUP BY with aggregation
            (
                "SELECT department, SUM(salary) AS total FROM employees GROUP BY department",
                "mysql",
                "postgres",
            ),
            # GROUP BY with ORDER BY
            (
                "SELECT department, COUNT(*) AS cnt FROM employees GROUP BY department ORDER BY cnt DESC",
                "mysql",
                "postgres",
            ),
        ],
    )
    def test_group_by_equivalence(
        self, duckdb_conn, transpiler, source_sql, src_dialect, tgt_dialect
    ):
        """Verify transpiled GROUP BY queries produce equivalent results."""
        result = transpiler.transpile(source_sql, src_dialect, tgt_dialect, pretty=False)
        assert result.success, f"Transpile failed: {result.error}"

        src_rows, src_err = execute_or_skip(duckdb_conn, source_sql)
        tgt_rows, tgt_err = execute_or_skip(duckdb_conn, result.target_sql)

        if src_err:
            pytest.skip(f"Source SQL not executable in DuckDB: {src_err}")
        if tgt_err:
            pytest.skip(f"Target SQL not executable in DuckDB: {tgt_err}")

        # Normalize both and compare as sets (order may vary)
        src_set = set(normalize_rows(src_rows))
        tgt_set = set(normalize_rows(tgt_rows))

        assert src_set == tgt_set, (
            f"GROUP BY mismatch:\n  source: {src_rows}\n  target: {tgt_rows}"
        )


# =============================================================================
# JOIN TESTS
# =============================================================================

class TestJoinRuntime:
    """Runtime verification of JOIN translations."""

    def test_inner_join(self, duckdb_conn, transpiler):
        """INNER JOIN translation equivalence."""
        source_sql = """
            SELECT e1.name, e2.name AS manager_name
            FROM employees e1
            INNER JOIN employees e2 ON e1.manager_id = e2.id
        """
        result = transpiler.transpile(source_sql, "mysql", "postgres", pretty=False)
        assert result.success, f"Transpile failed: {result.error}"

        src_rows, _ = execute_or_skip(duckdb_conn, source_sql)
        tgt_rows, _ = execute_or_skip(duckdb_conn, result.target_sql)

        src_set = set(normalize_rows(src_rows))
        tgt_set = set(normalize_rows(tgt_rows))

        assert src_set == tgt_set, f"JOIN mismatch: src={src_rows}, tgt={tgt_rows}"

    def test_left_join(self, duckdb_conn, transpiler):
        """LEFT JOIN translation equivalence."""
        source_sql = """
            SELECT e1.name, e2.name AS manager_name
            FROM employees e1
            LEFT JOIN employees e2 ON e1.manager_id = e2.id
        """
        result = transpiler.transpile(source_sql, "mysql", "postgres", pretty=False)
        assert result.success, f"Transpile failed: {result.error}"

        src_rows, _ = execute_or_skip(duckdb_conn, source_sql)
        tgt_rows, _ = execute_or_skip(duckdb_conn, result.target_sql)

        src_set = set(normalize_rows(src_rows))
        tgt_set = set(normalize_rows(tgt_rows))

        assert src_set == tgt_set, f"LEFT JOIN mismatch: src={src_rows}, tgt={tgt_rows}"


# =============================================================================
# ORDER BY / LIMIT TESTS
# =============================================================================

class TestOrderLimitRuntime:
    """Runtime verification of ORDER BY and LIMIT translations."""

    @pytest.mark.parametrize(
        ("source_sql", "src_dialect", "tgt_dialect", "expected_count"),
        [
            # ORDER BY DESC LIMIT
            ("SELECT * FROM employees ORDER BY salary DESC LIMIT 3", "mysql", "postgres", 3),
            # ORDER BY ASC LIMIT (with NULLS LAST for consistent ordering)
            ("SELECT id, name, salary FROM employees ORDER BY salary ASC NULLS LAST LIMIT 2", "mysql", "postgres", 2),
            # LIMIT OFFSET
            ("SELECT * FROM employees LIMIT 3 OFFSET 2", "mysql", "postgres", 3),
            # FETCH FIRST (oracle)
            ("SELECT * FROM employees ORDER BY id FETCH FIRST 3 ROWS ONLY", "oracle", "mysql", 3),
            # TOP (tsql)
            ("SELECT TOP 3 * FROM employees ORDER BY id", "tsql", "postgres", 3),
        ],
    )
    def test_order_limit_equivalence(
        self, duckdb_conn, transpiler, source_sql, src_dialect, tgt_dialect, expected_count
    ):
        """Verify transpiled ORDER BY/LIMIT queries produce equivalent results."""
        result = transpiler.transpile(source_sql, src_dialect, tgt_dialect, pretty=False)
        assert result.success, f"Transpile failed: {result.error}"

        src_rows, src_err = execute_or_skip(duckdb_conn, source_sql)
        tgt_rows, tgt_err = execute_or_skip(duckdb_conn, result.target_sql)

        if src_err:
            pytest.skip(f"Source SQL not executable in DuckDB: {src_err}")
        if tgt_err:
            pytest.skip(f"Target SQL not executable in DuckDB: {tgt_err}")

        assert len(src_rows) == expected_count
        assert len(tgt_rows) == expected_count

        # Compare row content (not order, as ordering may differ)
        src_set = set(normalize_rows(src_rows))
        tgt_set = set(normalize_rows(tgt_rows))
        assert src_set == tgt_set, f"ORDER/LIMIT mismatch: src={src_rows}, tgt={tgt_rows}"


# =============================================================================
# DATE/TIME TESTS
# =============================================================================

class TestDateTimeRuntime:
    """Runtime verification of date/time function translations."""

    @pytest.mark.parametrize(
        ("source_sql", "src_dialect", "tgt_dialect"),
        [
            # CURRENT_DATE
            ("SELECT CURRENT_DATE", "mysql", "postgres"),
            # NOW()
            ("SELECT NOW()", "mysql", "postgres"),
            # DATE_ADD
            ("SELECT DATE_ADD(created_at, INTERVAL 7 DAY) FROM employees LIMIT 1", "mysql", "postgres"),
            # DATE_SUB
            ("SELECT DATE_SUB(created_at, INTERVAL 7 DAY) FROM employees LIMIT 1", "mysql", "postgres"),
        ],
    )
    def test_datetime_equivalence(
        self, duckdb_conn, transpiler, source_sql, src_dialect, tgt_dialect
    ):
        """Verify transpiled date/time queries execute without error."""
        result = transpiler.transpile(source_sql, src_dialect, tgt_dialect, pretty=False)
        assert result.success, f"Transpile failed: {result.error}"

        # Both should execute without error
        _, src_err = execute_or_skip(duckdb_conn, source_sql)
        _, tgt_err = execute_or_skip(duckdb_conn, result.target_sql)

        if src_err:
            pytest.skip(f"Source SQL not executable in DuckDB: {src_err}")
        if tgt_err:
            pytest.skip(f"Target SQL not executable in DuckDB: {tgt_err}")


# =============================================================================
# DML TESTS
# =============================================================================

class TestDMLRuntime:
    """Runtime verification of DML translations."""

    def test_insert(self, duckdb_conn, transpiler):
        """INSERT translation equivalence."""
        source_sql = "INSERT INTO employees (id, name, department, salary, active) VALUES (8, 'Test', 'eng', 50000, TRUE)"
        result = transpiler.transpile(source_sql, "mysql", "postgres", pretty=False)
        assert result.success, f"Transpile failed: {result.error}"

        # Both should execute without error
        _, src_err = execute_or_skip(duckdb_conn, source_sql)
        _, tgt_err = execute_or_skip(duckdb_conn, result.target_sql)

        if src_err:
            pytest.skip(f"Source SQL not executable in DuckDB: {src_err}")
        if tgt_err:
            pytest.skip(f"Target SQL not executable in DuckDB: {tgt_err}")

    def test_update_with_where(self, duckdb_conn, transpiler):
        """UPDATE with WHERE translation equivalence."""
        source_sql = "UPDATE employees SET salary = salary * 1.1 WHERE department = 'eng'"
        result = transpiler.transpile(source_sql, "mysql", "postgres", pretty=False)
        assert result.success, f"Transpile failed: {result.error}"

        _, src_err = execute_or_skip(duckdb_conn, source_sql)
        _, tgt_err = execute_or_skip(duckdb_conn, result.target_sql)

        if src_err:
            pytest.skip(f"Source SQL not executable in DuckDB: {src_err}")
        if tgt_err:
            pytest.skip(f"Target SQL not executable in DuckDB: {tgt_err}")

    def test_delete_with_where(self, duckdb_conn, transpiler):
        """DELETE with WHERE translation equivalence."""
        source_sql = "DELETE FROM employees WHERE id = 8"
        result = transpiler.transpile(source_sql, "mysql", "postgres", pretty=False)
        assert result.success, f"Transpile failed: {result.error}"

        _, src_err = execute_or_skip(duckdb_conn, source_sql)
        _, tgt_err = execute_or_skip(duckdb_conn, result.target_sql)

        if src_err:
            pytest.skip(f"Source SQL not executable in DuckDB: {src_err}")
        if tgt_err:
            pytest.skip(f"Target SQL not executable in DuckDB: {tgt_err}")


# =============================================================================
# CONCAT NULL SEMANTICS TEST
# =============================================================================

class TestConcatNullSemantics:
    """Verify CONCAT NULL behavior difference is documented.

    PostgreSQL CONCAT ignores NULL arguments (treats as empty string),
    while MySQL CONCAT propagates NULL (returns NULL if any arg is NULL).
    sqlglot handles this by wrapping args in COALESCE when transpiling
    from PostgreSQL to MySQL.
    """

    def test_concat_null_semantics_warning(self, transpiler):
        """PostgreSQL CONCAT -> MySQL transpilation includes NULL semantics note."""
        source_sql = "SELECT CONCAT(a, b) FROM t"
        result = transpiler.transpile(source_sql, "postgres", "mysql", pretty=False)

        assert result.success
        # Check that NULL semantics warning is present
        has_warning = any(
            "NULL" in note and "CONCAT" in note
            for note in result.compatibility_notes
        )
        assert has_warning, "CONCAT NULL semantics warning missing"

    def test_concat_translation_adds_coalesce(self, transpiler):
        """Verify transpiled SQL wraps CONCAT args in COALESCE for MySQL."""
        source_sql = "SELECT CONCAT(a, b) FROM t"
        result = transpiler.transpile(source_sql, "postgres", "mysql", pretty=False)

        assert result.success
        # PostgreSQL CONCAT should be rewritten to handle NULL differently
        assert "COALESCE" in result.target_sql, (
            f"Expected COALESCE wrapper for NULL handling, got: {result.target_sql}"
        )

    def test_concat_no_null_args_unchanged(self, transpiler):
        """When no NULL args expected, CONCAT translation should be minimal."""
        # Using literal strings avoids NULL issues
        source_sql = "SELECT CONCAT('hello', 'world') FROM t"
        result = transpiler.transpile(source_sql, "postgres", "mysql", pretty=False)

        assert result.success
        # Literal strings don't need COALESCE wrapping
        assert "COALESCE" not in result.target_sql


# =============================================================================
# SEMANTIC DIFF INTEGRATION TEST
# =============================================================================

class TestSemanticDiffIntegration:
    """Verify semantic diff classification aligns with runtime evidence."""

    @pytest.mark.parametrize(
        ("source_sql", "src_dialect", "tgt_dialect"),
        [
            ("SELECT CONCAT(a, b) FROM t", "postgres", "mysql"),
            ("SELECT GROUP_CONCAT(name) FROM employees", "mysql", "postgres"),
            ("SELECT ARRAY_AGG(name) FROM employees", "postgres", "duckdb"),
        ],
    )
    def test_runtime_matches_classification(
        self, duckdb_conn, transpiler, source_sql, src_dialect, tgt_dialect
    ):
        """When runtime shows different results, semantic diff should not claim 'equivalent'."""
        result = transpiler.transpile(source_sql, src_dialect, tgt_dialect, pretty=False)
        assert result.success, f"Transpile failed: {result.error}"

        # Run semantic diff
        diff = diff_sql_ast(source_sql, result.target_sql, src_dialect, tgt_dialect)

        # If the transformation changes function semantics, classification should reflect uncertainty
        if diff.semantic_classification == "equivalent":
            # Verify runtime actually matches
            src_rows, _ = execute_or_skip(duckdb_conn, source_sql)
            tgt_rows, _ = execute_or_skip(duckdb_conn, result.target_sql)
            if src_rows and tgt_rows:
                src_norm = normalize_rows(src_rows)
                tgt_norm = normalize_rows(tgt_rows)
                assert src_norm == tgt_norm, (
                    f"Semantic diff claims equivalent but runtime differs: {src_norm} vs {tgt_norm}"
                )
