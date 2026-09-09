from fastapi.testclient import TestClient

from backend.api.main import app


def test_deep_health_sanitizes_internal_error_and_returns_503(monkeypatch):
    from backend.api import main

    def explode(*args, **kwargs):
        raise RuntimeError("SECRET_DATABASE_PASSWORD=leak-me")

    monkeypatch.setattr(main.transpiler, "transpile", explode)

    response = TestClient(app).get("/health/deep")
    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "❌ unhealthy"
    assert payload["checks"]["transpiler"]["message"] == "internal health check failure"
    assert "SECRET_DATABASE_PASSWORD" not in response.text
