"""Semantic test corpus for runtime verification.

Each entry is a (source_dialect, source_sql, target_dialect, expected_category) tuple.

Categories:
    EQUIVALENT: result sets match exactly (order matters for ordered queries)
    STRUCTURALLY_EQUIVALENT: same rows but order may differ
    KNOWN_DIFFERENCE: documented semantic gap between dialects
    PARSE_ERROR: target SQL fails to parse in target dialect
    UNKNOWN: source or target not executable in DuckDB
"""
from backend.tests.semantic.runtime_helpers import SemanticCategory

# (source_dialect, source_sql, target_dialect, expected_category)
RUNTIME_CASES = [
    # ================================================================
    # PREDICATES
    # ================================================================
    ("mysql", "SELECT COUNT(*) FROM employees WHERE active = TRUE", "postgres", SemanticCategory.EQUIVALENT),
    ("mysql", "SELECT COUNT(*) FROM employees WHERE salary > 80000", "postgres", SemanticCategory.EQUIVALENT),
    ("mysql", "SELECT COUNT(*) FROM employees WHERE name IS NULL", "postgres", SemanticCategory.EQUIVALENT),
    ("mysql", "SELECT COUNT(*) FROM employees WHERE name IS NOT NULL", "postgres", SemanticCategory.EQUIVALENT),
    ("mysql", "SELECT COUNT(*) FROM employees WHERE id IN (1, 2, 3)", "postgres", SemanticCategory.EQUIVALENT),
    ("mysql", "SELECT COUNT(*) FROM employees WHERE id NOT IN (1, 2, 3)", "postgres", SemanticCategory.EQUIVALENT),
    ("mysql", "SELECT COUNT(*) FROM employees WHERE salary BETWEEN 70000 AND 100000", "postgres", SemanticCategory.EQUIVALENT),
    ("mysql", "SELECT COUNT(*) FROM employees WHERE name LIKE 'A%'", "postgres", SemanticCategory.EQUIVALENT),
    # Boolean combinations
    ("mysql", "SELECT COUNT(*) FROM employees WHERE active = TRUE AND salary > 90000", "postgres", SemanticCategory.EQUIVALENT),
    ("mysql", "SELECT COUNT(*) FROM employees WHERE active = TRUE OR department = 'sales'", "postgres", SemanticCategory.EQUIVALENT),
    ("mysql", "SELECT COUNT(*) FROM employees WHERE (active = TRUE AND salary > 90000) OR department = 'sales'", "postgres", SemanticCategory.EQUIVALENT),

    # ================================================================
    # AGGREGATION - Non-DISTINCT (deterministic ordering)
    # ================================================================
    ("mysql", "SELECT GROUP_CONCAT(name) FROM employees WHERE active = TRUE", "postgres", SemanticCategory.EQUIVALENT),
    ("mysql", "SELECT GROUP_CONCAT(name ORDER BY id) FROM employees", "postgres", SemanticCategory.EQUIVALENT),
    # SEPARATOR not supported by DuckDB natively - skip for runtime
    ("mysql", "SELECT GROUP_CONCAT(name SEPARATOR '|') FROM employees WHERE active = TRUE", "postgres", SemanticCategory.KNOWN_DIFFERENCE),
    ("postgres", "SELECT STRING_AGG(name, ',') FROM employees WHERE active = TRUE", "mysql", SemanticCategory.KNOWN_DIFFERENCE),
    ("postgres", "SELECT STRING_AGG(name, '|') FROM employees", "mysql", SemanticCategory.KNOWN_DIFFERENCE),
    # COUNT, SUM, AVG, MIN, MAX
    ("mysql", "SELECT COUNT(*), COUNT(name), SUM(salary), AVG(salary), MIN(salary), MAX(salary) FROM employees", "postgres", SemanticCategory.EQUIVALENT),
    ("mysql", "SELECT COUNT(*) FROM employees WHERE active = TRUE", "postgres", SemanticCategory.EQUIVALENT),
    ("mysql", "SELECT SUM(salary) FROM employees WHERE active = TRUE", "postgres", SemanticCategory.EQUIVALENT),
    ("mysql", "SELECT AVG(salary) FROM employees WHERE active = TRUE", "postgres", SemanticCategory.EQUIVALENT),
    ("mysql", "SELECT MIN(salary) FROM employees", "postgres", SemanticCategory.EQUIVALENT),
    ("mysql", "SELECT MAX(salary) FROM employees", "postgres", SemanticCategory.EQUIVALENT),

    # ================================================================
    # AGGREGATION - DISTINCT (non-deterministic ordering across dialects)
    # ================================================================
    ("mysql", "SELECT GROUP_CONCAT(DISTINCT department) FROM employees", "postgres", SemanticCategory.KNOWN_DIFFERENCE),
    ("mysql", "SELECT GROUP_CONCAT(DISTINCT name) FROM employees", "postgres", SemanticCategory.KNOWN_DIFFERENCE),
    ("postgres", "SELECT ARRAY_AGG(DISTINCT name) FROM employees", "mysql", SemanticCategory.KNOWN_DIFFERENCE),
    ("postgres", "SELECT STRING_AGG(DISTINCT department, ',') FROM employees", "mysql", SemanticCategory.KNOWN_DIFFERENCE),

    # ================================================================
    # AGGREGATION - Nested expressions
    # ================================================================
    ("mysql", "SELECT GROUP_CONCAT(CONCAT(name, '-', department)) FROM employees", "postgres", SemanticCategory.EQUIVALENT),
    ("postgres", "SELECT STRING_AGG(CONCAT(name, '_', department), '|') FROM employees", "mysql", SemanticCategory.KNOWN_DIFFERENCE),

    # ================================================================
    # AGGREGATION - Array functions
    # ================================================================
    ("postgres", "SELECT ARRAY_AGG(name) FROM employees WHERE active = TRUE", "duckdb", SemanticCategory.EQUIVALENT),
    ("duckdb", "SELECT ARRAY_AGG(name) FROM employees WHERE active = TRUE", "postgres", SemanticCategory.EQUIVALENT),
    ("postgres", "SELECT ARRAY_AGG(name) FROM employees", "hive", SemanticCategory.KNOWN_DIFFERENCE),
    ("hive", "SELECT COLLECT_LIST(name) FROM employees WHERE active = TRUE", "postgres", SemanticCategory.KNOWN_DIFFERENCE),

    # ================================================================
    # GROUP BY / HAVING
    # ================================================================
    ("mysql", "SELECT department, COUNT(*) AS cnt FROM employees GROUP BY department", "postgres", SemanticCategory.EQUIVALENT),
    ("mysql", "SELECT department, COUNT(*) AS cnt FROM employees GROUP BY department HAVING COUNT(*) > 1", "postgres", SemanticCategory.EQUIVALENT),
    ("mysql", "SELECT department, SUM(salary) AS total FROM employees GROUP BY department ORDER BY total DESC", "postgres", SemanticCategory.EQUIVALENT),

    # ================================================================
    # JOIN
    # ================================================================
    ("mysql", "SELECT e1.name, e2.name AS peer_name FROM employees e1 JOIN employees e2 ON e1.department = e2.department AND e1.id < e2.id", "postgres", SemanticCategory.EQUIVALENT),

    # ================================================================
    # ORDER BY / LIMIT
    # ================================================================
    ("mysql", "SELECT * FROM employees ORDER BY salary DESC LIMIT 3", "postgres", SemanticCategory.EQUIVALENT),
    ("mysql", "SELECT * FROM employees LIMIT 10 OFFSET 2", "postgres", SemanticCategory.EQUIVALENT),
    ("oracle", "SELECT * FROM employees ORDER BY id FETCH FIRST 5 ROWS ONLY", "mysql", SemanticCategory.EQUIVALENT),
    ("tsql", "SELECT TOP 3 * FROM employees ORDER BY salary DESC", "postgres", SemanticCategory.KNOWN_DIFFERENCE),
    ("mysql", "SELECT * FROM employees WHERE active = TRUE ORDER BY salary DESC NULLS LAST LIMIT 2", "postgres", SemanticCategory.EQUIVALENT),

    # ================================================================
    # DATE/TIME (where DuckDB can execute both)
    # ================================================================
    ("mysql", "SELECT CURRENT_DATE FROM employees LIMIT 1", "postgres", SemanticCategory.EQUIVALENT),
    ("mysql", "SELECT NOW() FROM employees LIMIT 1", "postgres", SemanticCategory.EQUIVALENT),
    ("mysql", "SELECT DATE_ADD(created_at, INTERVAL 7 DAY) FROM employees LIMIT 1", "postgres", SemanticCategory.EQUIVALENT),
]
