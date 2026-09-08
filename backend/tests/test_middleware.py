"""Regression tests for security-sensitive HTTP middleware."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.middleware import (
    RateLimitMiddleware,
    RateLimiter,
    SecurityHeadersMiddleware,
)


def make_app(rate_limit: int = 2) -> FastAPI:
    app = FastAPI()
    limiter = RateLimiter(requests_per_window=rate_limit, window_seconds=60)

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitMiddleware, limiter=limiter, enabled=True)

    @app.get("/api/test")
    async def test_endpoint():
        return {"success": True}

    @app.get("/health")
    async def health_endpoint():
        return {"status": "healthy"}

    return app


def test_rate_limit_headers_are_added():
    client = TestClient(make_app(rate_limit=2))

    response = client.get("/api/test")

    assert response.status_code == 200
    assert response.headers["X-RateLimit-Limit"] == "2"
    assert response.headers["X-RateLimit-Remaining"] == "1"
    assert "X-RateLimit-Reset" in response.headers


def test_rate_limit_returns_429_after_limit():
    client = TestClient(make_app(rate_limit=1))

    first = client.get("/api/test")
    second = client.get("/api/test")

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["Retry-After"].isdigit()
    assert second.headers["X-RateLimit-Remaining"] == "0"
    assert second.json()["error"]["code"] == 429


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


def test_security_headers_are_present():
    client = TestClient(make_app())

    response = client.get("/api/test")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
