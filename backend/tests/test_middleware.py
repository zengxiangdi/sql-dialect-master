"""Regression tests for security-sensitive HTTP middleware."""

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.middleware import (
    DEFAULT_MAX_REQUEST_BODY_BYTES,
    RateLimitMiddleware,
    RateLimiter,
    SecurityHeadersMiddleware,
    StructuredLoggingMiddleware,
)

REQUEST_ID = "12345678-1234-4123-8123-123456789abc"


def make_app(rate_limit: int = 2) -> FastAPI:
    app = FastAPI()
    limiter = RateLimiter(requests_per_window=rate_limit, window_seconds=60)

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitMiddleware, limiter=limiter, enabled=True)
    app.add_middleware(StructuredLoggingMiddleware)

    @app.get("/api/test")
    async def test_endpoint():
        return {"success": True}

    @app.post("/api/echo")
    async def echo_endpoint(request: Request):
        return {"size": len(await request.body())}

    @app.get("/health")
    async def health_endpoint():
        return {"status": "healthy"}

    return app


def assert_standard_error(response, status_code: int, error_code: str, request_id: str = REQUEST_ID):
    assert response.status_code == status_code
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == error_code
    assert "timestamp" in data
    assert data["request_id"] == request_id
    assert response.headers["X-Request-ID"] == request_id


def test_rate_limit_headers_are_added():
    client = TestClient(make_app(rate_limit=2))
    response = client.get("/api/test")
    assert response.status_code == 200
    assert response.headers["X-RateLimit-Limit"] == "2"
    assert response.headers["X-RateLimit-Remaining"] == "1"
    assert "X-RateLimit-Reset" in response.headers


def test_rate_limit_returns_429_with_standard_contract():
    client = TestClient(make_app(rate_limit=1))
    first = client.get("/api/test", headers={"X-Request-ID": REQUEST_ID})
    second = client.get("/api/test", headers={"X-Request-ID": REQUEST_ID})
    assert first.status_code == 200
    assert_standard_error(second, 429, "RATE_LIMITED")
    assert second.headers["Retry-After"].isdigit()
    assert second.headers["X-RateLimit-Remaining"] == "0"
    assert "retry_after" in second.json()["error"]


def test_forwarded_for_cannot_change_client_identity():
    client = TestClient(make_app(rate_limit=1))
    first = client.get("/api/test", headers={"X-Forwarded-For": "203.0.113.10"})
    second = client.get("/api/test", headers={"X-Forwarded-For": "198.51.100.20"})
    assert first.status_code == 200
    assert second.status_code == 429


def test_health_check_bypasses_rate_limit():
    client = TestClient(make_app(rate_limit=1))
    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200


def test_oversized_content_length_uses_payload_too_large_contract():
    client = TestClient(make_app(rate_limit=100))
    response = client.post(
        "/api/echo",
        content=b"x",
        headers={"Content-Length": str(DEFAULT_MAX_REQUEST_BODY_BYTES + 1), "X-Request-ID": REQUEST_ID},
    )
    assert_standard_error(response, 413, "PAYLOAD_TOO_LARGE")
    assert response.json()["error"]["max_bytes"] == DEFAULT_MAX_REQUEST_BODY_BYTES


def test_invalid_content_length_uses_bad_request_contract():
    client = TestClient(make_app(rate_limit=100))
    response = client.post(
        "/api/echo",
        content=b"x",
        headers={"Content-Length": "invalid", "X-Request-ID": REQUEST_ID},
    )
    assert_standard_error(response, 400, "BAD_REQUEST")
    assert response.json()["error"]["message"] == "Invalid Content-Length"


def test_method_not_allowed_uses_standard_contract():
    client = TestClient(make_app(rate_limit=100))
    response = client.post("/api/test", headers={"X-Request-ID": REQUEST_ID})
    assert_standard_error(response, 405, "METHOD_NOT_ALLOWED")


def test_security_headers_are_present():
    client = TestClient(make_app())
    response = client.get("/api/test")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
