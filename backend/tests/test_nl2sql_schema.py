"""Schema-aware NL2SQL requests preserve routing and privacy contracts."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.api import main
from backend.core.config import settings
from backend.core.nl2sql_llm import LLMGeneration


MODEL = "test-provider/schema-model"
SCHEMA = {
    "tables": [
        {"name": "users", "columns": [{"name": "id"}, {"name": "name"}]},
        {"name": "orders", "columns": [{"name": "id"}, {"name": "user_id"}]},
    ],
    "relationships": [{
        "from_table": "orders", "from_column": "user_id",
        "to_table": "users", "to_column": "id",
    }],
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "api_key", None)
    monkeypatch.setattr(settings, "nl2sql_llm_enabled", True)
    monkeypatch.setattr(settings, "nl2sql_llm_fallback", True)
    monkeypatch.setattr(settings, "nl2sql_llm_api_key", SecretStr("fake-schema-test-key"))
    monkeypatch.setattr(settings, "nl2sql_llm_model", MODEL)
    with TestClient(main.app) as test_client:
        yield test_client


def stub_llm(monkeypatch, sql="SELECT id FROM users"):
    generate = AsyncMock(return_value=LLMGeneration(sql=sql, model=MODEL))
    factory = Mock(return_value=SimpleNamespace(generate=generate))
    monkeypatch.setattr(main, "LLMN2SQLClient", factory)
    return generate


def request_payload(schema):
    return {"text": "show users", "dialect": "postgres", "schema": schema}


def assert_invalid_schema(response):
    assert response.status_code == 422
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "VALIDATION_FAILED"
    assert data["request_id"] == response.headers["X-Request-ID"]
    assert "timestamp" in data


@pytest.mark.parametrize("schema", [None, {}])
def test_schema_optional_and_empty_requests_are_not_schema_grounded(client, monkeypatch, schema):
    generate = stub_llm(monkeypatch, "SELECT 1")

    response = client.post("/api/nl2sql", json=request_payload(schema))

    assert response.status_code == 200
    assert response.json()["provider"] == "llm"
    assert response.json()["schema_used"] is False
    if schema is None:
        generate.assert_awaited_once_with("show users", "postgres", None, None)


def test_schema_success_passes_structured_schema_and_marks_response(client, monkeypatch):
    generate = stub_llm(monkeypatch)

    response = client.post("/api/nl2sql", json=request_payload(SCHEMA))

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["provider"] == "llm"
    assert data["schema_used"] is True
    assert data["fallback_reason"] is None
    generate.assert_awaited_once()
    assert generate.await_args.args == ("show users", "postgres", None, None)
    forwarded = generate.await_args.kwargs["schema"]
    assert forwarded["tables"][0]["name"] == "users"
    assert [column["name"] for column in forwarded["tables"][0]["columns"]] == ["id", "name"]
    assert forwarded["relationships"] == SCHEMA["relationships"]
    assert "schema" not in data


@pytest.mark.parametrize("enabled,text", [(False, "show users"), (True, "insert users"), (True, "update users"), (True, "delete users")])
def test_schema_reaches_deterministic_generation_without_changing_no_schema_baseline(
    client, monkeypatch, enabled, text
):
    monkeypatch.setattr(settings, "nl2sql_llm_enabled", enabled)
    generate = stub_llm(monkeypatch)
    worker = AsyncMock(wraps=main._run_cpu_bound)
    monkeypatch.setattr(main, "_run_cpu_bound", worker)
    payload = {**request_payload(None), "text": text}
    baseline = client.post("/api/nl2sql", json=payload)
    worker.reset_mock()

    response = client.post("/api/nl2sql", json={**payload, "schema": SCHEMA})

    assert response.status_code == baseline.status_code == 200
    actual = response.json()
    assert baseline.json()["provider"] == "deterministic"
    assert actual["schema_used"] is True
    assert actual["provider"] == "deterministic"
    assert actual["success"] is True
    call = worker.await_args
    assert call.args[:5] == (main.nl2sql_generator.generate, text, "postgres", None, None)
    assert call.args[5].tables[0].name == "users"
    generate.assert_not_awaited()


@pytest.mark.parametrize("sql", [
    "SELECT id FROM private_users",
    "SELECT u.password FROM users AS u",
    "SELECT password FROM users",
    "SELECT o.password FROM users AS u JOIN orders AS o ON o.user_id = u.id",
])
def test_unknown_schema_tables_and_columns_use_existing_fallback(client, monkeypatch, sql):
    stub_llm(monkeypatch, sql)

    response = client.post("/api/nl2sql", json=request_payload(SCHEMA))

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "deterministic"
    assert data["fallback_reason"] == "invalid_sql"
    assert data["schema_used"] is True
    assert "password" not in response.text
    assert "private_users" not in response.text


def test_schema_validation_failure_without_fallback_is_a_safe_llm_failure(client, monkeypatch):
    monkeypatch.setattr(settings, "nl2sql_llm_fallback", False)
    stub_llm(monkeypatch, "SELECT private_column FROM users")

    response = client.post("/api/nl2sql", json=request_payload(SCHEMA))

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert data["provider"] == "llm"
    assert data["fallback_reason"] is None
    assert data["schema_used"] is False
    assert "private_column" not in response.text


@pytest.mark.parametrize("sql,schema", [
    ("SELECT u.id FROM users AS u", SCHEMA),
    ("SELECT U.ID FROM USERS AS U", SCHEMA),
    ("SELECT * FROM users", SCHEMA),
    ("SELECT u.* FROM users AS u", SCHEMA),
    ("SELECT u.id, o.user_id FROM users AS u JOIN orders AS o ON o.user_id = u.id", SCHEMA),
    ("SELECT id FROM users UNION SELECT user_id FROM orders", SCHEMA),
    ("SELECT arbitrary_column FROM users", {"tables": [{"name": "users"}]}),
    ("SELECT u.arbitrary_column FROM users AS u", {"tables": [{"name": "users", "columns": []}]}),
    ("SELECT u.id FROM app.users AS u", {"tables": [{"name": "app.users", "columns": [{"name": "id"}]}]}),
])
def test_allowed_schema_queries_preserve_sql(client, monkeypatch, sql, schema):
    stub_llm(monkeypatch, sql)

    response = client.post("/api/nl2sql", json=request_payload(schema))

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "llm"
    assert data["schema_used"] is True
    assert data["sql"] == sql


def test_schema_does_not_restrict_existing_generation_without_schema(client, monkeypatch):
    sql = "SELECT password FROM private_users"
    stub_llm(monkeypatch, sql)

    response = client.post("/api/nl2sql", json={"text": "show users", "dialect": "postgres"})

    assert response.status_code == 200
    assert response.json()["provider"] == "llm"
    assert response.json()["sql"] == sql
    assert response.json()["schema_used"] is False


@pytest.mark.parametrize("identifier", ["users", "_users", "users$archive", "app.users", "db.app.users", "a" * 128])
def test_schema_accepts_supported_identifiers(client, monkeypatch, identifier):
    monkeypatch.setattr(settings, "nl2sql_llm_enabled", False)
    schema = {"tables": [{"name": identifier, "columns": [{"name": identifier, "type": "DECIMAL(10, 2)"}]}]}

    response = client.post("/api/nl2sql", json=request_payload(schema))

    assert response.status_code == 200


@pytest.mark.parametrize("identifier", [
    "", "1users", "users..id", ".users", "users.", "users id", "users;DROP",
    '"users"', "用户", "a" * 129,
    "users\n", "us\ners", "users\r", "us\rers", "users\t", "us\ters",
    " users", "users ", "\nusers", "\rusers", "\tusers",
])
def test_schema_rejects_unsafe_or_overlength_table_identifiers(client, monkeypatch, identifier):
    generate = stub_llm(monkeypatch)

    response = client.post("/api/nl2sql", json=request_payload({"tables": [{"name": identifier}]}))

    assert_invalid_schema(response)
    generate.assert_not_awaited()


@pytest.mark.parametrize("location", ["table", "column", "from_table", "from_column", "to_table", "to_column"])
def test_invalid_schema_identifiers_are_not_echoed_in_422_or_logs(client, monkeypatch, caplog, location):
    sentinel = "private_schema_identifier;DROP"
    schema = deepcopy(SCHEMA)
    if location == "table":
        schema["tables"][0]["name"] = sentinel
    elif location == "column":
        schema["tables"][0]["columns"][0]["name"] = sentinel
    else:
        schema["relationships"][0][location] = sentinel
    generate = stub_llm(monkeypatch)

    response = client.post("/api/nl2sql", json=request_payload(schema))

    assert_invalid_schema(response)
    assert sentinel not in response.text
    assert sentinel not in caplog.text
    generate.assert_not_awaited()


@pytest.mark.parametrize("schema", [
    {"tables": [{"name": f"table_{index}"} for index in range(51)]},
    {"tables": [{"name": "users", "columns": [{"name": f"col_{index}"} for index in range(201)]}]},
    {"tables": [
        {"name": f"table_{index}", "columns": [{"name": f"col_{column}"} for column in range(200 if index < 5 else 1)]}
        for index in range(6)
    ]},
])
def test_schema_size_limits_reject_excess_without_invoking_llm(client, monkeypatch, schema):
    generate = stub_llm(monkeypatch)

    response = client.post("/api/nl2sql", json=request_payload(schema))

    assert_invalid_schema(response)
    generate.assert_not_awaited()


@pytest.mark.parametrize("table_count,column_count", [(50, 20), (5, 200)])
def test_schema_size_boundaries_are_inclusive(client, monkeypatch, table_count, column_count):
    monkeypatch.setattr(settings, "nl2sql_llm_enabled", False)
    schema = {"tables": [
        {"name": f"table_{index}", "columns": [{"name": f"col_{column}"} for column in range(column_count)]}
        for index in range(table_count)
    ]}

    response = client.post("/api/nl2sql", json=request_payload(schema))

    assert response.status_code == 200


@pytest.mark.parametrize("schema", [[], "private_schema_payload", {"tables": None}, {"tables": [{"name": 123}]}, {"tables": [{"name": "users", "columns": None}]}])
def test_malformed_schema_shape_is_rejected(client, monkeypatch, schema):
    generate = stub_llm(monkeypatch)

    response = client.post("/api/nl2sql", json=request_payload(schema))

    assert_invalid_schema(response)
    assert "private_schema_payload" not in response.text
    generate.assert_not_awaited()


def test_schema_metadata_is_not_logged_or_echoed_in_success_response(client, monkeypatch, caplog):
    sentinel = "private_schema_metadata_sentinel"
    schema = deepcopy(SCHEMA)
    schema["tables"][0]["columns"][0]["type"] = sentinel
    schema["tables"].append({"name": sentinel, "columns": [{"name": sentinel}]})
    stub_llm(monkeypatch)

    response = client.post("/api/nl2sql", json=request_payload(schema))

    assert response.status_code == 200
    assert response.json()["schema_used"] is True
    assert sentinel not in caplog.text
    assert sentinel not in response.text


@pytest.mark.parametrize("changes", [
    {"text": None},
    {"text": ["show users"]},
    {"dialect": ["postgres"]},
    {"table_hint": {"name": "users"}},
    {"column_hints": "id"},
])
def test_top_level_validation_does_not_echo_valid_schema(client, monkeypatch, caplog, changes):
    sentinel = "private_schema_top_level_error_sentinel"
    schema = {"tables": [{"name": "users", "columns": [{"name": "id", "type": sentinel}]}]}
    generate = stub_llm(monkeypatch)

    response = client.post("/api/nl2sql", json={**request_payload(schema), **changes})

    assert_invalid_schema(response)
    assert sentinel not in response.text
    assert sentinel not in caplog.text
    generate.assert_not_awaited()


def test_missing_required_text_does_not_echo_valid_schema(client, monkeypatch, caplog):
    sentinel = "private_schema_missing_text_sentinel"
    schema = {"tables": [{"name": "users", "columns": [{"name": "id", "type": sentinel}]}]}
    generate = stub_llm(monkeypatch)

    response = client.post("/api/nl2sql", json={"dialect": "postgres", "schema": schema})

    assert_invalid_schema(response)
    assert sentinel not in response.text
    assert sentinel not in caplog.text
    generate.assert_not_awaited()


def test_schema_model_list_defaults_are_independent():
    first_schema = main.SchemaDefinition()
    second_schema = main.SchemaDefinition()
    first_table = main.SchemaTable(name="users")
    second_table = main.SchemaTable(name="orders")

    first_schema.tables.append(first_table)
    first_schema.relationships.append(main.SchemaRelationship(
        from_table="users", from_column="id", to_table="orders", to_column="user_id",
    ))
    first_table.columns.append(main.SchemaColumn(name="id"))

    assert second_schema.tables == []
    assert second_schema.relationships == []
    assert second_table.columns == []


def test_relationship_endpoint_missing_table_is_rejected_at_api_boundary(client, monkeypatch):
    generate = stub_llm(monkeypatch)
    response = client.post(
        "/api/nl2sql",
        json={
            "text": "show users",
            "dialect": "postgres",
            "schema": {
                "tables": [{"name": "users", "columns": [{"name": "id"}]}],
                "relationships": [{
                    "from_table": "orders",
                    "from_column": "user_id",
                    "to_table": "users",
                    "to_column": "id",
                }],
            },
        },
    )
    assert_invalid_schema(response)
    generate.assert_not_awaited()


def test_schema_relationship_limit_rejects_201_entries(client, monkeypatch):
    generate = stub_llm(monkeypatch)
    relationship = {
        "from_table": "orders",
        "from_column": "user_id",
        "to_table": "users",
        "to_column": "id",
    }
    response = client.post(
        "/api/nl2sql",
        json={
            "text": "show users",
            "dialect": "postgres",
            "schema": {
                "tables": [
                    {"name": "users", "columns": [{"name": "id"}]},
                    {"name": "orders", "columns": [{"name": "user_id"}]},
                ],
                "relationships": [relationship for _ in range(201)],
            },
        },
    )
    assert_invalid_schema(response)
    generate.assert_not_awaited()
