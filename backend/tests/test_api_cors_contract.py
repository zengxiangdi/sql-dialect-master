"""Cross-origin browser contract for the public API request layer."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.api.middleware import RateLimiter, RateLimitMiddleware

client = TestClient(app)
ORIGIN = "http://localhost:8501"


def test_cors_preflight_allows_request_headers_used_by_react() -> None:
    response = client.options(
        "/api/convert",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-api-key,x-request-id",
        },
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
    assert "POST" in response.headers["Access-Control-Allow-Methods"]
    allowed_headers = response.headers["Access-Control-Allow-Headers"].lower()
    assert "x-api-key" in allowed_headers
    assert "x-request-id" in allowed_headers


def test_cors_exposes_operational_headers_to_browser_clients() -> None:
    response = client.get("/health", headers={"Origin": ORIGIN})

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
    exposed = {
        value.strip().lower()
        for value in response.headers["Access-Control-Expose-Headers"].split(",")
    }
    assert {"retry-after", "x-process-time", "x-request-id"} <= exposed


def test_gzipped_error_keeps_the_same_machine_readable_contract() -> None:
    """Error normalization must also run after the compression middleware."""
    response = client.post(
        "/api/convert",
        json={
            "sql": "SELECT 1",
            "source_dialect": "x" * 20_000,
            "target_dialect": "mysql",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "BAD_REQUEST"
    assert payload["request_id"] == response.headers["X-Request-ID"]
    # The normalized response is rebuilt after decompression, so it must not
    # advertise a stale gzip encoding for its plain JSON bytes.
    assert response.headers.get("Content-Encoding") is None


def test_cors_preflight_does_not_consume_business_rate_limit() -> None:
    local_app = FastAPI()
    local_app.add_middleware(
        CORSMiddleware,
        allow_origins=[ORIGIN],
        allow_methods=["POST", "OPTIONS"],
        allow_headers=["content-type", "x-request-id"],
    )
    local_app.add_middleware(
        RateLimitMiddleware,
        limiter=RateLimiter(requests_per_window=1, window_seconds=60),
    )
    local_client = TestClient(local_app)
    headers = {
        "Origin": ORIGIN,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-request-id",
    }

    assert local_client.options("/api/convert", headers=headers).status_code == 200
    assert local_client.options("/api/convert", headers=headers).status_code == 200
