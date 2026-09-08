from fastapi.testclient import TestClient

from backend.api.main import app


client = TestClient(app)


def test_type_mapping_normalizes_dialect_whitespace_and_case() -> None:
    response = client.post(
        "/api/types/map",
        json={
            "type_name": "VARCHAR",
            "source_dialect": " MySQL ",
            "target_dialect": " POSTGRES ",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["target_dialect"] == "postgres"


def test_type_mapping_rejects_unsupported_dialect_after_normalization() -> None:
    response = client.post(
        "/api/types/map",
        json={
            "type_name": "VARCHAR",
            "source_dialect": " invalid_db ",
            "target_dialect": " POSTGRES ",
        },
    )

    assert response.status_code == 400
