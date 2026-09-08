import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.core.config import settings, SUPPORTED_DIALECTS
from backend.core.type_mapping import TypeMapper


client = TestClient(app)


def test_api_version_comes_from_settings():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["version"] == settings.api_version
    assert response.headers["X-API-Version"] == settings.api_version


def test_parse_normalizes_dialect():
    response = client.post("/api/parse", json={
        "sql": "SELECT 1",
        "dialect": "MySQL",
    })
    assert response.status_code == 200
    assert response.json()["dialect"] == "mysql"


def test_parse_rejects_unknown_dialect():
    response = client.post("/api/parse", json={
        "sql": "SELECT 1",
        "dialect": "not_a_db",
    })
    assert response.status_code == 400
    assert response.json()["success"] is False


def test_nl2sql_normalizes_dialect():
    response = client.post("/api/nl2sql", json={
        "text": "查询所有用户",
        "dialect": "MYSQL",
    })
    assert response.status_code == 200
    assert response.json()["dialect"] == "mysql"


def test_nl2sql_rejects_unknown_dialect():
    response = client.post("/api/nl2sql", json={
        "text": "查询所有用户",
        "dialect": "not_a_db",
    })
    assert response.status_code == 400
    assert response.json()["success"] is False


def test_types_endpoint_validates_query_dialects():
    response = client.get("/api/types?source=not_a_db")
    assert response.status_code == 400
    assert response.json()["success"] is False


def test_type_mapper_rejects_unknown_dialect_at_core_boundary():
    mapper = TypeMapper()
    result = mapper.map_type("VARCHAR", "not_a_db", "mysql")
    assert result["success"] is False
    assert "not_a_db" in result["error"]


def test_allowed_origins_are_centralized():
    assert settings.allowed_origins
    assert "localhost:8501" in settings.allowed_origins
    assert all(dialect in SUPPORTED_DIALECTS for dialect in settings.model_dump().get("allowed_origins", "").split(",") if dialect.startswith("http") is False) is True
