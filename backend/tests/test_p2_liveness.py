from fastapi.testclient import TestClient

from backend.api.main import app


def test_health_is_true_liveness(monkeypatch):
    def fail_probe(*args, **kwargs):
        raise AssertionError("liveness must not invoke dependency probes")

    from backend.api import readiness
    monkeypatch.setattr(readiness, "_get_checks", fail_probe)

    response = TestClient(app).get("/health")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "alive"
    assert payload["version"]
    assert "timestamp" in payload
    assert "services" not in payload
    assert "stats" not in payload
    assert "uptime" not in payload
    assert "checks" not in payload


def test_health_liveness_survives_business_component_failure(monkeypatch):
    from backend.api import main
    monkeypatch.setattr(main.func_encyclopedia, "get_function", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("broken")))
    monkeypatch.setattr(main.type_mapper, "map_type", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("broken")))

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "alive"
