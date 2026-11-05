"""Batch 1 schema-aware multi-column ORDER BY contracts."""

import pytest
import sqlglot

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_schema import SchemaContext
from backend.core.nl2sql_pipeline.ir import build_ir
from backend.core.nl2sql_pipeline.renderer import render_sql


USERS_SCHEMA = SchemaContext.from_mapping({
    "tables": [
        {"name": "users", "columns": [
            {"name": "id"}, {"name": "name"}, {"name": "email"}, {"name": "nickname"},
            {"name": "created_at"}, {"name": "status"}, {"name": "phone"},
            {"name": "age"}, {"name": "price"},
        ]},
        {"name": "orders", "columns": [{"name": "id"}, {"name": "user_id"}, {"name": "amount"}]},
    ],
    "relationships": [{
        "from_table": "orders", "from_column": "user_id",
        "to_table": "users", "to_column": "id",
    }],
})


def generate(text: str, schema=USERS_SCHEMA):
    return NL2SQLGenerator().generate(text, "postgres", schema=schema)


def body(result):
    assert result.success, result.explanation
    return " ".join(line.strip() for line in result.sql.splitlines() if not line.strip().startswith("--"))


@pytest.mark.parametrize("text,order", [
    ("show users ordered by name, email", "ORDER BY name ASC, email ASC"),
    ("show users ordered by name and email", "ORDER BY name ASC, email ASC"),
    ("show users ordered by name ascending, email descending", "ORDER BY name ASC, email DESC"),
    ("show users order by name asc, email desc", "ORDER BY name ASC, email DESC"),
    ("show users sorted by name and email", "ORDER BY name ASC, email ASC"),
    ("show users ordered by name, email and created_at", "ORDER BY name ASC, email ASC, created_at ASC"),
])
def test_schema_multi_ordering(text, order):
    assert order in body(generate(text))


def test_single_ordering_and_limit_regressions():
    assert "ORDER BY name ASC" in body(generate("show users ordered by name"))
    assert "ORDER BY created_at ASC" in body(generate("show users ordered by created_at"))
    result = generate("find top 5 users by price")
    assert result.success
    assert "LIMIT 5" in body(result)


@pytest.mark.parametrize("text", [
    "show users ordered by unknown_col, name",
    "show users ordered by name, unknown_col",
    "show users ordered by name, name",
    "show users ordered by name,,email",
    "show users ordered by ,name",
    "show users ordered by name,",
    "show users ordered by name or email",
    "show users ordered by name foo, email",
    "show users ordered by lower(name), email",
    "show users ordered by 'name', email",
    "show users ordered by name, email, created_at, id, status, phone",
])
def test_schema_multi_ordering_invalid_forms_fail_closed(text):
    result = generate(text)
    assert result.success is False
    assert result.sql is None


def test_qualified_subject_columns_are_supported():
    result = generate("show users ordered by users.name, users.email")
    assert result.success
    assert "ORDER BY name ASC, email ASC" in result.sql


@pytest.mark.parametrize("text", [
    "show users group by name ordered by email, created_at",
    "count orders by user_id ordered by id, amount",
])
def test_multi_ordering_combinations_fail_closed_in_batch_one(text):
    result = generate(text)
    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("text,order", [
    ("find users whose nickname is bob ordered by name, email", "ORDER BY name ASC, email ASC"),
    ("users joined on orders.user_id = users.id ordered by name, email", "ORDER BY name ASC, email ASC"),
    ("users joined with orders ordered by name, email", "ORDER BY name ASC, email ASC"),
])
def test_multi_ordering_composes_with_subject_whose_and_joins(text, order):
    result = generate(text)
    assert result.success, result.explanation
    assert order in body(result)


def test_multi_ordering_rejects_join_target_column():
    result = generate("users joined with orders ordered by amount, name")
    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("text,expected", [
    ("find distinct user emails and names ordered by email, name", "ORDER BY email ASC, name ASC"),
])
def test_distinct_multi_ordering_requires_all_projected(text, expected):
    result = generate(text)
    assert result.success
    assert expected in body(result)


@pytest.mark.parametrize("text", [
    "find distinct user emails ordered by email, name",
    "find distinct users ordered by name, email",
])
def test_distinct_multi_ordering_rejects_unprojected_columns(text):
    result = generate(text)
    assert result.success is False
    assert result.sql is None


def test_multi_ordering_no_schema_outputs_are_unchanged():
    expected = {
        "show users ordered by name, email": ("name", "email"),
        "show users ordered by name and email": ("name", "email"),
        "show users sorted by name and email": ("ORDER BY name ASC",),
    }
    generator = NL2SQLGenerator()
    for text, fragments in expected.items():
        first = generator.generate(text, "postgres")
        second = generator.generate(text, "postgres")
        assert first.success and second.success
        assert first.sql == second.sql
        for fragment in fragments:
            assert fragment in first.sql
        assert first.schema_used is False
        assert first.suggestions == second.suggestions


def test_query_ir_preserves_legacy_tuple_and_new_list():
    legacy = build_ir(
        "SELECT", "users", ["*"], [], [], [],
        ("name", "ASC"), None, [], False, "postgres",
    )
    sql, _, _, _ = render_sql(legacy)
    assert "ORDER BY name ASC" in sql

    multi = build_ir(
        "SELECT", "users", ["*"], [], [], [],
        None, None, [], False, "postgres",
        orderings=[("name", "ASC"), ("email", "DESC")],
    )
    sql, explanation, _, _ = render_sql(multi)
    assert "ORDER BY name ASC, email DESC" in sql
    assert "排序: name ASC, email DESC" in explanation


@pytest.mark.parametrize("dialect", [
    "mysql", "postgres", "oracle", "tsql", "hive", "spark",
    "trino", "databricks", "snowflake", "redshift", "clickhouse", "duckdb",
])
def test_multi_ordering_sql_parses_in_all_dialects(dialect):
    result = NL2SQLGenerator().generate(
        "show users ordered by name ascending, email descending",
        dialect,
        schema=USERS_SCHEMA,
    )
    assert result.success
    assert sqlglot.parse_one(result.sql, read=dialect) is not None


def test_multi_ordering_is_deterministic():
    first = generate("show users ordered by name ascending, email descending")
    second = generate("show users ordered by name ascending, email descending")
    assert first.success and second.success
    assert first.sql == second.sql
