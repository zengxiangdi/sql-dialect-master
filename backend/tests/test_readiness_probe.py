from fastapi.testclient import TestClient

from backend.api.main import app


def test_readiness_probe_returns_dependency_status():
    response = TestClient(app).get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["probe"] == "readiness"
    assert all(check["status"] == "ok" for check in body["checks"].values())


def test_readiness_probe_is_not_rate_limited():
    client = TestClient(app)
    for _ in range(105):
        response = client.get("/ready")
        assert response.status_code == 200
