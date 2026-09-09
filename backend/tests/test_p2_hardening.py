"""Regression coverage for the P2 hardening changes."""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.middleware import (
    DEFAULT_MAX_REQUEST_BODY_BYTES,
    RateLimitMiddleware,
)
from backend.api.readiness import _get_checks
from backend.core.post_processor import PostProcessor
from backend.core.sql_scanner import mask_non_executable, replace_outside
from backend.core.transpiler import SQLTranspiler


def make_middleware_app(rate_limit: int = 10) -> FastAPI:
    app = FastAPI()
    from backend.api.middleware import RateLimiter, SecurityHeadersMiddleware

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        RateLimitMiddleware,
        limiter=RateLimiter(requests_per_window=rate_limit, window_seconds=60),
        enabled=True,
    )

    @app.get("/api/test")
    async def test_endpoint():
        return {"ok": True}

    @app.post("/api/nl2sql")
    async def nl2sql_endpoint():
        return {"ok": True}

    return app


def test_structured_logging_adds_request_id_to_success_response(caplog):
    client = TestClient(make_middleware_app())
    caplog.set_level("INFO")

    response = client.get("/api/test", headers={"X-Request-ID": "p2-test-id"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "p2-test-id"
    records = [json.loads(record.message) for record in caplog.records if record.message.startswith("{")]
    assert {record["event"] for record in records} >= {"request_start", "request_end"}
    assert {record["request_id"] for record in records} == {"p2-test-id"}


def test_structured_logging_covers_rejected_body_requests(caplog):
    client = TestClient(make_middleware_app())
    caplog.set_level("INFO")

    response = client.post(
        "/api/test",
        content=b"x",
        headers={"Content-Length": str(DEFAULT_MAX_REQUEST_BODY_BYTES + 1)},
    )

    assert response.status_code == 413
    assert response.headers["X-Request-ID"]
    records = [json.loads(record.message) for record in caplog.records if record.message.startswith("{")]
    ends = [record for record in records if record["event"] == "request_end"]
    assert ends and ends[-1]["status_code"] == 413


def test_column_hints_reject_unsafe_values():
    client = TestClient(make_middleware_app())

    response = client.post(
        "/api/nl2sql",
        json={"text": "query", "column_hints": ["name;DROP TABLE users"]},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == 422


def test_column_hints_allow_simple_identifiers():
    client = TestClient(make_middleware_app())

    response = client.post(
        "/api/nl2sql",
        json={"text": "query", "column_hints": ["users.id", "created_at"]},
    )

    assert response.status_code == 200


def test_single_statement_transpilation_rejects_batches():
    result = SQLTranspiler().transpile(
        "SELECT 1; SELECT 2", "mysql", "postgres"
    )

    assert result.success is False
    assert result.error_code == "VALIDATION_FAILED"
    assert "Multiple SQL statements" in result.error


def test_invalid_sql_fails_closed_before_transpile_indexing():
    result = SQLTranspiler().transpile(
        "SELECT (", "mysql", "postgres"
    )

    assert result.success is False
    assert result.error_code == "VALIDATION_FAILED"


def test_single_statement_output_is_validated():
    processor = SQLTranspiler()
    assert processor._validate_output("SELECT 1; SELECT 2", "postgres")
    assert processor._validate_output("SELECT 1", "postgres") is None


def test_scanner_does_not_rewrite_literals_or_comments():
    sql = "SELECT 'SELECT TOP 5 x', TOP FROM t -- SELECT TOP 3\n/* TOP 4 */"
    result, count = replace_outside(
        sql,
        __import__("re").compile(r"\bSELECT\s+TOP\s+\d+\b", __import__("re").IGNORECASE),
        "SELECT",
    )

    assert result == sql
    assert count == 0
    masked = mask_non_executable(sql)
    assert "SELECT TOP 5 x" not in masked


def test_top_transform_ignores_quoted_text():
    processor = PostProcessor()
    sql = "SELECT TOP 5 id FROM users WHERE note = 'SELECT TOP 9'"

    converted, notes = processor._convert_top_to_limit(sql)

    assert "LIMIT 5" in converted
    assert "SELECT TOP 9" in converted
    assert notes


def test_probe_cache_single_flight_reuses_result(monkeypatch):
    import backend.api.readiness as readiness

    readiness._cached_checks = None
    readiness._cached_at = 0.0
    calls = {"count": 0}

    def fake_checks():
        calls["count"] += 1
        return {name: {"status": "ok"} for name in ("transpiler", "functions", "types", "nl2sql")}

    monkeypatch.setattr(readiness, "_run_checks", fake_checks)

    import asyncio
    asyncio.run(_get_checks())
    asyncio.run(_get_checks())

    assert calls["count"] == 1
