from fastapi.testclient import TestClient

from backend.api.main import app

PROBE_HEADERS = {"X-Health-Probe-Token": "test-health-token"}


def test_readiness_probe_returns_dependency_status(monkeypatch):
    monkeypatch.setenv("SDM_HEALTH_PROBE_TOKEN", "test-health-token")
    response = TestClient(app).get("/ready", headers=PROBE_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["probe"] == "readiness"
    assert all(check["status"] == "ok" for check in body["checks"].values())


def test_readiness_probe_is_not_rate_limited(monkeypatch):
    monkeypatch.setenv("SDM_HEALTH_PROBE_TOKEN", "test-health-token")
    client = TestClient(app)
    for _ in range(105):
        response = client.get("/ready", headers=PROBE_HEADERS)
        assert response.status_code == 200
