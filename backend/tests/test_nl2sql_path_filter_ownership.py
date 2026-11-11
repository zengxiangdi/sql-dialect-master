"""Path-owned whose predicates for schema-aware distinct target counts."""

import sqlite3

import pytest
import sqlglot

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_pipeline.ir import (
    PathCondition,
    PathDistinctCountPlan,
    PathStep,
    build_ir,
)
from backend.core.nl2sql_pipeline.renderer import render_sql
from backend.core.nl2sql_schema import SchemaContext


DIALECTS = [
    "mysql", "postgres", "oracle", "tsql", "hive", "spark",
    "trino", "databricks", "snowflake", "redshift", "clickhouse", "duckdb",
]


def onehop_schema(*, composite_subject=False):
    users = {
        "name": "users",
        "columns": [{"name": "id"}, {"name": "status"}],
        "primary_key": ["id"],
    }
    orders = {
        "name": "orders",
        "columns": [
            {"name": "id"}, {"name": "user_id"},
            {"name": "status"}, {"name": "amount"},
        ],
        "primary_key": ["id"],
    }
    if composite_subject:
        users = {
            "name": "users",
            "columns": [
                {"name": "tenant_id"}, {"name": "id"}, {"name": "status"},
            ],
            "primary_key": ["tenant_id", "id"],
        }
        orders = {
            "name": "orders",
            "columns": [
                {"name": "tenant_id"}, {"name": "id"},
                {"name": "user_id"}, {"name": "status"},
            ],
            "primary_key": ["id"],
        }
        relationship = {
            "from_table": "users",
            "to_table": "orders",
            "columns": [
                {"from_column": "tenant_id", "to_column": "tenant_id"},
                {"from_column": "id", "to_column": "user_id"},
            ],
        }
    else:
        relationship = {
            "from_table": "orders",
            "from_column": "user_id",
            "to_table": "users",
            "to_column": "id",
        }
    return SchemaContext.from_mapping({
        "tables": [users, orders],
        "relationships": [relationship],
    })


def onehop_single_tenant_schema():
    return SchemaContext.from_mapping({
        "tables": [
            {
                "name": "users",
                "columns": [{"name": "id"}, {"name": "tenant_id"}],
                "primary_key": ["id"],
            },
            {
                "name": "orders",
                "columns": [
                    {"name": "id"}, {"name": "user_id"},
                    {"name": "tenant_id"}, {"name": "status"},
                ],
                "primary_key": ["id"],
            },
        ],
        "relationships": [{
            "from_table": "orders",
            "from_column": "user_id",
            "to_table": "users",
            "to_column": "id",
        }],
    })


def twohop_schema():
    return SchemaContext.from_mapping({
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "tenant_id"}, {"name": "id"}, {"name": "status"},
                ],
                "primary_key": ["tenant_id", "id"],
            },
            {
                "name": "orders",
                "columns": [
                    {"name": "tenant_id"}, {"name": "id"},
                    {"name": "user_id"}, {"name": "product_id"},
                    {"name": "status"},
                ],
                "primary_key": ["id"],
            },
            {
                "name": "products",
                "columns": [
                    {"name": "tenant_id"}, {"name": "id"}, {"name": "status"},
                ],
                "primary_key": ["tenant_id", "id"],
            },
        ],
        "relationships": [
            {
                "from_table": "orders",
                "to_table": "users",
                "columns": [
                    {"from_column": "tenant_id", "to_column": "tenant_id"},
                    {"from_column": "user_id", "to_column": "id"},
                ],
            },
            {
                "from_table": "orders",
                "to_table": "products",
                "columns": [
                    {"from_column": "tenant_id", "to_column": "tenant_id"},
                    {"from_column": "product_id", "to_column": "id"},
                ],
            },
        ],
    })


def generate(text, schema=None, dialect="postgres"):
    return NL2SQLGenerator().generate(text, dialect, schema=schema)


def test_single_pk_onehop_nonzero_keeps_flat_shorthand():
    context = onehop_schema()
    where = generate("count distinct orders per user where amount > 10", context)
    whose = generate("count distinct orders per user whose orders.status is active", context)

    assert where.success and whose.success
    assert "COUNT(DISTINCT id) AS count" in where.sql
    assert "COUNT(DISTINCT id) AS count" in whose.sql
    assert "_distinct_targets" not in where.sql
    assert "_distinct_targets" not in whose.sql
    assert "WHERE amount > 10" in where.sql
    assert "WHERE status = 'active'" in whose.sql


@pytest.mark.parametrize("text", [
    "count distinct orders per user where users.status = 'active'",
    "count distinct orders per user whose users.status is active",
])
def test_single_pk_onehop_nonzero_subject_filters_still_fail_closed(text):
    result = generate(text, onehop_schema())

    assert result.success is False
    assert result.sql is None


def test_single_pk_onehop_zero_subject_and_target_filters_use_path_plan():
    target = generate(
        "count distinct orders per user whose orders.status is active including zero",
        onehop_schema(),
    )
    subject = generate(
        "count distinct orders per user whose users.status is active including zero",
        onehop_schema(),
    )

    assert target.success and subject.success
    assert "COUNT(DISTINCT" not in target.sql
    assert "orders.status = 'active'" in target.sql
    baseline, counts = target.sql.split(") AS b\nLEFT JOIN (", 1)
    assert "orders.status" not in baseline
    assert "orders.status = 'active'" in counts
    assert "users.status = 'active'" in subject.sql
    assert subject.sql.count("users.status = 'active'") == 2


def test_single_pk_onehop_zero_ordinary_where_still_fails_closed():
    result = generate(
        "count distinct orders per user where amount > 10 including zero",
        onehop_schema(),
    )

    assert result.success is False
    assert result.sql is None


def test_single_pk_flat_and_zero_path_differ_on_ambiguous_unqualified_owner():
    nonzero = generate(
        "count distinct orders per user whose tenant_id is 1",
        onehop_single_tenant_schema(),
    )
    zero = generate(
        "count distinct orders per user whose tenant_id is 1 including zero",
        onehop_single_tenant_schema(),
    )

    assert nonzero.success
    assert "COUNT(DISTINCT id) AS count" in nonzero.sql
    assert "WHERE tenant_id = 1" in nonzero.sql
    assert zero.success is False
    assert zero.sql is None


@pytest.mark.parametrize("text", [
    "count distinct orders per user whose tenant_id is 1",
    "count distinct orders per user whose tenant_id is 1 including zero",
])
def test_composite_onehop_unqualified_path_owner_is_ambiguous(text):
    result = generate(text, onehop_schema(composite_subject=True))

    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("include_zero", [False, True])
def test_composite_onehop_target_and_subject_ownership(include_zero):
    suffix = " including zero" if include_zero else ""
    target = generate(
        f"count distinct orders per user whose orders.status is active{suffix}",
        onehop_schema(composite_subject=True),
    )
    subject = generate(
        f"count distinct orders per user whose users.status is active{suffix}",
        onehop_schema(composite_subject=True),
    )

    assert target.success and subject.success
    assert "orders.status = 'active'" in target.sql
    if include_zero:
        baseline, counts = target.sql.split(") AS b\nLEFT JOIN (", 1)
        assert "orders.status" not in baseline
        assert "orders.status = 'active'" in counts
    else:
        assert "orders.status = 'active'" in target.sql
    assert "users.status = 'active'" in subject.sql


@pytest.mark.parametrize("column", ["products.tenant_id", "orders.status"])
@pytest.mark.parametrize("include_zero", [False, True])
def test_twohop_target_and_intermediate_ownership(column, include_zero):
    suffix = " including zero" if include_zero else ""
    result = generate(
        f"count distinct products per user whose {column} is 1{suffix}",
        twohop_schema(),
    )

    assert result.success
    assert f"{column} = 1" in result.sql
    if include_zero:
        baseline, counts = result.sql.split(") AS b\nLEFT JOIN (", 1)
        assert column.split(".", 1)[0] + "." not in baseline
        assert f"{column} = 1" in counts


def test_twohop_subject_owner_requires_qualification_when_ambiguous():
    ambiguous = generate(
        "count distinct products per user whose tenant_id is 1",
        twohop_schema(),
    )
    qualified = generate(
        "count distinct products per user whose users.tenant_id is 1",
        twohop_schema(),
    )

    assert ambiguous.success is False
    assert qualified.success
    assert "users.tenant_id = 1" in qualified.sql


@pytest.mark.parametrize("text", [
    "count distinct products per user where products.tenant_id = 1",
    "count distinct products per user whose products.status is active and whose orders.status is active",
    "count distinct products per user whose products.unknown is active",
    "count distinct products per user whose shipments.status is active",
    "count distinct products per user whose products.status in (active)",
])
def test_path_filters_fail_closed_for_unsupported_shapes(text):
    result = generate(text, twohop_schema())

    assert result.success is False
    assert result.sql is None


def test_zero_filtered_out_subject_and_duplicates_runtime_sqlite():
    result = generate(
        "count distinct orders per user whose orders.status is active including zero",
        onehop_schema(),
    )
    assert result.success
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        "CREATE TABLE users(id INTEGER, status TEXT);"
        "CREATE TABLE orders(id INTEGER, user_id INTEGER, status TEXT, amount INTEGER);"
        "INSERT INTO users VALUES (1, 'active'), (2, 'active'), (3, 'active');"
        "INSERT INTO orders VALUES "
        "(10, 1, 'active', 1), (10, 1, 'active', 1), "
        "(11, 1, 'inactive', 1), (12, 2, 'inactive', 1);"
    )

    assert list(connection.execute(result.sql.split("\n", 1)[1])) == [
        (1, 1), (2, 0), (3, 0),
    ]


def test_zero_filtered_out_subject_runtime_duckdb():
    duckdb = pytest.importorskip("duckdb")
    result = generate(
        "count distinct orders per user whose orders.status is active including zero",
        onehop_schema(),
    )
    assert result.success
    connection = duckdb.connect()
    for statement in (
        "CREATE TABLE users(id INTEGER, status TEXT)",
        "CREATE TABLE orders(id INTEGER, user_id INTEGER, status TEXT, amount INTEGER)",
        "INSERT INTO users VALUES (1, 'active'), (2, 'active'), (3, 'active')",
        "INSERT INTO orders VALUES (10, 1, 'active', 1), (10, 1, 'active', 1), (11, 1, 'inactive', 1), (12, 2, 'inactive', 1)",
    ):
        connection.execute(statement)

    assert sorted(connection.execute(result.sql.split("\n", 1)[1]).fetchall()) == [
        (1, 1), (2, 0), (3, 0),
    ]
    connection.close()


def test_twohop_target_filter_runtime_sqlite_keeps_filtered_zero_subjects():
    result = generate(
        "count distinct products per user whose products.tenant_id is 1 including zero",
        twohop_schema(),
    )
    assert result.success
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        "CREATE TABLE users(tenant_id INTEGER, id INTEGER, status TEXT);"
        "CREATE TABLE orders(tenant_id INTEGER, id INTEGER, user_id INTEGER, product_id INTEGER, status TEXT);"
        "CREATE TABLE products(tenant_id INTEGER, id INTEGER, status TEXT);"
        "INSERT INTO users VALUES (1, 1, 'active'), (1, 2, 'active'), (2, 1, 'active');"
        "INSERT INTO orders VALUES "
        "(1, 10, 1, 10, 'active'), (1, 11, 1, 10, 'active'), (2, 12, 1, 10, 'active');"
        "INSERT INTO products VALUES (1, 10, 'active'), (2, 10, 'active');"
    )

    assert sorted(connection.execute(result.sql.split("\n", 1)[1]).fetchall()) == [
        (1, 1, 1), (1, 2, 0), (2, 1, 0),
    ]


@pytest.mark.parametrize("dialect", DIALECTS)
def test_path_filter_sql_is_parseable_in_all_dialects(dialect):
    result = generate(
        "count distinct products per user whose products.tenant_id is 1 including zero",
        twohop_schema(),
        dialect=dialect,
    )

    assert result.success
    assert sqlglot.parse_one(result.sql, read=dialect) is not None


@pytest.mark.parametrize("column", ["products.tenant_id", "orders.tenant_id"])
@pytest.mark.parametrize("dialect", DIALECTS)
def test_nonzero_path_filter_sql_is_parseable_in_all_dialects(column, dialect):
    result = generate(
        f"count distinct products per user whose {column} is 1",
        twohop_schema(),
        dialect=dialect,
    )

    assert result.success
    assert sqlglot.parse_one(result.sql, read=dialect) is not None


def test_path_filter_generation_is_deterministic():
    text = "count distinct products per user whose orders.status is active including zero limit 5"
    first = generate(text, twohop_schema())
    second = generate(text, twohop_schema())

    assert first.success and second.success
    assert first.sql == second.sql
    assert first.explanation == second.explanation
    assert first.evidence.score == second.evidence.score


@pytest.mark.parametrize("invalid_condition", [
    PathCondition("users", "status", "=", "'active'"),
    PathCondition("shipments", "status", "=", "'active'"),
    PathCondition("orders", "status", "LIKE", "'active'"),
    PathCondition("orders", "status", "=", "active OR 1=1"),
])
def test_renderer_rejects_invalid_path_condition(invalid_condition):
    plan = PathDistinctCountPlan(
        subject_table="users",
        path_steps=(PathStep("users", "orders", (("id", "user_id"),)),),
        group_identity=("id",),
        target_identity=("id",),
        path_conditions=(invalid_condition,),
    )
    ir = build_ir(
        operation="SELECT",
        table="users",
        columns=["*"],
        conditions=[],
        aggregations=[],
        group_by=[],
        ordering=None,
        limit=None,
        joins=[],
        distinct=False,
        dialect="postgres",
        path_distinct_count_plan=plan,
    )

    sql, _, confidence, _ = render_sql(ir)
    assert sql is None
    assert confidence == 0.0


def test_no_schema_path_filter_text_keeps_legacy_output():
    plain = generate("count distinct products per user")
    filtered = generate("count distinct products per user whose products.status is active")

    assert plain.schema_used is False
    assert filtered.schema_used is False
    assert plain.success == filtered.success
