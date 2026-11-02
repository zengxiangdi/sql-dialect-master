"""P1.3 schema-aware ``whose`` predicate contracts."""

import pytest
import sqlglot

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_schema import SchemaContext


USERS_SCHEMA = SchemaContext.from_mapping({
    "tables": [{
        "name": "users",
        "columns": [
            {"name": "id"}, {"name": "name"}, {"name": "nickname"},
            {"name": "price"}, {"name": "email"}, {"name": "created_at"},
            {"name": "status"},
        ],
    }],
    "relationships": [],
})


def generate(text: str, schema: SchemaContext | None = USERS_SCHEMA):
    return NL2SQLGenerator().generate(text, "postgres", schema=schema)


def sql_body(result):
    assert result.success, result.explanation
    return " ".join(
        line.strip() for line in result.sql.splitlines()
        if not line.strip().startswith("--")
    )


@pytest.mark.parametrize("text,fragment", [
    ("find users whose nickname is bob", "SELECT * FROM users WHERE nickname = 'bob'"),
    ("find users whose price > 10", "SELECT * FROM users WHERE price > 10"),
    ("find users whose email is null", "SELECT * FROM users WHERE email IS NULL"),
    ("find users whose email is not null", "SELECT * FROM users WHERE email IS NOT NULL"),
    ("find users whose email isn't null", "SELECT * FROM users WHERE email IS NOT NULL"),
    ("find users whose created_at >= '2024-01-01'", "created_at >= '2024-01-01'"),
    ("find users whose nickname is 'bob'", "nickname = 'bob'"),
    ("find users whose nickname is \"bob\"", "nickname = 'bob'"),
    ("find users whose nickname is 张三", "nickname = '张三'"),
    ("find users whose nickname is '张三'", "nickname = '张三'"),
    ("find users whose users.nickname is 张三", "nickname = '张三'"),
    ("find users whose price >= -10", "price >= -10"),
    ("find users whose price < 10.5", "price < 10.5"),
])
def test_schema_whose_literals_and_comparisons(text, fragment):
    assert fragment in sql_body(generate(text))


def test_whose_column_is_removed_from_projection():
    result = generate("find users whose price > 10")
    assert sql_body(result) == "SELECT * FROM users WHERE price > 10"


def test_explicit_projection_survives_whose_masking():
    result = generate("show user names whose nickname is bob")
    assert sql_body(result) == "SELECT name FROM users WHERE nickname = 'bob'"


@pytest.mark.parametrize("text,fragment", [
    ("find users whose nickname is bob and status is active", "status = 'active' AND nickname = 'bob'"),
    ("find users whose nickname is 'bob and alice'", "nickname = 'bob and alice'"),
])
def test_whose_combines_with_other_predicates(text, fragment):
    assert fragment in sql_body(generate(text))


@pytest.mark.parametrize("text", [
    "find users whose nickname is New York",
    "find users whose nickname is 张三 李四",
    "find users whose nickname is 张三和李四",
    "find users whose nickname is 张三，李四",
    "find users whose unknown_col is 1",
    "find users whose email = null",
    "find users whose email != null",
    "find users whose nickname is bob or price > 10",
    "find users whose nickname is bob and whose price > 10",
    "find users whose nickname is SELECT",
    "find users whose nickname is true",
    "find users whose nickname is current_date",
    "find users whose nickname is lower(bob)",
    "find users whose nickname is bob (and price > 10)",
    "find users whose nickname is 'bob",
])
def test_schema_whose_unsupported_or_unsafe_forms_fail_closed(text):
    result = generate(text)
    assert result.success is False
    assert result.sql is None


def test_qualified_whose_column_must_belong_to_subject_table():
    result = generate("find users whose users.nickname is bob")
    assert result.success
    assert "nickname = 'bob'" in sql_body(result)

    cross_table = SchemaContext.from_mapping({
        "tables": [
            {"name": "users", "columns": [{"name": "id"}]},
            {"name": "orders", "columns": [{"name": "user_id"}]},
        ],
        "relationships": [],
    })
    result = generate("find users whose orders.user_id is 1", cross_table)
    assert result.success is False
    assert result.sql is None


def test_whose_unknown_table_and_ambiguous_subject_fail_closed():
    unknown_table = SchemaContext.from_mapping({
        "tables": [{"name": "users", "columns": [{"name": "id"}]}],
    })
    result = generate("find users whose missing.nickname is bob", unknown_table)
    assert result.success is False
    assert result.sql is None

    ambiguous = SchemaContext.from_mapping({
        "tables": [
            {"name": "users", "columns": [{"name": "id"}, {"name": "nickname"}]},
            {"name": "accounts", "columns": [{"name": "id"}, {"name": "nickname"}]},
        ],
    })
    result = generate("find users and accounts whose nickname is bob", ambiguous)
    assert result.success is False
    assert result.sql is None


def test_whose_allows_unrestricted_schema_columns():
    unrestricted = SchemaContext.from_mapping({
        "tables": [{"name": "users", "columns": []}],
    })
    result = generate("find users whose nickname is bob", unrestricted)
    assert result.success
    assert sql_body(result) == "SELECT * FROM users WHERE nickname = 'bob'"


@pytest.mark.parametrize("text", [
    "find users whose nickname is bob",
    "find users whose price > 10",
    "find users whose email is null",
    "find users whose created_at >= '2024-01-01'",
    "show user names whose nickname is bob",
    "find users whose nickname is 张三",
])
def test_no_schema_behavior_remains_unchanged(text):
    current = generate(text, None)
    baseline = {
        "find users whose nickname is bob": "SELECT * FROM users",
        "find users whose price > 10": "SELECT * FROM users WHERE price > 10",
        "find users whose email is null": "SELECT email FROM users WHERE email IS NULL",
        "find users whose created_at >= '2024-01-01'": "SELECT * FROM users WHERE created_at >= '2024-01-01'",
        "show user names whose nickname is bob": "SELECT * FROM users",
        "find users whose nickname is 张三": "SELECT * FROM users",
    }[text]
    assert current.schema_used is False
    assert sql_body(current) == baseline


@pytest.mark.parametrize("text", [
    "show users where status is not active",
    "find users whose price < -10",
])
def test_p0_and_p1_regressions_remain(text):
    result = generate(text)
    assert result.success
    assert result.sql


@pytest.mark.parametrize("dialect", [
    "mysql", "postgres", "oracle", "tsql", "hive", "spark",
    "trino", "databricks", "snowflake", "redshift", "clickhouse", "duckdb",
])
def test_whose_sql_parses_in_all_dialects(dialect):
    generator = NL2SQLGenerator()
    for text in [
        "find users whose nickname is bob",
        "find users whose nickname is 张三",
        "find users whose created_at >= '2024-01-01'",
        "show user names whose nickname is bob",
    ]:
        result = generator.generate(text, dialect, schema=USERS_SCHEMA)
        assert result.success
        assert sqlglot.parse_one(result.sql, read=dialect) is not None


def test_whose_results_are_deterministic():
    first = generate("find users whose nickname is bob")
    second = generate("find users whose nickname is bob")
    assert first.success and second.success
    assert first.sql == second.sql
