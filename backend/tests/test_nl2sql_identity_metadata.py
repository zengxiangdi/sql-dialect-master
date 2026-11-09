"""Schema table primary-key metadata validation and normalization contracts."""

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.api import main
from backend.core.config import settings
from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_schema import SchemaContext


def table(*, columns=None, primary_key=None):
    value = {"name": "users"}
    if columns is not None:
        value["columns"] = [{"name": column} for column in columns]
    if primary_key is not None:
        value["primary_key"] = primary_key
    return value


def schema(table_value):
    return {"tables": [table_value], "relationships": []}


def test_api_accepts_single_and_composite_primary_keys():
    model = main.SchemaDefinition.model_validate({
        "tables": [
            table(columns=["id", "name"], primary_key=["id"]),
            {"name": "tenant_users", "columns": [
                {"name": "tenant_id"}, {"name": "id"},
            ], "primary_key": ["tenant_id", "id"]},
        ],
    })

    assert model.tables[0].primary_key == ["id"]
    assert model.tables[1].primary_key == ["tenant_id", "id"]
    assert model.model_dump(exclude_none=True)["tables"][0]["primary_key"] == ["id"]


@pytest.mark.parametrize("primary_key", [[], ["id"] * 2, ["id"] * 9, ["bad-name"]])
def test_api_rejects_empty_duplicate_overlong_and_invalid_primary_keys(primary_key):
    with pytest.raises(ValidationError):
        main.SchemaDefinition.model_validate(
            schema(table(columns=["id"], primary_key=primary_key))
        )


def test_api_rejects_primary_key_unknown_to_declared_columns():
    with pytest.raises(ValidationError):
        main.SchemaDefinition.model_validate(
            schema(table(columns=["id"], primary_key=["missing"]))
        )


def test_api_primary_key_validation_preserves_422_error_envelope(monkeypatch):
    monkeypatch.setattr(settings, "api_key", None)
    monkeypatch.setattr(settings, "nl2sql_llm_enabled", False)
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/nl2sql",
            json={
                "text": "show users",
                "dialect": "postgres",
                "schema": schema(table(columns=["id"], primary_key=["missing"])),
            },
        )

    assert response.status_code == 422
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "VALIDATION_FAILED"
    assert payload["request_id"] == response.headers["X-Request-ID"]


def test_api_allows_unverified_primary_key_without_column_metadata():
    model = main.SchemaDefinition.model_validate(
        schema(table(columns=[], primary_key=["Tenant_ID", "ID"]))
    )
    assert model.tables[0].primary_key == ["Tenant_ID", "ID"]


def test_old_schema_shape_dumps_without_primary_key():
    model = main.SchemaDefinition.model_validate(schema(table(columns=["id"])))
    assert model.model_dump(exclude_none=True) == {
        "tables": [{"name": "users", "columns": [{"name": "id"}]}],
        "relationships": [],
    }


@pytest.mark.parametrize("raw_primary_key", [[], ["id", "ID"], ["missing"], ["id"] * 9, ["bad-name"]])
def test_core_rejects_invalid_primary_key_metadata(raw_primary_key):
    context = SchemaContext.from_mapping(
        schema(table(columns=["id"], primary_key=raw_primary_key))
    )
    assert context.is_valid is False


def test_core_normalizes_case_and_preserves_declared_column_spelling():
    context = SchemaContext.from_mapping(
        schema(table(columns=["Tenant_ID", "ID"], primary_key=["tenant_id", "id"]))
    )

    assert context.is_valid
    table_context = context.tables[0]
    assert table_context.primary_key == ("Tenant_ID", "ID")
    assert table_context.identity_columns == ("Tenant_ID", "ID")


def test_core_retains_unverified_primary_key_without_column_metadata():
    context = SchemaContext.from_mapping(
        schema(table(columns=[], primary_key=["Tenant_ID", "ID"]))
    )

    assert context.is_valid
    assert context.tables[0].primary_key == ("Tenant_ID", "ID")


def test_core_defaults_primary_key_to_empty_tuple():
    context = SchemaContext.from_mapping(schema(table(columns=["id"])))

    assert context.is_valid
    assert context.tables[0].primary_key == ()
    assert context.tables[0].identity_columns == ()


def test_schema_payload_with_primary_key_is_json_serializable_for_llm():
    payload = main.SchemaDefinition.model_validate(
        schema(table(columns=["tenant_id", "id"], primary_key=["tenant_id", "id"]))
    ).model_dump(exclude_none=True)

    encoded = json.dumps({"schema": payload})
    assert '"primary_key": ["tenant_id", "id"]' in encoded


def test_primary_key_metadata_does_not_enable_unique_count_or_change_no_schema():
    schema_payload = {
        "tables": [
            {"name": "users", "columns": [{"name": "id"}], "primary_key": ["id"]},
            {"name": "orders", "columns": [
                {"name": "id"}, {"name": "user_id"}, {"name": "product_id"},
            ]},
            {"name": "products", "columns": [{"name": "id"}]},
        ],
        "relationships": [
            {"from_table": "orders", "from_column": "user_id", "to_table": "users", "to_column": "id"},
            {"from_table": "orders", "from_column": "product_id", "to_table": "products", "to_column": "id"},
        ],
    }
    schema_context = SchemaContext.from_mapping(schema_payload)
    assert schema_context.is_valid
    assert not NL2SQLGenerator().generate(
        "count products per user", "postgres", schema=schema_context
    ).success

    no_schema = NL2SQLGenerator().generate("show users", "postgres")
    assert no_schema.success
    assert no_schema.sql == "-- Generated for POSTGRES\nSELECT *\nFROM users"

