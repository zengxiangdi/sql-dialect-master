"""P1.3 schema-aware ``joined with`` contracts."""

import pytest
import sqlglot

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_schema import SchemaContext


def schema_context(*, relationships=True, duplicate=False, reverse=False):
    tables = [
        {"name": "users", "columns": [{"name": "id"}, {"name": "name"}, {"name": "status"}, {"name": "nickname"}]},
        {"name": "orders", "columns": [{"name": "id"}, {"name": "user_id"}]},
        {"name": "employees", "columns": [{"name": "id"}, {"name": "department_id"}]},
        {"name": "departments", "columns": [{"name": "id"}]},
    ]
    rels = []
    if relationships:
        rels = [
            {
                "from_table": "users" if reverse else "orders",
                "from_column": "id" if reverse else "user_id",
                "to_table": "orders" if reverse else "users",
                "to_column": "user_id" if reverse else "id",
            },
            {"from_table": "employees", "from_column": "department_id", "to_table": "departments", "to_column": "id"},
        ]
    if duplicate:
        rels.append(dict(rels[0]))
    return SchemaContext.from_mapping({"tables": tables, "relationships": rels})


def generate(text: str, schema=None, *, dialect="postgres"):
    return NL2SQLGenerator().generate(text, dialect, schema=schema)


def sql_body(result):
    assert result.success, result.explanation
    return " ".join(
        line.strip() for line in result.sql.splitlines()
        if not line.strip().startswith("--")
    )


@pytest.mark.parametrize("text,join_type", [
    ("users joined with orders", "INNER JOIN"),
    ("users left joined with orders", "LEFT JOIN"),
    ("users right joined with orders", "RIGHT JOIN"),
    ("users inner joined with orders", "INNER JOIN"),
    ("employees joined with departments", "INNER JOIN"),
])
def test_joined_with_renders_relationship_join(text, join_type):
    body = sql_body(generate(text, schema_context()))
    assert join_type in body
    if "employees" in text:
        assert "ON employees.department_id = departments.id" in body
    else:
        assert "ON orders.user_id = users.id" in body


def test_joined_with_accepts_reverse_relationship_declaration():
    body = sql_body(generate("orders joined with users", schema_context(reverse=True)))
    assert body.startswith("SELECT * FROM orders INNER JOIN users")
    assert "ON users.id = orders.user_id" in body


def test_joined_with_masks_target_from_projection():
    body = sql_body(generate("show user names joined with orders", schema_context()))
    assert body.startswith("SELECT name FROM users INNER JOIN orders")
    assert "orders" in body


@pytest.mark.parametrize("text", [
    "users joined with orders where status = 'active'",
    "users joined with orders whose nickname is bob",
])
def test_joined_with_preserves_where_and_whose(text):
    body = sql_body(generate(text, schema_context()))
    assert "INNER JOIN orders ON orders.user_id = users.id" in body
    assert "WHERE" in body
    if "whose" in text:
        assert "nickname = 'bob'" in body
    else:
        assert "status = 'active'" in body


@pytest.mark.parametrize("schema", [
    schema_context(relationships=False),
    schema_context(duplicate=True),
])
def test_joined_with_requires_one_raw_relationship(schema):
    result = generate("users joined with orders", schema)
    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("text", [
    "users joined with unknown",
    "users joined with users",
    "users joined with orders on orders.user_id = users.id",
    "users joined with orders joined on orders.user_id = users.id",
    "users and orders joined with departments",
    "users and orders joined with orders",
    "users joined with orders group by id",
    "users joined with orders per user",
    "users joined with orders each user",
    "users joined with orders 每个用户",
])
def test_joined_with_unsupported_or_ambiguous_forms_fail_closed(text):
    result = generate(text, schema_context())
    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("text", [
    "users with orders",
    "users who have orders",
])
def test_bare_with_and_existence_keep_exists_semantics(text):
    body = sql_body(generate(text, schema_context()))
    assert "WHERE EXISTS" in body
    assert "INNER JOIN" not in body


@pytest.mark.parametrize("text,fragment", [
    ("users join orders", "INNER JOIN orders ON users.id = orders.user_id"),
    ("users left join orders", "LEFT JOIN orders ON users.id = orders.user_id"),
])
def test_existing_physical_join_paths_remain(text, fragment):
    assert fragment in sql_body(generate(text, schema_context()))


def test_plain_joined_employees_departments_remains_fail_closed():
    result = generate("employees joined departments", schema_context())
    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("text", [
    "users joined with orders",
    "users left joined with orders",
    "users right joined with orders",
    "users with orders",
    "users join orders",
    "users left join orders",
    "employees joined departments",
])
def test_no_schema_outputs_remain_legacy(text):
    result = generate(text, None)
    assert result.schema_used is False
    assert result.success
    body = sql_body(result)
    if "joined with orders" in text or text == "users with orders":
        assert "WHERE EXISTS" in body
    elif text == "employees joined departments":
        assert "INNER JOIN departments ON employees.dept_id = departments.id" in body
    elif "left join" in text and "joined" not in text:
        assert "LEFT JOIN orders ON users.id = orders.user_id" in body
    else:
        assert "INNER JOIN orders ON users.id = orders.user_id" in body


@pytest.mark.parametrize("dialect", [
    "mysql", "postgres", "oracle", "tsql", "hive", "spark",
    "trino", "databricks", "snowflake", "redshift", "clickhouse", "duckdb",
])
def test_joined_with_sql_parses_in_all_dialects(dialect):
    for text in [
        "users joined with orders",
        "users left joined with orders",
        "orders joined with users",
    ]:
        schema = schema_context(reverse=text.startswith("orders"))
        result = generate(text, schema, dialect=dialect)
        assert result.success
        assert sqlglot.parse_one(result.sql, read=dialect) is not None


def test_joined_with_results_are_deterministic():
    first = generate("users joined with orders", schema_context())
    second = generate("users joined with orders", schema_context())
    assert first.success and second.success
    assert first.sql == second.sql
