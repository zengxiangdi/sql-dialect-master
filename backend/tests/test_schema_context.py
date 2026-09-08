"""Tests for schema-aware semantic query resolution."""

import pytest

from backend.core.schema_context import SchemaColumn, SchemaContext, SchemaTable


@pytest.fixture
def schema() -> SchemaContext:
    return SchemaContext(
        tables=(
            SchemaTable(
                name="users",
                alias="u",
                columns=(
                    SchemaColumn("id"),
                    SchemaColumn("name"),
                    SchemaColumn("status", alias="state"),
                ),
            ),
            SchemaTable(
                name="orders",
                alias="o",
                columns=(SchemaColumn("id"), SchemaColumn("user_id"), SchemaColumn("amount")),
            ),
        ),
        default_table="users",
    )


def test_resolve_table_by_name_and_alias(schema: SchemaContext):
    assert schema.resolve_table().name == "users"
    assert schema.resolve_table("u").name == "users"
    assert schema.resolve_table("orders").alias == "o"


def test_resolve_column_by_name_alias_and_table(schema: SchemaContext):
    table, column = schema.resolve_column("state")
    assert table.name == "users"
    assert column.name == "status"

    table, column = schema.resolve_column("id", "o")
    assert table.name == "orders"
    assert column.name == "id"


def test_resolve_column_rejects_ambiguous_unqualified_name(schema: SchemaContext):
    with pytest.raises(ValueError, match="Ambiguous schema column: id"):
        schema.resolve_column("id")


def test_resolve_table_and_column_reject_missing(schema: SchemaContext):
    with pytest.raises(KeyError, match="Unknown schema table"):
        schema.resolve_table("missing")
    with pytest.raises(KeyError, match="Unknown schema column"):
        schema.resolve_column("missing", "users")
