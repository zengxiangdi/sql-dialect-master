from fastapi.testclient import TestClient

from backend.api.main import app


def test_deep_health_sanitizes_internal_error_and_returns_503(monkeypatch):
    from backend.api import main, readiness

    def explode(*args, **kwargs):
        raise RuntimeError("SECRET_DATABASE_PASSWORD=leak-me")

    monkeypatch.setenv("SDM_HEALTH_PROBE_TOKEN", "test-health-token")
    monkeypatch.setattr(main.transpiler, "transpile", explode)
    readiness._cached_checks = None
    readiness._cached_at = 0.0

    response = TestClient(app).get(
        "/health/deep",
        headers={"X-Health-Probe-Token": "test-health-token"},
    )
    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "❌ unhealthy"
    transpiler_check = payload["checks"]["transpiler"]
    assert (
        transpiler_check.get("message") == "internal health check failure"
        or transpiler_check.get("code") == "probe_failed"
    )
    assert "SECRET_DATABASE_PASSWORD" not in response.text


def test_deep_health_denies_public_request(monkeypatch):
    monkeypatch.setenv("SDM_HEALTH_PROBE_TOKEN", "test-health-token")
    response = TestClient(app).get("/health/deep")
    assert response.status_code == 403
