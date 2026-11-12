"""Schema grouped unique count ordering contracts."""
import pytest
import sqlglot
from backend.core.nl2sql import NL2SQLGenerator
from backend.tests.test_nl2sql_unique_count import make_schema
from backend.tests.test_nl2sql_composite_unique_count import schema as composite_schema

DIALECTS = ["mysql", "postgres", "oracle", "tsql", "hive", "spark", "trino", "databricks", "snowflake", "redshift", "clickhouse", "duckdb"]

def generate(text, schema, dialect="postgres"):
    return NL2SQLGenerator().generate(text, dialect, schema=schema)

@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_flat_count_ordering(direction):
    result = generate(f"count distinct orders per user ordered by count {direction}", make_schema(primary_key=["id"]))
    assert result.success and f"COUNT(DISTINCT id) {direction.upper()}" in result.sql

def test_flat_mixed_ordering_and_limit():
    result = generate("count distinct orders per user ordered by user_id desc, count asc limit 5", make_schema(primary_key=["id"]))
    assert result.success and "ORDER BY user_id DESC, COUNT(DISTINCT id) ASC" in result.sql and result.sql.endswith("LIMIT 5")

@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_composite_count_ordering(direction):
    result = generate(f"count distinct orders per user ordered by count {direction}", composite_schema(primary_key=["tenant_id", "id"]))
    assert result.success and f"COUNT(*) {direction.upper()}" in result.sql

@pytest.mark.parametrize("text", [
    "count distinct orders ordered by count desc",
    "count distinct orders top 10 ordered by count desc",
    "count distinct orders per user top 10",
    "count distinct orders per user top 10 ordered by user_id desc",
    "count distinct orders per user ordered by amount",
    "count distinct orders per user ordered by lower(user_id)",
    "count distinct orders per user ordered by count, count",
])
def test_grouped_count_ordering_fail_closed(text):
    result = generate(text, make_schema(primary_key=["id"]))
    assert result.success is False

def test_top_with_count_is_supported():
    result = generate("count distinct orders per user top 10 ordered by count desc", make_schema(primary_key=["id"]))
    assert result.success and result.sql.endswith("LIMIT 10")

def test_count_column_requires_qualification_for_group():
    schema = make_schema(primary_key=["id"])
    result = generate("count distinct orders per count ordered by count desc", schema)
    assert result.success is False

@pytest.mark.parametrize("dialect", DIALECTS)
def test_flat_count_ordering_parseable(dialect):
    result = generate("count distinct orders per user ordered by count desc limit 5", make_schema(primary_key=["id"]), dialect)
    assert result.success and sqlglot.parse_one(result.sql, read=dialect) is not None

def test_no_schema_is_unchanged():
    result = NL2SQLGenerator().generate("count distinct orders per user ordered by count desc", "postgres")
    assert result.schema_used is False and result.success
