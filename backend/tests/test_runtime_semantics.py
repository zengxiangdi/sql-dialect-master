import os

import pytest

from backend.core.semantic_diff import diff_sql_ast
from backend.core.transpiler import SQLTranspiler


duckdb = pytest.importorskip("duckdb")
psycopg = pytest.importorskip("psycopg")


POSTGRES_DSN = os.getenv(
    "SDM_TEST_POSTGRES_DSN",
    "postgresql://postgres:postgres@127.0.0.1:5432/sql_dialect_test",
)


def _normalize_rows(rows):
    normalized = []
    for row in rows:
        normalized.append(
            tuple(float(value) if hasattr(value, "as_integer_ratio") or value.__class__.__name__ == "Decimal" else value for value in row)
        )
    return normalized


def _execute_duckdb(connection, sql):
    return _normalize_rows(connection.execute(sql).fetchall())


def _execute_postgres(connection, sql):
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return _normalize_rows(cursor.fetchall())


def _prepare_duckdb(connection):
    connection.execute("DROP TABLE IF EXISTS employees")
    connection.execute(
        """
        CREATE TABLE employees (
            id INTEGER,
            department VARCHAR,
            salary INTEGER,
            active BOOLEAN
        )
        """
    )
    connection.executemany(
        "INSERT INTO employees VALUES (?, ?, ?, ?)",
        [
            (1, "engineering", 100000, True),
            (2, "engineering", 120000, True),
            (3, "sales", 80000, True),
            (4, "sales", 70000, False),
        ],
    )


def _prepare_postgres(connection):
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS employees")
        cursor.execute(
            """
            CREATE TABLE employees (
                id INTEGER,
                department TEXT,
                salary INTEGER,
                active BOOLEAN
            )
            """
        )
        cursor.executemany(
            "INSERT INTO employees VALUES (%s, %s, %s, %s)",
            [
                (1, "engineering", 100000, True),
                (2, "engineering", 120000, True),
                (3, "sales", 80000, True),
                (4, "sales", 70000, False),
            ],
        )
    connection.commit()


@pytest.fixture(scope="module")
def duckdb_connection():
    connection = duckdb.connect(database=":memory:")
    _prepare_duckdb(connection)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture(scope="module")
def postgres_connection():
    try:
        connection = psycopg.connect(POSTGRES_DSN)
    except Exception as exc:
        pytest.skip(f"PostgreSQL runtime test database unavailable: {exc}")

    try:
        _prepare_postgres(connection)
        yield connection
    finally:
        connection.close()


QUERY = """
SELECT department, COUNT(*) AS employee_count, AVG(salary) AS avg_salary
FROM employees
WHERE active = TRUE
GROUP BY department
ORDER BY department
"""


@pytest.mark.parametrize(
    ("source", "target", "source_sql", "target_engine"),
    [
        ("postgres", "duckdb", QUERY, "duckdb"),
        ("duckdb", "postgres", QUERY, "postgres"),
    ],
)
def test_transpiled_sql_matches_source_runtime(
    source,
    target,
    source_sql,
    target_engine,
    duckdb_connection,
    postgres_connection,
):
    transpiler = SQLTranspiler()
    result = transpiler.transpile(source_sql, source, target, pretty=False, validate=True)
    assert result.success, result.error
    assert result.target_sql

    semantic = diff_sql_ast(
        source_sql,
        result.target_sql,
        source_dialect=source,
        target_dialect=target,
    )
    assert semantic.equivalent, semantic.differences

    if source == "postgres":
        source_rows = _execute_postgres(postgres_connection, source_sql)
    else:
        source_rows = _execute_duckdb(duckdb_connection, source_sql)

    if target_engine == "postgres":
        target_rows = _execute_postgres(postgres_connection, result.target_sql)
    else:
        target_rows = _execute_duckdb(duckdb_connection, result.target_sql)

    assert target_rows == source_rows
