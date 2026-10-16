"""Contracts exercised by the React-only web client."""
from fastapi.testclient import TestClient

from backend.api.main import app

client = TestClient(app)


def test_types_filtered_matrix_is_an_array_with_canonical_type_and_source_target():
    response = client.get("/api/types?source=mysql&target=postgres")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["mappings"], list)
    entry = next(item for item in payload["mappings"] if item["type"] == "VARCHAR")
    assert entry["type"] == "VARCHAR"
    assert entry["source"]
    assert entry["target"]


def test_types_full_matrix_is_also_an_array():
    response = client.get("/api/types")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["mappings"], list)
    assert any(item["type"] == "VARCHAR" for item in payload["mappings"])


def test_function_search_and_category_filters_are_composed():
    response = client.get("/api/functions?search=trim&category=string&limit=100")
    assert response.status_code == 200
    payload = response.json()
    assert payload["functions"]
    assert all(item["category"] == "string" for item in payload["functions"])
