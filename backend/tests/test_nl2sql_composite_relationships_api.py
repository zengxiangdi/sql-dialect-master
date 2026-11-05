"""API validation contracts for composite schema relationships."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.api import main
from backend.core.config import settings


def tables(*, with_columns=True):
    columns = [{"name": "tenant_id"}, {"name": "id"}] if with_columns else []
    return [
        {"name": "users", "columns": columns},
        {"name": "orders", "columns": [
            {"name": "tenant_id"}, {"name": "user_id"}, {"name": "id"}
        ]},
    ]


def composite_schema():
    return {
        "tables": tables(),
        "relationships": [{
            "from_table": "orders",
            "to_table": "users",
            "columns": [
                {"from_column": "tenant_id", "to_column": "tenant_id"},
                {"from_column": "user_id", "to_column": "id"},
            ],
        }],
    }


def test_legacy_and_composite_relationship_models_are_accepted():
    legacy = main.SchemaDefinition.model_validate({
        "tables": tables(),
        "relationships": [{
            "from_table": "orders", "from_column": "user_id",
            "to_table": "users", "to_column": "id",
        }],
    })
    assert legacy.relationships[0].columns is None
    composite = main.SchemaDefinition.model_validate(composite_schema())
    assert len(composite.relationships[0].columns) == 2


@pytest.mark.parametrize("relationship", [
    {
        "from_table": "orders", "from_column": "user_id",
        "to_table": "users", "to_column": "id",
        "columns": [{"from_column": "tenant_id", "to_column": "tenant_id"}],
    },
    {
        "from_table": "orders", "to_table": "users",
        "columns": [],
    },
    {
        "from_table": "orders", "to_table": "users",
        "columns": [{"from_column": "tenant_id"}],
    },
])
def test_invalid_composite_relationship_shapes_are_rejected(relationship):
    with pytest.raises(ValidationError):
        main.SchemaDefinition.model_validate({"tables": tables(), "relationships": [relationship]})


def test_composite_duplicate_pairs_and_unknown_columns_are_rejected():
    duplicate = composite_schema()
    duplicate["relationships"][0]["columns"].append(
        {"from_column": "TENANT_ID", "to_column": "tenant_id"}
    )
    with pytest.raises(ValidationError):
        main.SchemaDefinition.model_validate(duplicate)

    unknown = composite_schema()
    unknown["relationships"][0]["columns"][0]["from_column"] = "missing"
    with pytest.raises(ValidationError):
        main.SchemaDefinition.model_validate(unknown)


def test_composite_pair_count_budget_is_enforced():
    relationships = [{
        "from_table": "orders", "to_table": "users",
        "columns": [
            {"from_column": "tenant_id", "to_column": "tenant_id"},
            {"from_column": "user_id", "to_column": "id"},
            {"from_column": "id", "to_column": "id"},
            {"from_column": "tenant_id", "to_column": "id"},
            {"from_column": "id", "to_column": "tenant_id"},
            {"from_column": "user_id", "to_column": "tenant_id"},
            {"from_column": "tenant_id", "to_column": "user_id"},
            {"from_column": "id", "to_column": "user_id"},
        ],
    }]
    relationships *= 128
    assert len(main.SchemaDefinition.model_validate({"tables": tables(with_columns=False), "relationships": relationships}).relationships) == 128
    with pytest.raises(ValidationError):
        main.SchemaDefinition.model_validate({"tables": tables(), "relationships": relationships + [relationships[0]]})


def test_composite_schema_endpoint_returns_existing_validation_envelope(monkeypatch):
    monkeypatch.setattr(settings, "api_key", None)
    monkeypatch.setattr(settings, "nl2sql_llm_enabled", False)
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.post("/api/nl2sql", json={
            "text": "show users",
            "dialect": "postgres",
            "schema": composite_schema(),
        })
    assert response.status_code == 200
    assert response.json()["schema_used"] is True

    invalid = composite_schema()
    invalid["relationships"][0]["columns"] = []
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.post("/api/nl2sql", json={
            "text": "show users", "dialect": "postgres", "schema": invalid,
        })
    assert response.status_code == 422
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "VALIDATION_FAILED"
    assert "tenant_id" not in response.text
    assert "from_column" not in response.text
