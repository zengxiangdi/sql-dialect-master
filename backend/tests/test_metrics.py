from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from backend.api.main import app
from backend.core.config import AppSettings, settings


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
    assert re.search(r"sdm_build_info\{version=\"1\.1\.7\"\} 1", response.text)
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
