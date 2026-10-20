from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from backend.api.main import app
from backend.api import main
from backend.api.workers import BoundedWorkerPool, WorkerCapacityError
from backend.core.config import AppSettings, settings
from backend.core.metadata import PROJECT_VERSION


@pytest.fixture()
def metrics_config(monkeypatch):
    monkeypatch.setattr(settings, "metrics_enabled", False)
    monkeypatch.setattr(settings, "metrics_token", None)
    yield
    monkeypatch.setattr(settings, "metrics_enabled", False)
    monkeypatch.setattr(settings, "metrics_token", None)


def test_metrics_is_disabled_by_default(metrics_config):
    response = TestClient(app).get("/metrics")
    assert response.status_code == 404


def test_enabled_metrics_require_a_token():
    with pytest.raises(ValidationError, match="metrics_token"):
        AppSettings(_env_file=None, metrics_enabled=True, metrics_token="  ")


def test_metrics_authentication_and_exposition(monkeypatch):
    monkeypatch.setattr(settings, "metrics_enabled", True)
    monkeypatch.setattr(settings, "metrics_token", SecretStr("metrics-secret"))
    client = TestClient(app)

    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"X-Metrics-Token": "wrong"}).status_code == 401

    response = client.get("/metrics", headers={"X-Metrics-Token": "metrics-secret"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain; version=1.0.0")
    assert f'sdm_build_info{{version="{PROJECT_VERSION}"}} 1' in response.text
    assert "metrics-secret" not in response.text


def test_api_key_does_not_replace_metrics_token(monkeypatch):
    monkeypatch.setattr(settings, "metrics_enabled", True)
    monkeypatch.setattr(settings, "metrics_token", SecretStr("metrics-secret"))
    monkeypatch.setattr(settings, "api_key", SecretStr("api-secret"))
    client = TestClient(app)

    assert client.get("/metrics", headers={"X-API-Key": "api-secret"}).status_code == 401
    assert client.get("/metrics", headers={"X-Metrics-Token": "metrics-secret"}).status_code == 200


def test_metrics_is_no_store_and_does_not_count_itself(monkeypatch):
    monkeypatch.setattr(settings, "metrics_enabled", True)
    monkeypatch.setattr(settings, "metrics_token", SecretStr("metrics-secret"))
    client = TestClient(app)
    first = client.get("/metrics", headers={"X-Metrics-Token": "metrics-secret"}).text
    second = client.get("/metrics", headers={"X-Metrics-Token": "metrics-secret"})
    assert second.headers["cache-control"] == "no-store"
    assert second.text.count("sdm_http_requests_total") == first.count("sdm_http_requests_total")


def test_metrics_use_route_templates_and_other_for_404(monkeypatch):
    monkeypatch.setattr(settings, "metrics_enabled", True)
    monkeypatch.setattr(settings, "metrics_token", SecretStr("metrics-secret"))
    client = TestClient(app)
    client.get("/api/functions/CONCAT")
    client.get("/metrics", headers={"X-Metrics-Token": "metrics-secret"})
    body = client.get("/metrics", headers={"X-Metrics-Token": "metrics-secret"}).text
    assert 'route="/api/functions/{name}"' in body

    client.get("/definitely-not-a-route")
    body = client.get("/metrics", headers={"X-Metrics-Token": "metrics-secret"}).text
    assert 'route="other",status_class="4xx"' in body
    assert "CONCAT" not in body


def test_worker_stats_track_rejection_and_timeout():
    import asyncio
    from threading import Event

    async def exercise():
        pool = BoundedWorkerPool(workers=1)
        gate = Event()

        def blocked():
            gate.wait(1)

        task = asyncio.create_task(pool.run(blocked, timeout=0.01))
        await asyncio.sleep(0.01)
        with pytest.raises(asyncio.TimeoutError):
            await task
        with pytest.raises(WorkerCapacityError):
            await pool.run(lambda: None, timeout=0.01)
        stats = pool.stats()
        assert stats["capacity"] == 1
        assert stats["in_use"] == 1
        assert stats["timeouts"] == 1
        assert stats["rejections"] == 1
        gate.set()
        await asyncio.sleep(0.02)
        assert pool.stats()["in_use"] == 0
        pool.shutdown()

    asyncio.run(exercise())


def test_worker_503_and_504_are_visible_without_changing_contract(monkeypatch):
    monkeypatch.setattr(settings, "metrics_enabled", True)
    monkeypatch.setattr(settings, "metrics_token", SecretStr("metrics-secret"))
    monkeypatch.setattr(settings, "api_key", None)

    class BusyPool:
        async def run(self, *_args, **_kwargs):
            raise WorkerCapacityError("busy")

    monkeypatch.setattr(main, "_worker_pool", BusyPool())
    response = TestClient(app).post("/api/parse", json={"sql": "SELECT 1", "dialect": "mysql"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"

    class SlowPool:
        async def run(self, *_args, **_kwargs):
            import asyncio
            raise asyncio.TimeoutError()

    monkeypatch.setattr(main, "_worker_pool", SlowPool())
    response = TestClient(app).post("/api/parse", json={"sql": "SELECT 1", "dialect": "mysql"})
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "REQUEST_TIMEOUT"

    body = TestClient(app).get("/metrics", headers={"X-Metrics-Token": "metrics-secret"}).text
    assert 'status_class="5xx"' in body


def test_conversion_and_runtime_metrics_are_exposed(monkeypatch):
    monkeypatch.setattr(settings, "metrics_enabled", True)
    monkeypatch.setattr(settings, "metrics_token", SecretStr("metrics-secret"))
    monkeypatch.setattr(settings, "api_key", None)
    client = TestClient(app)
    client.post(
        "/api/convert",
        json={"sql": "SELECT 1", "source_dialect": "postgres", "target_dialect": "mysql"},
    )
    body = client.get("/metrics", headers={"X-Metrics-Token": "metrics-secret"}).text
    assert 'sdm_transpile_requests_total{result="success",source="postgres",target="mysql"}' in body
    assert "sdm_transpile_cache_size" in body
    assert "sdm_api_worker_capacity" in body
    assert "SELECT 1" not in body
