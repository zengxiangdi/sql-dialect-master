"""Core schema context and shared SQL reference validation contracts."""

import pytest
import sqlglot

from backend.core.nl2sql import NL2SQLGenerator
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


SINGLE_TABLE_SCHEMA = SchemaContext.from_mapping(
    {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "id"},
                    {"name": "name"},
                    {"name": "price"},
                    {"name": "quantity"},
                    {"name": "created_at"},
                ],
            }
        ]
    }
)


@pytest.mark.parametrize("dialect", [
    "mysql", "postgres", "oracle", "tsql", "hive", "spark",
    "trino", "databricks", "snowflake", "redshift", "clickhouse", "duckdb",
])
def test_deterministic_schema_plain_select_parses_in_all_dialects(dialect):
    result = NL2SQLGenerator().generate(
        "show users", dialect=dialect, schema=SINGLE_TABLE_SCHEMA
    )
    assert result.success is True
    assert result.schema_used is True
    assert sqlglot.parse_one(result.sql, read=dialect) is not None


def test_deterministic_schema_uses_enhanced_path_for_top_n_aggregate_date_and_boolean():
    generator = NL2SQLGenerator()
    top_n = generator.generate(
        "find top 5 users by price", "postgres", schema=SINGLE_TABLE_SCHEMA
    )
    assert top_n.success and "ORDER BY price DESC" in top_n.sql
    assert "LIMIT 5" in top_n.sql

    aggregate = generator.generate(
        "calculate average price for users grouped by name",
        "postgres",
        schema=SINGLE_TABLE_SCHEMA,
    )
    assert aggregate.success and "GROUP BY name" in aggregate.sql

    date = generator.generate("last 7 days", "postgres", schema=SINGLE_TABLE_SCHEMA)
    assert date.success and "created_at" in date.sql

    boolean = generator.generate(
        "find users with price greater than 3 and quantity less than 9",
        "postgres",
        schema=SINGLE_TABLE_SCHEMA,
    )
    assert boolean.success and "price" in boolean.sql and "quantity" in boolean.sql


@pytest.mark.parametrize(
    "schema,text,kwargs",
    [
        ({}, "show users", {}),
        (
            {
                "tables": [
                    {"name": "audit.users", "columns": [{"name": "id"}]},
                    {"name": "public.users", "columns": [{"name": "id"}]},
                ]
            },
            "show users",
            {},
        ),
        (SINGLE_TABLE_SCHEMA, "show users", {"column_hints": ["secret"]}),
    ],
)
def test_deterministic_schema_unknown_or_ambiguous_requests_fail_closed(
    schema, text, kwargs
):
    context = schema if isinstance(schema, SchemaContext) else SchemaContext.from_mapping(schema)
    result = NL2SQLGenerator().generate(text, "postgres", schema=context, **kwargs)
    assert result.success is False
    assert result.sql is None
    assert result.schema_used is False
    assert result.confidence == 0.0


def test_deterministic_schema_hints_are_checked_before_generation():
    result = NL2SQLGenerator().generate(
        "show users",
        "postgres",
        table_hint="missing",
        schema=SINGLE_TABLE_SCHEMA,
    )
    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize(
    "prompt",
    ["show orders", "list products", "show payments where id = 1"],
)
def test_schema_unknown_table_aliases_fail_closed(prompt):
    result = NL2SQLGenerator().generate(
        prompt, "postgres", schema=SINGLE_TABLE_SCHEMA
    )
    assert result.success is False
    assert result.sql is None
    assert result.schema_used is False


def test_schema_unknown_table_fails_with_unrestricted_table_metadata():
    context = SchemaContext.from_mapping(
        {"tables": [{"name": "events", "columns": []}]}
    )
    result = NL2SQLGenerator().generate("show orders", "postgres", schema=context)
    assert result.success is False
    assert result.sql is None
    assert result.schema_used is False


@pytest.mark.parametrize(
    "prompt",
    [
        "show users and payments",
        "show users with payments",
        "find users who have orders and payments",
    ],
)
def test_schema_unknown_multi_table_alias_fails_closed(prompt):
    result = NL2SQLGenerator().generate(
        prompt, "postgres", schema=RELATION_SCHEMA
    )
    assert result.success is False
    assert result.sql is None
    assert result.schema_used is False


def test_schema_generic_data_word_and_implicit_single_table_still_work():
    generator = NL2SQLGenerator()
    assert generator.generate("show users", "postgres", schema=SINGLE_TABLE_SCHEMA).success
    assert generator.generate("show user data", "postgres", schema=SINGLE_TABLE_SCHEMA).success
    assert generator.generate("last 7 days", "postgres", schema=SINGLE_TABLE_SCHEMA).success
    assert generator.generate("count everything", "postgres", schema=SINGLE_TABLE_SCHEMA).success


def test_no_schema_unknown_table_behavior_is_unchanged():
    result = NL2SQLGenerator().generate("show orders", "postgres")
    assert result.success is True
    assert "FROM orders" in result.sql


def test_deterministic_schema_empty_columns_allow_qualified_columns():
    context = SchemaContext.from_mapping({"tables": [{"name": "events", "columns": []}]})
    result = NL2SQLGenerator().generate(
        "show events",
        "postgres",
        column_hints=["events.anything"],
        schema=context,
    )
    assert result.success is True
    assert "events.anything" in result.sql


RELATION_SCHEMA = SchemaContext.from_mapping(
    {
        "tables": [
            {"name": "users", "columns": [{"name": "id"}]},
            {"name": "orders", "columns": [{"name": "user_id"}]},
        ],
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


def test_schema_relationships_generate_forward_and_reverse_exists():
    generator = NL2SQLGenerator()
    forward = generator.generate(
        "find users who have orders", "postgres", schema=RELATION_SCHEMA
    )
    assert forward.success
    assert "WHERE EXISTS" in forward.sql
    assert "users.id = orders.user_id" in forward.sql

    reverse = generator.generate(
        "find orders who have users", "postgres", schema=RELATION_SCHEMA
    )
    assert reverse.success
    assert "WHERE EXISTS" in reverse.sql
    assert "orders.user_id = users.id" in reverse.sql


SCOPE_SCHEMA = SchemaContext.from_mapping(
    {
        "tables": [
            {"name": "users", "columns": [{"name": "id"}, {"name": "name"}, {"name": "price"}]},
            {"name": "orders", "columns": [{"name": "id"}, {"name": "user_id"}, {"name": "total"}]},
        ],
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


@pytest.mark.parametrize(
    "prompt",
    ["find users with id = 1", "find orders with id = 2", "count users by id"],
)
def test_schema_unqualified_columns_resolve_in_current_scope(prompt):
    result = NL2SQLGenerator().generate(prompt, "postgres", schema=SCOPE_SCHEMA)
    assert result.success is True
    assert result.schema_used is True


def test_schema_unqualified_column_is_ambiguous_across_join_sources():
    with pytest.raises(SchemaValidationError, match="ambiguous"):
        validate_schema_references(
            parse("SELECT id FROM users JOIN orders ON users.id = orders.user_id"),
            SCOPE_SCHEMA,
            reject_ambiguous_unqualified=True,
        )


def test_schema_correlated_exists_uses_inner_and_outer_qualified_sources():
    validate_schema_references(
        parse(
            "SELECT * FROM users WHERE EXISTS "
            "(SELECT 1 FROM orders WHERE orders.id = users.id)"
        ),
        SCOPE_SCHEMA,
        reject_ambiguous_unqualified=True,
    )


def test_schema_projection_alias_is_allowed_in_order_by():
    validate_schema_references(
        parse("SELECT price * 2 AS doubled FROM users ORDER BY doubled"),
        SCOPE_SCHEMA,
        reject_ambiguous_unqualified=True,
    )


def test_schema_unknown_unqualified_column_fails_closed():
    with pytest.raises(SchemaValidationError, match="unknown"):
        validate_schema_references(
            parse("SELECT unknown FROM users"),
            SCOPE_SCHEMA,
            reject_ambiguous_unqualified=True,
        )


def test_schema_date_rewrite_skips_single_quoted_literals():
    context = SchemaContext.from_mapping(
        {"tables": [{"name": "users", "columns": [{"name": "status"}, {"name": "created_at"}]}]}
    )
    generator = NL2SQLGenerator()
    table = context.tables[0]
    assert generator._schema_resolve_conditions(
        "status = 'date'",
        ["status = 'date'"],
        table,
        context,
    ) == ["status = 'date'"]


def test_schema_finalize_does_not_swallow_unexpected_errors(monkeypatch):
    import backend.core.nl2sql_pipeline.orchestrator as pipeline_orchestrator
    from backend.core.nl2sql_pipeline.models import NL2SQLResult

    context = SchemaContext.from_mapping(
        {"tables": [{"name": "users", "columns": [{"name": "id"}]}]}
    )
    result = NL2SQLResult(
        success=True,
        input_text="show users",
        sql="SELECT * FROM users",
        dialect="postgres",
    )

    def unexpected_error(*_args, **_kwargs):
        raise RuntimeError("unexpected validator failure")

    monkeypatch.setattr(
        pipeline_orchestrator, "validate_schema_references", unexpected_error
    )
    with pytest.raises(RuntimeError, match="unexpected validator failure"):
        NL2SQLGenerator()._schema_finalize(result, context)


def test_schema_relationships_generate_not_exists_and_physical_join():
    generator = NL2SQLGenerator()
    negative = generator.generate(
        "find users without orders", "postgres", schema=RELATION_SCHEMA
    )
    assert negative.success
    assert "WHERE NOT EXISTS" in negative.sql

    physical = generator.generate(
        "show users left join orders", "postgres", schema=RELATION_SCHEMA
    )
    assert physical.success
    assert "LEFT JOIN orders" in physical.sql
    assert "users.id = orders.user_id" in physical.sql


@pytest.mark.parametrize(
    "prompt",
    [
        "show users full join orders",
        "show users outer join orders",
        "show users cross join orders",
    ],
)
def test_schema_unsupported_join_types_fail_closed(prompt):
    result = NL2SQLGenerator().generate(prompt, "postgres", schema=RELATION_SCHEMA)
    assert result.success is False
    assert result.sql is None
    assert result.schema_used is False


@pytest.mark.parametrize(
    "prompt,join_type",
    [
        ("show users left join orders", "LEFT JOIN"),
        ("show users right join orders", "RIGHT JOIN"),
        ("show users inner join orders", "INNER JOIN"),
        ("show users left outer join orders", "LEFT JOIN"),
        ("show users right outer join orders", "RIGHT JOIN"),
    ],
)
def test_schema_supported_join_types_render_expected_kind(prompt, join_type):
    result = NL2SQLGenerator().generate(prompt, "postgres", schema=RELATION_SCHEMA)
    assert result.success is True
    assert join_type in result.sql


def test_schema_missing_relationship_fails_closed():
    context = SchemaContext.from_mapping(
        {
            "tables": [
                {"name": "users", "columns": [{"name": "id"}]},
                {"name": "invoices", "columns": [{"name": "user_id"}]},
            ]
        }
    )
    result = NL2SQLGenerator().generate(
        "find users who have invoices", "postgres", schema=context
    )
    assert result.success is False
    assert result.sql is None
    assert result.schema_used is False


def test_schema_duplicate_relationships_fail_closed():
    context = SchemaContext.from_mapping(
        {
            "tables": [
                {"name": "users", "columns": [{"name": "id"}]},
                {"name": "orders", "columns": [{"name": "user_id"}]},
            ],
            "relationships": [
                {
                    "from_table": "orders",
                    "from_column": "user_id",
                    "to_table": "users",
                    "to_column": "id",
                },
                {
                    "from_table": "orders",
                    "from_column": "user_id",
                    "to_table": "users",
                    "to_column": "id",
                },
            ],
        }
    )
    result = NL2SQLGenerator().generate(
        "find users who have orders", "postgres", schema=context
    )
    assert result.success is False
    assert result.sql is None
