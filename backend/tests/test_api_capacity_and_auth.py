"""Capacity must remain bounded after callers time out; keys protect API routes."""
import asyncio
from threading import Event

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.api.main import app
from backend.api.workers import BoundedWorkerPool, WorkerCapacityError
from backend.core.config import settings


def test_timed_out_work_keeps_its_capacity_until_thread_finishes():
    async def exercise():
        pool = BoundedWorkerPool(workers=1, queue_size=0)
        gate = Event()
        started = asyncio.Event()
        loop = asyncio.get_running_loop()

        def blocked():
            loop.call_soon_threadsafe(started.set)
            gate.wait(2)

        try:
            task = asyncio.create_task(pool.run(blocked, timeout=0.02))
            await asyncio.wait_for(started.wait(), 1)
            with pytest.raises(asyncio.TimeoutError):
                await task
            with pytest.raises(WorkerCapacityError):
                await pool.run(lambda: "extra work", timeout=1)
        finally:
            gate.set()
            pool.shutdown()

    asyncio.run(exercise())


def test_worker_failure_releases_capacity():
    async def exercise():
        pool = BoundedWorkerPool(workers=1)
        def fail():
            raise ValueError("worker failed")
        try:
            with pytest.raises(ValueError, match="worker failed"):
                await pool.run(fail, timeout=1)
            assert await pool.run(lambda: "next request", timeout=1) == "next request"
        finally:
            pool.shutdown()
    asyncio.run(exercise())


def test_api_key_is_optional_for_existing_local_usage(monkeypatch):
    monkeypatch.setattr(settings, "api_key", None)
    assert TestClient(app).get("/api/dialects").status_code == 200


def test_configured_key_requires_credentials_and_preserves_error_headers(monkeypatch):
    monkeypatch.setattr(settings, "api_key", SecretStr("test-key"))
    client = TestClient(app)
    for headers in ({}, {"X-API-Key": "wrong"}, {"Authorization": "Bearer wrong"}):
        response = client.get("/api/dialects", headers=headers)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHORIZED"
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert response.headers["X-Request-ID"] == response.json()["request_id"]
    for headers in ({"X-API-Key": "test-key"}, {"Authorization": "Bearer test-key"}):
        assert client.get("/api/dialects", headers=headers).status_code == 200
    assert client.get("/health").status_code == 200


def test_api_capacity_rejection_is_a_correlated_503(monkeypatch):
    from backend.api import main
    class BusyPool:
        async def run(self, *_args, **_kwargs):
            raise WorkerCapacityError("Request processing capacity is exhausted")
    monkeypatch.setattr(settings, "api_key", None)
    monkeypatch.setattr(main, "_worker_pool", BusyPool())
    response = TestClient(app).post("/api/parse", json={"sql": "SELECT 1", "dialect": "mysql"})
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_lifespan_closes_pool_and_a_new_startup_can_serve_requests(monkeypatch):
    monkeypatch.setattr(settings, "api_key", None)
    for _ in range(2):
        with TestClient(app) as client:
            assert client.post("/api/parse", json={"sql": "SELECT 1"}).status_code == 200
            pool = app.state.worker_pool
        assert not hasattr(app.state, "worker_pool")
        async def closed_pool():
            with pytest.raises(RuntimeError, match="shutdown"):
                await pool.run(lambda: 1, timeout=1)
        asyncio.run(closed_pool())
