#!/usr/bin/env python3
"""Regression tests for the unified API 4xx error contract."""

from fastapi.testclient import TestClient

from backend.api.main import app


client = TestClient(app)
REQUEST_ID = "12345678-1234-4123-8123-123456789abc"


def _assert_error_contract(response, *, status_code, error_code):
    assert response.status_code == status_code
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == error_code
    assert data["request_id"] == REQUEST_ID
    assert response.headers["X-Request-ID"] == REQUEST_ID
    assert "timestamp" in data


def test_validation_error_uses_stable_code_and_safe_detail():
    """FastAPI request validation must use a stable machine-readable code."""
    response = client.post(
        "/api/convert",
        json={"sql": "SELECT 1"},
        headers={"X-Request-ID": REQUEST_ID},
    )

    _assert_error_contract(
        response,
        status_code=422,
        error_code="VALIDATION_FAILED",
    )
    assert isinstance(response.json()["error"]["details"], list)


def test_not_found_uses_stable_code():
    """Unknown routes must use a stable NOT_FOUND code."""
    response = client.get(
        "/api/does-not-exist",
        headers={"X-Request-ID": REQUEST_ID},
    )

    _assert_error_contract(
        response,
        status_code=404,
        error_code="NOT_FOUND",
    )


def test_business_http_400_keeps_client_safe_detail():
    """Known client errors keep their useful detail without exposing internals."""
    response = client.post(
        "/api/convert",
        json={
            "sql": "SELECT 1",
            "source_dialect": "invalid_db",
            "target_dialect": "mysql",
        },
        headers={"X-Request-ID": REQUEST_ID},
    )

    _assert_error_contract(
        response,
        status_code=400,
        error_code="BAD_REQUEST",
    )
    assert "Unsupported source dialect" in response.json()["error"]["message"]
    assert "invalid_db" in response.json()["error"]["message"]


def test_validation_error_does_not_expose_server_internals():
    """422 payloads must not expose Python/Pydantic implementation details."""
    response = client.post(
        "/api/convert",
        content="not valid json",
        headers={
            "Content-Type": "application/json",
            "X-Request-ID": REQUEST_ID,
        },
    )

    _assert_error_contract(
        response,
        status_code=422,
        error_code="VALIDATION_FAILED",
    )
    body = response.text.lower()
    assert "traceback" not in body
    assert "validationerror" not in body
