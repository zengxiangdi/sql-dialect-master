"""Count and group ordering contracts for schema-aware path counts."""

import sqlite3

import pytest
import sqlglot

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_pipeline.ir import (
    PathDistinctCountPlan,
    PathOrderingTerm,
    PathStep,
    build_ir,
)
from backend.core.nl2sql_pipeline.renderer import render_sql
from backend.tests.test_nl2sql_composite_unique_count import schema as single_composite_schema
from backend.tests.test_nl2sql_path_filter_ownership import (
    onehop_schema,
    twohop_schema,
)
from backend.tests.test_nl2sql_unique_count import make_schema as single_schema
from backend.tests.test_nl2sql_zero_count import make_count_pk_schema, make_schema


DIALECTS = [
    "mysql", "postgres", "oracle", "tsql", "hive", "spark",
    "trino", "databricks", "snowflake", "redshift", "clickhouse", "duckdb",
]


def generate(text, schema=None, dialect="postgres"):
    return NL2SQLGenerator().generate(text, dialect, schema=schema)


@pytest.mark.parametrize("direction", ["asc", "desc"])
@pytest.mark.parametrize("path_text,schema", [
    ("orders per user", onehop_schema(composite_subject=True)),
    ("products per user", twohop_schema()),
])
def test_nonzero_path_count_ordering(path_text, schema, direction):
    result = generate(
        f"count distinct {path_text} ordered by count {direction}",
        schema,
    )

    assert result.success
    assert f"COUNT(*) {direction.upper()}" in result.sql
    assert result.sql.index("GROUP BY") < result.sql.index("ORDER BY")


@pytest.mark.parametrize("schema,path_text", [
    (make_schema(path_length=1), "orders per user"),
    (make_schema(path_length=2), "products per user"),
    (onehop_schema(composite_subject=True), "orders per user"),
    (twohop_schema(), "products per user"),
])
def test_zero_path_count_ordering_uses_coalesce(schema, path_text):
    result = generate(
        f"count distinct {path_text} including zero ordered by count desc limit 2",
        schema,
    )

    assert result.success
    assert "ORDER BY COALESCE(c.count, 0) DESC" in result.sql
    assert result.sql.index(") AS c ON") < result.sql.index("ORDER BY") < result.sql.index("LIMIT 2")
    assert "ORDER BY" not in result.sql.split("FROM (", 1)[1].split(") AS _distinct_targets", 1)[0]


@pytest.mark.parametrize("text,expected", [
    (
        "count distinct products per user ordered by count desc, users.id desc",
        "ORDER BY COUNT(*) DESC, _group_1 DESC, _group_0 ASC",
    ),
    (
        "count distinct products per user ordered by users.id desc, count asc",
        "ORDER BY _group_1 DESC, COUNT(*) ASC, _group_0 ASC",
    ),
    (
        "count distinct products per user ordered by tenant_id desc, id desc, count asc",
        "ORDER BY _group_0 DESC, _group_1 DESC, COUNT(*) ASC",
    ),
])
def test_count_and_group_ordering_preserves_user_order_and_ties(text, expected):
    result = generate(text, twohop_schema())

    assert result.success
    assert expected in result.sql


def test_zero_count_ordering_with_path_filter_and_limit():
    result = generate(
        "count distinct products per user whose products.tenant_id is 1 "
        "including zero ordered by count desc, users.id desc limit 2",
        twohop_schema(),
    )

    assert result.success
    assert "ORDER BY COALESCE(c.count, 0) DESC, b._group_1 DESC, b._group_0 ASC" in result.sql
    baseline, counts = result.sql.split(") AS b\nLEFT JOIN (", 1)
    assert "products.tenant_id = 1" not in baseline
    assert "products.tenant_id = 1" in counts


@pytest.mark.parametrize("owner", ["users", "orders", "products"])
@pytest.mark.parametrize("include_zero", [False, True])
@pytest.mark.parametrize("value", [
    "'desc'", "desc", "'max'", "max", "'top 10'",
    "'order by count desc'", "'sort'", "sort", "'sorted'", "sorted",
    "'asc'", "asc", "'ascending'", "ascending", "'descending'",
    "descending", "'highest'", "highest", "'lowest'", "lowest",
    "'min'", "min", "'排序'", "排序", "'降序'", "降序",
])
def test_ordering_words_inside_path_filter_values_do_not_trigger_ordering(
    owner, include_zero, value
):
    suffix = " including zero" if include_zero else ""
    result = generate(
        f"count distinct products per user whose {owner}.status is {value}{suffix}",
        twohop_schema(),
    )

    assert result.success
    assert not any(line.lstrip().upper().startswith("ORDER BY ") for line in result.sql.splitlines())
    predicate = f"{owner}.status = "
    assert predicate in result.sql
    if include_zero and owner != "users":
        baseline, counts = result.sql.split(") AS b\nLEFT JOIN (", 1)
        assert predicate not in baseline
        assert predicate in counts


@pytest.mark.parametrize("owner", ["users", "orders", "products"])
@pytest.mark.parametrize("include_zero", [False, True])
def test_real_ordering_after_path_filter_still_orders(owner, include_zero):
    suffix = " including zero" if include_zero else ""
    result = generate(
        f"count distinct products per user whose {owner}.status is 'desc'{suffix} "
        "ordered by count desc",
        twohop_schema(),
    )

    assert result.success
    expected = "ORDER BY COALESCE(c.count, 0) DESC" if include_zero else "ORDER BY COUNT(*) DESC"
    assert expected in result.sql


@pytest.mark.parametrize("text", [
    "count distinct products per user top 10",
    "count distinct products per user top 10 ordered by users.id desc",
])
def test_path_top_without_count_ordering_fails_closed(text):
    result = generate(text, twohop_schema())

    assert result.success is False
    assert result.sql is None


def test_path_top_with_count_ordering_only_controls_limit():
    result = generate(
        "count distinct products per user top 10 ordered by count desc",
        twohop_schema(),
    )

    assert result.success
    assert "ORDER BY COUNT(*) DESC" in result.sql
    assert result.sql.rstrip().endswith("LIMIT 10")


@pytest.mark.parametrize("text,limit", [
    ("count distinct products per user ordered by count desc top 10", "LIMIT 10"),
    ("count distinct products per user ordered by count desc, users.id asc top 10", "LIMIT 10"),
    ("count distinct products per user including zero ordered by count desc top 2", "LIMIT 2"),
])
def test_top_after_explicit_ordering_is_only_limit(text, limit):
    result = generate(text, twohop_schema() if "including zero" not in text else make_schema())

    assert result.success
    assert "ORDER BY" in result.sql
    assert result.sql.rstrip().endswith(limit)


@pytest.mark.parametrize("text", [
    "count distinct products per user ordered by products.id",
    "count distinct products per user ordered by orders.status",
    "count distinct products per user ordered by status",
    "count distinct products per user ordered by lower(users.id)",
    "count distinct products per user ordered by users.id NULLS LAST",
    "count distinct products per user ordered by count, count",
    "count distinct products per user ordered by count, tenant_id, id, users.id, users.tenant_id, products.id",
])
def test_path_count_ordering_rejects_unsafe_or_excessive_terms(text):
    result = generate(text, twohop_schema())

    assert result.success is False
    assert result.sql is None


def test_count_alias_wins_over_subject_identity_named_count():
    count_alias = generate(
        "count distinct orders per user including zero ordered by count desc",
        make_count_pk_schema(),
    )
    group_column = generate(
        "count distinct orders per user including zero ordered by users.count desc",
        make_count_pk_schema(),
    )

    assert count_alias.success and group_column.success
    assert "ORDER BY COALESCE(c.count, 0) DESC" in count_alias.sql
    assert "ORDER BY b._group_0 DESC" in group_column.sql


@pytest.mark.parametrize("text,schema", [
    ("count distinct orders per user ordered by count desc", single_schema(primary_key=["id"])),
    ("count distinct orders per user ordered by count desc", single_composite_schema(primary_key=["tenant_id", "id"])),
])
def test_flat_and_single_table_count_ordering_remains_fail_closed(text, schema):
    result = generate(text, schema)

    assert result.success is False
    assert result.sql is None


def _setup_onehop_runtime(connection):
    connection.executescript(
        "CREATE TABLE users(id INTEGER, status TEXT);"
        "CREATE TABLE orders(id INTEGER, user_id INTEGER, status TEXT, amount INTEGER);"
        "INSERT INTO users VALUES (1, 'active'), (2, 'active'), (3, 'active');"
        "INSERT INTO orders VALUES "
        "(10, 1, 'active', 1), (11, 1, 'active', 1), (12, 2, 'active', 1);"
    )


def test_count_ordering_runtime_sqlite():
    result = generate(
        "count distinct orders per user including zero ordered by count desc limit 2",
        onehop_schema(),
    )
    assert result.success
    connection = sqlite3.connect(":memory:")
    _setup_onehop_runtime(connection)

    assert connection.execute(result.sql.split("\n", 1)[1]).fetchall() == [
        (1, 2), (2, 1),
    ]


def test_count_ordering_runtime_duckdb():
    duckdb = pytest.importorskip("duckdb")
    result = generate(
        "count distinct orders per user including zero ordered by count desc limit 2",
        onehop_schema(),
    )
    assert result.success
    connection = duckdb.connect()
    for statement in (
        "CREATE TABLE users(id INTEGER, status TEXT)",
        "CREATE TABLE orders(id INTEGER, user_id INTEGER, status TEXT, amount INTEGER)",
        "INSERT INTO users VALUES (1, 'active'), (2, 'active'), (3, 'active')",
        "INSERT INTO orders VALUES (10, 1, 'active', 1), (11, 1, 'active', 1), (12, 2, 'active', 1)",
    ):
        connection.execute(statement)

    assert connection.execute(result.sql.split("\n", 1)[1]).fetchall() == [
        (1, 2), (2, 1),
    ]
    connection.close()


@pytest.mark.parametrize("dialect", DIALECTS)
def test_nonzero_count_ordering_parseable_in_all_dialects(dialect):
    result = generate(
        "count distinct products per user ordered by count desc limit 10",
        twohop_schema(),
        dialect=dialect,
    )

    assert result.success
    assert sqlglot.parse_one(result.sql, read=dialect) is not None


@pytest.mark.parametrize("dialect", DIALECTS)
def test_zero_count_ordering_parseable_in_all_dialects(dialect):
    result = generate(
        "count distinct products per user including zero ordered by count desc limit 10",
        twohop_schema(),
        dialect=dialect,
    )

    assert result.success
    assert sqlglot.parse_one(result.sql, read=dialect) is not None


def test_path_count_ordering_is_deterministic():
    text = "count distinct products per user including zero ordered by count desc limit 5"
    first = generate(text, twohop_schema())
    second = generate(text, twohop_schema())

    assert first.success and second.success
    assert first.sql == second.sql
    assert first.explanation == second.explanation
    assert first.evidence.score == second.evidence.score


def test_no_schema_count_ordering_stays_legacy():
    first = generate("count distinct products per user ordered by count desc")
    second = generate("count distinct products per user ordered by count desc")

    assert first.schema_used is False
    assert second.schema_used is False
    assert first.sql == second.sql
    assert first.explanation == second.explanation


@pytest.mark.parametrize("term", [
    PathOrderingTerm("unknown", None, "ASC"),
    PathOrderingTerm("count", "id", "ASC"),
    PathOrderingTerm("group", "status", "ASC"),
    PathOrderingTerm("count", None, "SIDEWAYS"),
])
def test_renderer_rejects_invalid_path_ordering_terms(term):
    plan = PathDistinctCountPlan(
        subject_table="users",
        path_steps=(PathStep("users", "orders", (("id", "user_id"),)),),
        group_identity=("id",),
        target_identity=("id",),
        path_orderings=(term,),
    )
    ir = build_ir(
        "SELECT", "users", ["*"], [], [], [], None, None, [], False, "postgres",
        path_distinct_count_plan=plan,
    )

    sql, _, confidence, _ = render_sql(ir)
    assert sql is None
    assert confidence == 0.0
