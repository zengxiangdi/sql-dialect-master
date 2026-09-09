import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import readiness
from backend.api.middleware import RateLimitMiddleware, StructuredLoggingMiddleware
from backend.core.nl2sql import NL2SQLGenerator
from backend.core.post_processor import PostProcessor


PROBE_HEADERS = {"X-Health-Probe-Token": "test-health-token"}


def test_rownum_custom_transform_does_not_rewrite_literals_or_comments():
    processor = PostProcessor()
    for sql in (
        "SELECT 'ROWNUM <= 5' AS message",
        "SELECT 1 AS x -- ROWNUM <= 5\n",
    ):
        result, notes = processor._convert_rownum_to_limit(sql)
        assert result == sql
        assert notes == []


def test_column_hints_reject_invalid_identifier_syntax():
    generator = NL2SQLGenerator()
    result = generator.generate(
        "查询所有用户", "mysql", table_hint="users", column_hints=["name; DROP TABLE users"]
    )
    assert result.success is False
    assert "column_hints" in result.explanation


def test_column_hints_accept_dotted_identifiers():
    generator = NL2SQLGenerator()
    result = generator.generate(
        "查询所有用户", "mysql", table_hint="app.users", column_hints=["users.id", "users.name"]
    )
    assert result.success is True
    assert result.sql is not None
    assert "users.id" in result.sql
    assert "users.name" in result.sql


def test_readiness_cache_is_shared_by_deep_health(monkeypatch):
    async def exercise():
        calls = 0

        def fake_probe():
            nonlocal calls
            calls += 1
            return {
                "transpiler": {"status": "ok"},
                "functions": {"status": "ok"},
                "types": {"status": "ok"},
                "nl2sql": {"status": "ok"},
            }

        monkeypatch.setattr(readiness, "_run_checks", fake_probe)
        readiness._cached_checks = None
        readiness._cached_at = 0.0
        original_ttl = readiness._READINESS_CACHE_TTL_SECONDS
        readiness._READINESS_CACHE_TTL_SECONDS = 30.0
        try:
            first, second = await asyncio.gather(readiness._get_checks(), readiness._get_checks())
            assert first == second
            assert calls == 1
        finally:
            readiness._READINESS_CACHE_TTL_SECONDS = original_ttl

    asyncio.run(exercise())


def test_health_deep_rejects_public_requests(monkeypatch):
    monkeypatch.setenv("SDM_HEALTH_PROBE_TOKEN", "test-health-token")
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, enabled=True)

    @app.get("/health/deep")
    async def deep_health():
        return {"status": "healthy"}

    response = TestClient(app).get("/health/deep")
    assert response.status_code == 403


def test_health_deep_accepts_internal_probe_token(monkeypatch):
    monkeypatch.setenv("SDM_HEALTH_PROBE_TOKEN", "test-health-token")
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, enabled=True)

    @app.get("/health/deep")
    async def deep_health():
        return {"status": "healthy"}

    response = TestClient(app).get("/health/deep", headers=PROBE_HEADERS)
    assert response.status_code == 200


def test_nl2sql_api_rejects_invalid_column_hints():
    from backend.api.main import app

    response = TestClient(app).post(
        "/api/nl2sql",
        json={
            "text": "查询所有用户",
            "dialect": "mysql",
            "column_hints": ["name; DROP TABLE users"],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_nl2sql_api_rejects_non_identifier_column_hints():
    from backend.api.main import app

    response = TestClient(app).post(
        "/api/nl2sql",
        json={"text": "查询所有用户", "column_hints": ["count(*)"]},
    )
    assert response.status_code == 422


def test_structured_logging_is_registered_on_main_app():
    from backend.api.main import app

    assert any(middleware.cls is StructuredLoggingMiddleware for middleware in app.user_middleware)
