"""Schema-aware one-hop association count contracts."""

import sqlite3

import pytest
import sqlglot

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_schema import SchemaContext


def single_schema(*, reverse: bool = False) -> SchemaContext:
    relationship = (
        {"from_table": "users", "from_column": "id", "to_table": "orders", "to_column": "user_id"}
        if reverse
        else {"from_table": "orders", "from_column": "user_id", "to_table": "users", "to_column": "id"}
    )
    return SchemaContext.from_mapping({
        "tables": [
            {"name": "users", "columns": [{"name": "id"}, {"name": "status"}], "primary_key": ["id"]},
            {"name": "orders", "columns": [{"name": "id"}, {"name": "user_id"}, {"name": "status"}]},
        ],
        "relationships": [relationship],
    })


def composite_schema(*, reverse: bool = False, complete: bool = True, duplicate: bool = False) -> SchemaContext:
    pairs = [
        {"from_column": "tenant_id", "to_column": "tenant_id"},
        {"from_column": "user_id", "to_column": "id"},
    ]
    if not complete:
        pairs = pairs[:1]
    relationship = (
        {
            "from_table": "users", "to_table": "orders",
            "columns": [
                {"from_column": pair["to_column"], "to_column": pair["from_column"]}
                for pair in pairs
            ],
        }
        if reverse
        else {"from_table": "orders", "to_table": "users", "columns": pairs}
    )
    relationships = [relationship]
    if duplicate:
        relationships.append(relationship)
    return SchemaContext.from_mapping({
        "tables": [
            {
                "name": "users",
                "columns": [{"name": "tenant_id"}, {"name": "id"}, {"name": "status"}],
                "primary_key": ["tenant_id", "id"],
            },
            {"name": "orders", "columns": [{"name": "tenant_id"}, {"name": "user_id"}, {"name": "status"}]},
        ],
        "relationships": relationships,
    })


def generate(text: str, schema: SchemaContext | None = None, *, table_hint: str | None = None):
    return NL2SQLGenerator().generate(text, "postgres", table_hint=table_hint, schema=schema)


def test_single_pk_without_subject_filter_preserves_group_label_sql() -> None:
    result = generate("count orders per user", single_schema())

    assert result.success
    assert result.sql is not None
    assert "\n".join(
        line for line in result.sql.splitlines() if not line.strip().startswith("--")
    ) == "SELECT user_id, COUNT(*) AS count\nFROM orders\nGROUP BY user_id"


def test_single_pk_subject_filter_uses_subject_join() -> None:
    result = generate("count orders per user whose users.status is active", single_schema())

    assert result.success
    assert "FROM users\nINNER JOIN orders ON orders.user_id = users.id" in result.sql
    assert "WHERE users.status = 'active'" in result.sql
    assert "COUNT(*) AS count" in result.sql
    assert "GROUP BY users.id" in result.sql


def test_single_pk_data_filter_keeps_legacy_group_label_sql() -> None:
    result = generate("count orders per user where orders.status = 'paid'", single_schema())

    assert result.success
    assert "FROM orders" in result.sql
    assert "WHERE status = 'paid'" in result.sql
    assert "users" not in result.sql


@pytest.mark.parametrize("text", [
    "count orders per user where orders.status = 'paid' limit 5",
    "count orders per user where orders.status = 'paid' ordered by count desc limit 5",
])
def test_single_pk_structural_suffix_is_not_a_where_predicate(text: str) -> None:
    result = generate(text, single_schema())

    assert result.success
    assert "WHERE status = 'paid'" in result.sql
    assert "status = 5" not in result.sql
    assert "LIMIT 5" in result.sql


def test_group_label_structural_suffix_does_not_create_extra_condition() -> None:
    result = generate("count employees per department where employees.status = 'active' limit 5", single_schema())

    assert result.success is False or "status = 5" not in (result.sql or "")


def test_single_pk_count_ordering_keeps_legacy_group_label_sql() -> None:
    result = generate("count orders per user ordered by count desc", single_schema())

    assert result.success
    assert "FROM orders" in result.sql
    assert "ORDER BY count DESC" in result.sql
    assert "users" not in result.sql


def test_single_pk_data_only_ordering_by_user_id_keeps_legacy_path() -> None:
    result = generate("count orders per user ordered by user_id desc", single_schema())

    assert result.success
    assert "FROM orders" in result.sql
    assert "users" not in result.sql


def test_single_pk_subject_identity_ordering_uses_association_join() -> None:
    result = generate("count orders per user ordered by users.id desc", single_schema())

    assert result.success
    assert "FROM users\nINNER JOIN orders" in result.sql
    assert "ORDER BY users.id DESC" in result.sql


def test_composite_subject_uses_all_relationship_pairs() -> None:
    result = generate("count orders per user", composite_schema())

    assert result.success
    assert "users.tenant_id AS _group_0" in result.sql
    assert "users.id AS _group_1" in result.sql
    assert "orders.tenant_id = users.tenant_id AND orders.user_id = users.id" in result.sql
    assert "GROUP BY users.tenant_id, users.id" in result.sql


def test_reverse_relationship_is_oriented_data_to_subject() -> None:
    result = generate("count orders per user", composite_schema(reverse=True))

    assert result.success
    assert "orders.tenant_id = users.tenant_id AND orders.user_id = users.id" in result.sql


@pytest.mark.parametrize("text", [
    "count orders per user whose orders.status is paid",
    "count orders per user where users.status is active",
])
def test_qualified_subject_and_data_filters_are_owned(text: str) -> None:
    result = generate(text, composite_schema())

    assert result.success
    if "orders.status" in text:
        assert "WHERE orders.status = 'paid'" in result.sql
    else:
        assert "WHERE users.status = 'active'" in result.sql


@pytest.mark.parametrize(
    "text, expected",
    [
        ("count orders per user where users.status = 'active'", "users.status = 'active'"),
        ("count orders per user where orders.status = 'paid'", "orders.status = 'paid'"),
        ('count orders per user where users.status = "active"', "users.status = 'active'"),
        ("count orders per user where users.status is active", "users.status = 'active'"),
        ("count orders per user where users.status = 'status = x'", "users.status = 'status = x'"),
        ("count orders per user where users.status = 'O''Reilly'", "users.status = 'O''Reilly'"),
    ],
)
def test_association_where_literal_is_preserved(text: str, expected: str) -> None:
    result = generate(text, composite_schema())

    assert result.success
    assert expected in result.sql
    assert "'''" not in result.sql


def test_association_multiple_quoted_where_literals_are_preserved() -> None:
    result = generate(
        "count orders per user where users.status = 'active' and orders.status = 'paid'",
        composite_schema(),
    )

    assert result.success
    assert "users.status = 'active'" in result.sql
    assert "orders.status = 'paid'" in result.sql
    assert "'''" not in result.sql


def test_multiple_whose_preserves_subject_and_data_conditions() -> None:
    result = generate(
        "count orders per user whose users.status is active and orders.status is paid",
        composite_schema(),
    )

    assert result.success
    assert "users.status = 'active'" in result.sql
    assert "orders.status = 'paid'" in result.sql


@pytest.mark.parametrize("text", [
    "count orders per user top 5",
    "count orders per user first 5",
])
def test_top_without_count_ordering_fails_closed(text: str) -> None:
    result = generate(text, composite_schema())

    assert result.success is False
    assert result.sql is None


def test_top_with_count_ordering_succeeds() -> None:
    result = generate("count orders per user ordered by count desc top 5", composite_schema())

    assert result.success
    assert "ORDER BY COUNT(*) DESC" in result.sql


@pytest.mark.parametrize("text", ["每位用户有多少订单", "每个用户有多少订单"])
def test_chinese_association_phrases_resolve_subject_and_data(text: str) -> None:
    result = generate(text, composite_schema())

    assert result.success
    assert "COUNT(*) AS count" in result.sql
    assert "orders.tenant_id = users.tenant_id" in result.sql


def test_ambiguous_unqualified_filter_fails_closed() -> None:
    result = generate("count orders per user where status is paid", composite_schema())

    assert result.success is False
    assert result.sql is None


def test_count_ordering_has_subject_identity_tie_breakers() -> None:
    result = generate("count orders per user ordered by count desc limit 5", composite_schema())

    assert result.success
    assert "ORDER BY COUNT(*) DESC, users.tenant_id ASC, users.id ASC" in result.sql
    assert result.sql.endswith("LIMIT 5")


def test_table_hint_refers_to_data_table() -> None:
    assert generate("count orders per user", composite_schema(), table_hint="orders").success
    rejected = generate("count orders per user", composite_schema(), table_hint="users")
    assert rejected.success is False
    assert rejected.sql is None


@pytest.mark.parametrize("text", [
    "count distinct orders per user",
    "count orders per user including zero",
    "count products per user",
    "count orders per user joined with products",
    "count orders per user who have products",
])
def test_unsupported_association_shapes_fail_closed(text: str) -> None:
    result = generate(text, composite_schema())

    assert result.success is False
    assert result.sql is None


def test_incomplete_or_duplicate_relationship_fails_closed() -> None:
    incomplete = generate("count orders per user", composite_schema(complete=False))
    duplicate = generate("count orders per user", composite_schema(duplicate=True))

    assert incomplete.success is False
    assert duplicate.success is False


def test_duplicate_rows_and_null_fk_are_counted_with_inner_join() -> None:
    result = generate("count orders per user", composite_schema())
    assert result.success and result.sql is not None
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE users (tenant_id INTEGER, id INTEGER, status TEXT, PRIMARY KEY (tenant_id, id));
        CREATE TABLE orders (tenant_id INTEGER, user_id INTEGER, status TEXT);
        INSERT INTO users VALUES (1, 10, 'active'), (2, 10, 'active');
        INSERT INTO orders VALUES (1, 10, 'paid'), (1, 10, 'paid'), (NULL, 10, 'paid'), (2, 10, 'paid');
        """
    )
    rows = connection.execute(result.sql.split("\n", 1)[1]).fetchall()

    assert rows == [(1, 10, 2), (2, 10, 1)]


@pytest.mark.parametrize("dialect", [
    "mysql", "postgres", "oracle", "tsql", "hive", "spark", "trino",
    "snowflake", "redshift", "clickhouse", "duckdb", "databricks",
])
def test_composite_association_sql_is_parseable_in_all_dialects(dialect: str) -> None:
    result = generate("count orders per user", composite_schema())

    assert result.success
    assert sqlglot.parse_one(result.sql, read=dialect) is not None


def test_no_schema_behavior_is_unchanged() -> None:
    result = generate("count orders per user")

    assert result.success
    assert result.sql is not None
    assert "COUNT(*)" in result.sql
