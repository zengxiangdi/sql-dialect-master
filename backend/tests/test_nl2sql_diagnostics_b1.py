"""B1 high-confidence schema-aware unmapped-reference suggestions."""

import sqlglot

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_schema import SchemaContext


def schema(columns, *, orders=False):
    tables = [{"name": "users", "columns": [{"name": c} for c in columns]}]
    if orders:
        tables.append({"name": "orders", "columns": [{"name": "id"}, {"name": "amount"}]})
    return SchemaContext.from_mapping({"tables": tables, "relationships": []})


def generate(text, schema_value=None):
    return NL2SQLGenerator().generate(text, "postgres", schema=schema_value)


def body(result):
    return " ".join(
        line.strip() for line in (result.sql or "").splitlines()
        if not line.strip().startswith("--")
    )


def b1_messages(result):
    return [item for item in result.suggestions if item.startswith("Possible ")]


def test_with_password_warns_only_when_schema_lacks_column():
    missing = generate("list users with password", schema(["id", "name"]))
    present = generate("list users with password", schema(["id", "name", "password"]))
    assert missing.success and body(missing) == "SELECT * FROM users"
    assert len(b1_messages(missing)) == 1
    assert '"password"' in b1_messages(missing)[0]
    assert present.success and body(present) == "SELECT password FROM users"
    assert b1_messages(present) == []


def test_with_excludes_relationships_values_and_known_columns():
    for text in [
        "list users with orders",
        "list users with active",
        "list users with name",
        "list users with email",
    ]:
        result = generate(text, schema(["id", "name", "email", "status"], orders=True))
        assert not b1_messages(result)


def test_by_unknown_identifier_warns_but_known_columns_do_not():
    unknown = generate("show users by unknown_col", schema(["id", "name", "created_at"]))
    assert unknown.success and body(unknown) == "SELECT * FROM users"
    assert any('"unknown_col"' in item for item in b1_messages(unknown))
    for text in ["show users by name", "show users by created_at"]:
        assert b1_messages(generate(text, schema(["id", "name", "created_at"]))) == []


def test_partial_projection_warns_in_text_order_and_caps_three():
    result = generate("show user names and emails", schema(["id", "name"]))
    assert result.success and body(result) == "SELECT name FROM users"
    messages = b1_messages(result)
    assert len(messages) == 1
    assert '"email"' in messages[0]

    partial = generate(
        "show user names, emails, and phone",
        schema(["id", "name", "email"]),
    )
    assert partial.success is False
    assert b1_messages(partial) == []

    # A second unmapped mapped alias still follows the pre-existing
    # fail-closed projection behavior; B1 must not alter that outcome.
    failed = generate("show user names, emails, and phone", schema(["id", "name"]))
    assert failed.success is False
    assert b1_messages(failed) == []


def test_projection_token_scan_flags_allowlisted_and_snake_case_terms():
    missing = schema(["id", "name", "status"])
    for text, token in [
        ("show user names and password", "password"),
        ("show user names and nickname", "nickname"),
        ("show user names and unknown_col", "unknown_col"),
    ]:
        result = generate(text, missing)
        assert result.success
        assert any(f'"{token}"' in item for item in b1_messages(result))

    combined = generate("show user emails and password", missing)
    assert combined.success
    messages = b1_messages(combined)
    assert len(messages) == 2
    assert '"email"' in messages[0]
    assert '"password"' in messages[1]


def test_projection_token_scan_has_no_common_word_false_positives():
    for text in [
        "show user names and active",
        "show user names and orders",
        "show user names and foo",
    ]:
        result = generate(text, schema(["id", "name", "status"], orders=True))
        assert not b1_messages(result)


def test_projection_token_scan_skips_columns_present_in_schema():
    result = generate(
        "show user names and password and nickname",
        schema(["id", "name", "password", "nickname"]),
    )
    assert result.success
    assert b1_messages(result) == []


def test_chinese_free_text_is_not_scanned():
    result = generate("查询用户昵称", schema(["id", "name"]))
    assert result.success
    assert b1_messages(result) == []
    ordinary = generate("用户数据", schema(["id", "name"]))
    assert b1_messages(ordinary) == []


def test_failed_schema_results_do_not_get_b1_diagnostics():
    for text in [
        "show users where password_hash = 'x'",
        "find users whose nickname is bob",
        "show users ordered by unknown_col",
        "count users by unknown_col",
        "show users group by unknown_col",
    ]:
        result = generate(text, schema(["id", "name"]))
        assert result.success is False
        assert b1_messages(result) == []


def test_no_schema_has_no_new_diagnostics_and_sql_is_unchanged():
    for text in [
        "list users with password",
        "show users by unknown_col",
        "show user names and emails",
        "查询用户昵称",
    ]:
        result = generate(text)
        assert result.schema_used is False
        assert b1_messages(result) == []


def test_p0_p1_successes_have_no_b1_warning():
    cases = [
        ("show inactive users", schema(["id", "name", "status"])),
        ("price < -10", schema(["id", "price"])),
        ("find distinct user emails", schema(["id", "email"])),
        ("show all order amounts", schema(["id"], orders=True)),
        ("count orders by user_id", SchemaContext.from_mapping({
            "tables": [{"name": "orders", "columns": [{"name": "id"}, {"name": "user_id"}]}],
        })),
    ]
    for text, schema_value in cases:
        result = generate(text, schema_value)
        assert result.success, (text, result.explanation)
        assert b1_messages(result) == []


def test_suggestions_are_deterministic_and_sql_parseable():
    first = generate("show users by unknown_col", schema(["id", "name"]))
    second = generate("show users by unknown_col", schema(["id", "name"]))
    assert first.sql == second.sql
    assert first.suggestions == second.suggestions
    assert sqlglot.parse_one(first.sql, read="postgres") is not None
