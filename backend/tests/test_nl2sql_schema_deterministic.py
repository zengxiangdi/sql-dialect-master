"""Core schema context and shared SQL reference validation contracts."""

import pytest
import sqlglot

from backend.core.nl2sql_schema import (
    SchemaContext,
    SchemaValidationError,
    validate_schema_references,
)


SCHEMA = {
    "tables": [
        {"name": "public.Users", "columns": [{"name": "ID"}, {"name": "name"}]},
        {"name": "orders", "columns": [{"name": "id"}, {"name": "user_id"}]},
        {"name": "events", "columns": []},
        {"name": "audit.users", "columns": [{"name": "id"}]},
    ],
    "relationships": [
        {
            "from_table": "orders",
            "from_column": "user_id",
            "to_table": "public.users",
            "to_column": "id",
        }
    ],
}


def parse(sql: str):
    return sqlglot.parse_one(sql, read="postgres")


def test_context_normalizes_case_and_preserves_canonical_names():
    context = SchemaContext.from_mapping(SCHEMA)

    assert context.is_valid
    assert context.table_candidates("PUBLIC.USERS")[0].name == "public.Users"
    assert context.table_candidates("public.users")[0].columns == frozenset({"ID", "name"})
    assert context.column_owners("NAME")[0].name == "public.Users"


def test_qualified_names_and_ambiguous_basenames_are_indexed():
    context = SchemaContext.from_mapping(SCHEMA)

    assert [table.name for table in context.table_candidates("public.users")] == [
        "public.Users"
    ]
    assert {table.name for table in context.table_candidates("users")} == {
        "public.Users",
        "audit.users",
    }


def test_empty_columns_allow_qualified_arbitrary_columns():
    context = SchemaContext.from_mapping({"tables": [{"name": "events", "columns": []}]})

    validate_schema_references(parse("SELECT e.anything, e.* FROM events AS e"), context)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT unknown FROM public.users",
        "SELECT u.unknown FROM public.users AS u",
    ],
)
def test_declared_columns_reject_unknown_columns(sql):
    context = SchemaContext.from_mapping(SCHEMA)
    with pytest.raises(SchemaValidationError):
        validate_schema_references(parse(sql), context)


def test_unqualified_column_unique_ambiguous_and_unknown():
    context = SchemaContext.from_mapping(SCHEMA)
    validate_schema_references(parse("SELECT name FROM public.users"), context)

    with pytest.raises(SchemaValidationError):
        validate_schema_references(
            parse("SELECT id FROM public.users JOIN orders ON public.users.ID = orders.user_id"),
            context,
            reject_ambiguous_unqualified=True,
        )
    with pytest.raises(SchemaValidationError):
        validate_schema_references(parse("SELECT missing FROM public.users"), context)


def test_alias_and_qualified_columns_are_allowed():
    context = SchemaContext.from_mapping(SCHEMA)
    validate_schema_references(
        parse("SELECT u.id, o.user_id FROM public.users AS u JOIN orders AS o ON u.id = o.user_id"),
        context,
    )


def test_cte_output_columns_are_checked():
    context = SchemaContext.from_mapping(
        {"tables": [{"name": "users", "columns": [{"name": "id"}]}]}
    )
    validate_schema_references(
        parse("WITH u AS (SELECT id AS user_id FROM users) SELECT u.user_id FROM u"),
        context,
    )
    with pytest.raises(SchemaValidationError):
        validate_schema_references(
            parse("WITH u AS (SELECT id AS user_id FROM users) SELECT u.missing FROM u"),
            context,
        )


def test_select_star_and_table_star_are_allowed():
    context = SchemaContext.from_mapping(SCHEMA)
    validate_schema_references(parse("SELECT * FROM public.users"), context)
    validate_schema_references(parse("SELECT u.* FROM public.users AS u"), context)


def test_relationship_index_supports_forward_and_reverse_traversal():
    context = SchemaContext.from_mapping(SCHEMA)

    forward = context.relationship_candidates("orders", "public.users")
    reverse = context.relationship_candidates("public.users", "orders")
    assert [(r.from_column, r.to_column) for r in forward] == [("user_id", "id")]
    assert [(r.from_column, r.to_column) for r in reverse] == [("id", "user_id")]


def test_missing_relationship_endpoint_marks_context_invalid_and_fails_closed():
    context = SchemaContext.from_mapping(
        {
            "tables": [{"name": "users", "columns": [{"name": "id"}]}],
            "relationships": [
                {
                    "from_table": "orders",
                    "from_column": "user_id",
                    "to_table": "users",
                    "to_column": "id",
                }
            ],
        }
    )

    assert context.is_valid is False
    with pytest.raises(SchemaValidationError):
        validate_schema_references(parse("SELECT id FROM users"), context)
