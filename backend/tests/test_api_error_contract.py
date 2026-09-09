#!/usr/bin/env python3
"""Regression tests for the API exception boundary."""

from fastapi.testclient import TestClient

from backend.api.main import app
from backend.core.exceptions import TranspileError


client = TestClient(app, raise_server_exceptions=False)


def test_unhandled_exception_returns_generic_internal_error(monkeypatch):
    """Unexpected exceptions must not expose implementation details to clients."""

    def explode(*args, **kwargs):
        raise RuntimeError("secret database password and stack detail")

    monkeypatch.setattr("backend.api.main.transpiler.transpile", explode)

    response = client.post(
        "/api/convert",
        json={
            "sql": "SELECT 1",
            "source_dialect": "mysql",
            "target_dialect": "postgres",
        },
        headers={"X-Request-ID": "12345678-1234-4123-8123-123456789abc"},
    )

    assert response.status_code == 500
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "INTERNAL_ERROR"
    assert data["error"]["message"] == "Internal server error"
    assert "secret database password" not in response.text
    assert data["request_id"] == "12345678-1234-4123-8123-123456789abc"


def test_sdm_exception_returns_stable_error_code(monkeypatch):
    """Known domain exceptions must retain stable machine-readable codes."""

    def fail(*args, **kwargs):
        raise TranspileError("transpiler rejected statement")

    monkeypatch.setattr("backend.api.main.transpiler.transpile", fail)

    response = client.post(
        "/api/convert",
        json={
            "sql": "SELECT 1",
            "source_dialect": "mysql",
            "target_dialect": "postgres",
        },
        headers={"X-Request-ID": "12345678-1234-4123-8123-123456789abc"},
    )

    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "TRANSPILE_FAILED"
    assert data["error"]["error_code"] == "TRANSPILE_FAILED"
    assert data["error"]["message"] == "transpiler rejected statement"
    assert response.headers["X-Request-ID"] == "12345678-1234-4123-8123-123456789abc"
