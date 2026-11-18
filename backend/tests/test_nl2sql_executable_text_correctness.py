"""Regression coverage for executable-text NL2SQL intent detection."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_schema import SchemaContext


def generate(text: str, schema: SchemaContext | None = None, dialect: str = "postgres"):
    return NL2SQLGenerator().generate(text, dialect, schema=schema)


def products_schema() -> SchemaContext:
    return SchemaContext.from_mapping(
        {
            "tables": [
                {
                    "name": "products",
                    "columns": [
                        {"name": "id"},
                        {"name": "date"},
                        {"name": "amount"},
                        {"name": "status"},
                    ],
                    "primary_key": ["id"],
                },
                {
                    "name": "users",
                    "columns": [{"name": "id"}, {"name": "status"}],
                    "primary_key": ["id"],
                },
                {
                    "name": "orders",
                    "columns": [{"name": "id"}, {"name": "user_id"}, {"name": "status"}],
                    "primary_key": ["id"],
                },
            ],
            "relationships": [
                {
                    "from_table": "users",
                    "from_column": "id",
                    "to_table": "orders",
                    "to_column": "user_id",
                }
            ],
        }
    )


@pytest.mark.parametrize(
    "literal,forbidden",
    [
        ("limit 5", "LIMIT"),
        ("top 10", "ORDER BY"),
        ("order by id", "ORDER BY"),
        ("group by id", "GROUP BY"),
        ("distinct", "SELECT DISTINCT"),
        ("sum", "SUM("),
        ("count", "COUNT("),
        ("avg", "AVG("),
        ("min", "MIN("),
        ("max", "MAX("),
    ],
)
def test_no_schema_quoted_structural_words_stay_literals(literal: str, forbidden: str):
    result = generate(f"show users where status = '{literal}'")

    assert result.success, result.explanation
    assert f"status = '{literal}'" in result.sql
    assert forbidden not in result.sql


def test_no_schema_quoted_large_limit_does_not_trigger_global_guard():
    result = generate("show users where status = 'limit 1000001'")

    assert result.success, result.explanation
    assert "status = 'limit 1000001'" in result.sql
    assert "LIMIT" not in result.sql


@pytest.mark.parametrize(
    "comment",
    [
        "-- top 10 order by id group by status sum count distinct orders",
        "/* top 10 order by id group by status sum count distinct orders */",
    ],
)
def test_no_schema_comments_do_not_create_structure(comment: str):
    result = generate(f"show users where status = 'active' {comment}")

    assert result.success, result.explanation
    assert "status = 'active'" in result.sql
    assert "ORDER BY" not in result.sql
    assert "GROUP BY" not in result.sql
    assert "LIMIT" not in result.sql
    assert "SUM(" not in result.sql and "COUNT(" not in result.sql


@pytest.mark.parametrize(
    "text",
    [
        "find top 10 products from last 7 days",
        "find products from last 7 days top 10",
    ],
)
def test_top_n_and_date_keep_clause_order_and_structural_limit(text: str):
    result = generate(text)

    assert result.success, result.explanation
    sql = result.sql
    assert sql.index("WHERE") < sql.index("ORDER BY") < sql.index("LIMIT")
    assert "LIMIT 10" in sql
    assert "LIMIT 7" not in sql


def test_date_without_top_has_no_limit():
    result = generate("find products from last 7 days")

    assert result.success, result.explanation
    assert "WHERE" in result.sql
    assert "LIMIT" not in result.sql


@pytest.mark.parametrize(
    "text",
    [
        "find top 10 products from last 7 days",
        "find products from last 7 days top 10",
    ],
)
def test_schema_top_n_and_date_keep_structural_limit(text: str):
    result = generate(text, products_schema())

    assert result.success, result.explanation
    assert "WHERE" in result.sql
    assert "LIMIT 10" in result.sql
    assert "LIMIT 7" not in result.sql


def test_top_date_sql_executes_in_duckdb_when_available():
    duckdb = pytest.importorskip("duckdb")
    result = generate("find top 10 products from last 7 days")
    assert result.success, result.explanation

    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE TABLE products (id INTEGER, date DATE, amount INTEGER)")
        connection.executemany(
            "INSERT INTO products VALUES (?, CURRENT_DATE, ?)",
            [(index, index) for index in range(12)],
        )
        rows = connection.execute(result.sql.split("\n", 1)[1]).fetchall()
        assert len(rows) == 10
    finally:
        connection.close()


@pytest.mark.parametrize("literal", ["orders", "products"])
def test_schema_table_literals_do_not_create_mentions(literal: str):
    result = generate(f"show users where status = '{literal}'", products_schema())

    assert result.success, result.explanation
    assert f"status = '{literal}'" in result.sql
    assert "JOIN orders" not in result.sql
    assert "JOIN products" not in result.sql


def test_schema_table_mentions_ignore_comments_but_keep_real_join():
    context = products_schema()
    commented = generate("show users -- orders products", context)
    joined = generate("show users joined with orders", context)

    assert commented.success, commented.explanation
    assert "JOIN" not in commented.sql
    assert joined.success, joined.explanation
    assert "JOIN orders" in joined.sql


def test_real_order_outside_literal_remains_visible():
    result = generate(
        "show products where status = 'order by id' ordered by amount desc",
        products_schema(),
    )

    assert result.success, result.explanation
    assert "status = 'order by id'" in result.sql
    assert "ORDER BY amount DESC" in result.sql


@pytest.mark.parametrize("literal", ["count", "sum", "avg", "min", "max"])
def test_schema_aggregate_keywords_in_literals_do_not_create_aggregates(literal: str):
    result = generate(f"show users where status = '{literal}'", products_schema())

    assert result.success, result.explanation
    assert "status =" in result.sql
    assert all(function not in result.sql for function in ("COUNT(", "SUM(", "AVG(", "MIN(", "MAX("))


def test_schema_aggregate_keywords_in_comments_do_not_create_aggregates():
    result = generate(
        "show users where status = 'active' /* sum count avg min max */",
        products_schema(),
    )

    assert result.success, result.explanation
    assert "status = 'active'" in result.sql
    assert all(function not in result.sql for function in ("COUNT(", "SUM(", "AVG(", "MIN(", "MAX("))


def test_schema_real_count_intent_is_preserved():
    result = generate("count users", products_schema())

    assert result.success, result.explanation
    assert "COUNT(*)" in result.sql


@pytest.mark.parametrize("text", ["show distinct users", "show unique users"])
def test_no_schema_distinct_and_unique_are_preserved(text: str):
    result = generate(text)

    assert result.success, result.explanation
    assert "SELECT DISTINCT *" in result.sql


def test_no_schema_quoted_distinct_is_not_projection_distinct():
    result = generate("show users where status = 'distinct'")

    assert result.success, result.explanation
    assert "SELECT DISTINCT" not in result.sql


def test_schema_distinct_regression():
    result = generate("show distinct users", products_schema())

    assert result.success, result.explanation
    assert "SELECT DISTINCT" in result.sql


def test_intent_and_generation_are_stable_across_hash_seeds():
    script = """
import json
from backend.core.nl2sql import NL2SQLGenerator

result = NL2SQLGenerator().generate('show users with names and emails', 'postgres')
print(json.dumps({
    'sql': result.sql,
    'explanation': result.explanation,
    'evidence': result.evidence.to_dict() if result.evidence else None,
}, sort_keys=True))
"""
    outputs = []
    for seed in ("0", "1", "2"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        outputs.append(json.loads(completed.stdout))

    assert outputs[0] == outputs[1] == outputs[2]
