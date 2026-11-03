"""P1.3 schema-aware ``joined on`` contracts."""

import pytest
import sqlglot

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_schema import SchemaContext


def schema_context(*, relationships=True, ambiguous_orders=False):
    tables = [
        {"name": "users", "columns": [{"name": "id"}, {"name": "name"}, {"name": "status"}, {"name": "nickname"}]},
        {"name": "orders", "columns": [{"name": "id"}, {"name": "user_id"}, {"name": "amount"}]},
        {"name": "employees", "columns": [{"name": "id"}, {"name": "department_id"}]},
        {"name": "departments", "columns": [{"name": "id"}]},
    ]
    rels = []
    if relationships:
        rels = [
            {"from_table": "orders", "from_column": "user_id", "to_table": "users", "to_column": "id"},
            {"from_table": "employees", "from_column": "department_id", "to_table": "departments", "to_column": "id"},
        ]
    if ambiguous_orders:
        rels.append({"from_table": "orders", "from_column": "user_id", "to_table": "users", "to_column": "id"})
    return SchemaContext.from_mapping({"tables": tables, "relationships": rels})


def generate(text: str, schema=None, *, dialect="postgres"):
    return NL2SQLGenerator().generate(text, dialect, schema=schema)


def sql_body(result):
    assert result.success, result.explanation
    return " ".join(
        line.strip() for line in result.sql.splitlines()
        if not line.strip().startswith("--")
    )


@pytest.mark.parametrize("text,join_type,condition", [
    ("users and orders joined on orders.user_id = users.id", "INNER JOIN", "orders.user_id = users.id"),
    ("users joined on orders.user_id = users.id", "INNER JOIN", "orders.user_id = users.id"),
    ("users inner joined on orders.user_id = users.id", "INNER JOIN", "orders.user_id = users.id"),
    ("users joined on users.id = orders.user_id", "INNER JOIN", "users.id = orders.user_id"),
    ("users left joined on orders.user_id = users.id", "LEFT JOIN", "orders.user_id = users.id"),
    ("users right joined on orders.user_id = users.id", "RIGHT JOIN", "orders.user_id = users.id"),
    ("orders and users joined on orders.user_id = users.id", "INNER JOIN", "orders.user_id = users.id"),
])
def test_joined_on_renders_explicit_physical_join(text, join_type, condition):
    result = generate(text, schema_context())
    body = sql_body(result)
    assert body.startswith("SELECT * FROM")
    assert join_type in body
    assert f"ON {condition}" in body


def test_joined_on_allows_explicit_relationship_proof_without_metadata():
    result = generate(
        "users joined on orders.user_id = users.id",
        schema_context(relationships=False),
    )
    assert result.success
    assert "INNER JOIN orders ON orders.user_id = users.id" in sql_body(result)


@pytest.mark.parametrize("text", [
    "users joined on orders.user_id = users.id where status = 'active'",
    "users joined on orders.user_id = users.id whose nickname is bob",
])
def test_joined_on_preserves_following_predicates(text):
    result = generate(text, schema_context())
    body = sql_body(result)
    assert "INNER JOIN orders ON orders.user_id = users.id" in body
    assert "WHERE" in body
    if "whose" in text:
        assert "nickname = 'bob'" in body
    else:
        assert "status = 'active'" in body


def test_joined_on_uses_table_hint_as_subject():
    result = NL2SQLGenerator().generate(
        "users and orders joined on orders.user_id = users.id",
        "postgres",
        table_hint="orders",
        schema=schema_context(),
    )
    assert result.success
    assert sql_body(result).startswith("SELECT * FROM orders INNER JOIN users")


@pytest.mark.parametrize("text", [
    "users joined on orders.amount = users.id",
    "users joined on orders.unknown = users.id",
    "users joined on missing.user_id = users.id",
    "users joined on user_id = users.id",
    "users joined on o.user_id = users.id",
    "users joined on orders.user_id > users.id",
    "users joined on orders.user_id = users.id AND orders.amount > 0",
    "users joined on orders.user_id = users.id OR orders.amount > 0",
    "users joined on users.id = users.id",
    "users joined on orders.user_id = users.id joined on orders.user_id = users.id",
    "users and orders and employees joined on orders.user_id = users.id",
    "count orders per user joined on orders.user_id = users.id",
])
def test_joined_on_unsupported_or_invalid_forms_fail_closed(text):
    result = generate(text, schema_context())
    assert result.success is False
    assert result.sql is None


def test_joined_on_mismatch_and_ambiguous_relationship_fail_closed():
    mismatch = generate(
        "users joined on orders.amount = users.id", schema_context()
    )
    assert mismatch.success is False
    assert mismatch.sql is None

    ambiguous = generate(
        "users joined on orders.user_id = users.id",
        schema_context(ambiguous_orders=True),
    )
    assert ambiguous.success is False
    assert ambiguous.sql is None


@pytest.mark.parametrize("text", [
    "users joined with orders",
    "users join orders",
    "users left join orders",
])
def test_preexisting_join_and_exists_paths_remain(text):
    result = generate(text, schema_context())
    assert result.success
    body = sql_body(result)
    if "joined with" in text:
        assert "INNER JOIN orders ON orders.user_id = users.id" in body
    elif "left join" in text:
        assert "LEFT JOIN orders ON users.id = orders.user_id" in body
    else:
        assert "INNER JOIN orders ON users.id = orders.user_id" in body


def test_joined_with_without_relationship_remains_exists_fail_closed():
    result = generate("users joined with orders", schema_context(relationships=False))
    assert result.success is False
    assert result.sql is None


def test_plain_joined_employees_departments_remains_fail_closed():
    result = generate("employees joined departments", schema_context())
    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("text", [
    "users joined on orders.user_id = users.id",
    "users left joined on orders.user_id = users.id",
    "users joined with orders",
    "users join orders",
    "employees joined departments",
])
def test_no_schema_outputs_remain_legacy(text):
    result = generate(text, None)
    assert result.schema_used is False
    if text == "employees joined departments":
        assert result.success
        assert "INNER JOIN departments ON employees.dept_id = departments.id" in sql_body(result)
    elif text == "users joined with orders":
        assert result.success and "WHERE EXISTS" in sql_body(result)
    else:
        assert result.success
        assert "INNER JOIN orders ON users.id = orders.user_id" in sql_body(result)


@pytest.mark.parametrize("dialect", [
    "mysql", "postgres", "oracle", "tsql", "hive", "spark",
    "trino", "databricks", "snowflake", "redshift", "clickhouse", "duckdb",
])
def test_joined_on_sql_parses_in_all_dialects(dialect):
    for text in [
        "users joined on orders.user_id = users.id",
        "users left joined on orders.user_id = users.id",
    ]:
        result = generate(text, schema_context(), dialect=dialect)
        assert result.success
        assert sqlglot.parse_one(result.sql, read=dialect) is not None


def test_joined_on_results_are_deterministic():
    first = generate("users joined on orders.user_id = users.id", schema_context())
    second = generate("users joined on orders.user_id = users.id", schema_context())
    assert first.success and second.success
    assert first.sql == second.sql
