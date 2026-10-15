"""Contracts exercised by the React-only web client."""
from fastapi.testclient import TestClient

from backend.api.main import app

client = TestClient(app)


def test_types_filtered_matrix_is_keyed_by_canonical_type_and_has_source_target():
    response = client.get("/api/types?source=mysql&target=postgres")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["mappings"], dict)
    entry = payload["mappings"]["VARCHAR"]
    assert entry["type"] == "VARCHAR"
    assert entry["source"]
    assert entry["target"]


def test_function_search_and_category_filters_are_composed():
    response = client.get("/api/functions?search=trim&category=string&limit=100")
    assert response.status_code == 200
    payload = response.json()
    assert payload["functions"]
    assert all(item["category"] == "string" for item in payload["functions"])
