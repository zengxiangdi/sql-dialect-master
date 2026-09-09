import asyncio
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.middleware import RateLimitMiddleware, StructuredLoggingMiddleware
from backend.api import readiness
from backend.core.nl2sql import NL2SQLGenerator
from backend.core.post_processor import PostProcessor


def test_rownum_custom_transform_does_not_rewrite_literals_or_comments():
    processor = PostProcessor()
    samples = [
        "SELECT 'ROWNUM <= 5' AS message",
        "SELECT 1 AS x -- ROWNUM <= 5\n",
    ]
    for sql in samples:
        result, notes = processor._convert_rownum_to_limit(sql)
        assert result == sql
        assert notes == []


def test_column_hints_reject_invalid_identifier_syntax():
    generator = NL2SQLGenerator()
    result = generator.generate(
        "查询所有用户",
        "mysql",
        table_hint="users",
        column_hints=["name; DROP TABLE users"],
    )
    assert result.success is False
    assert "column_hints" in result.explanation


def test_column_hints_accept_dotted_identifiers():
    generator = NL2SQLGenerator()
    result = generator.generate(
        "查询所有用户",
        "mysql",
        table_hint="app.users",
        column_hints=["users.id", "users.name"],
    )
    assert result.success is True
    assert result.sql is not None
    assert "users.id" in result.sql
    assert "users.name" in result.sql


def test_health_deep_probe_cache_and_single_flight(monkeypatch):
    async def exercise():
        calls = 0

        async def fake_probe():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0)
            return {"db": {"status": "ok"}}

        monkeypatch.setattr(readiness, "_run_checks", lambda: {"db": {"status": "ok"}})
        readiness._cached_checks = None
        readiness._cached_at = 0.0
        original_ttl = readiness._READINESS_CACHE_TTL_SECONDS
        readiness._READINESS_CACHE_TTL_SECONDS = 30.0
        try:
            monkeypatch.setattr(readiness, "_run_checks", fake_probe)
            first, second = await asyncio.gather(readiness._get_checks(), readiness._get_checks())
            assert first == second
            assert calls == 1
        finally:
            readiness._READINESS_CACHE_TTL_SECONDS = original_ttl

    asyncio.run(exercise())


def test_health_deep_rejects_public_requests():
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, enabled=True)

    @app.get("/health/deep")
    async def deep_health():
        return {"status": "healthy"}

    client = TestClient(app)
    response = client.get("/health/deep")
    assert response.status_code in {401, 403}


def test_structured_logging_is_registered_on_main_app():
    from backend.api.main import app

    assert any(
        middleware.cls is StructuredLoggingMiddleware
        for middleware in app.user_middleware
    )
