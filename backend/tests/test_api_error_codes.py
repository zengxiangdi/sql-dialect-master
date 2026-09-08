"""API-level regression tests for the public error_code contract."""

from fastapi.testclient import TestClient

from backend.api.main import app


client = TestClient(app)


def test_convert_response_exposes_error_code_for_validation_failure() -> None:
    response = client.post(
        "/api/convert",
        json={
            "sql": "",
            "source_dialect": "mysql",
            "target_dialect": "postgres",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert data["error_code"] == "VALIDATION_FAILED"


def test_convert_success_response_keeps_error_code_nullable() -> None:
    response = client.post(
        "/api/convert",
        json={
            "sql": "SELECT 1",
            "source_dialect": "mysql",
            "target_dialect": "postgres",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["error_code"] is None


def test_convert_normalizes_dialect_whitespace_and_case() -> None:
    response = client.post(
        "/api/convert",
        json={
            "sql": "SELECT 1",
            "source_dialect": " MySQL ",
            "target_dialect": " POSTGRES ",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["source_dialect"] == "mysql"
    assert data["target_dialect"] == "postgres"
