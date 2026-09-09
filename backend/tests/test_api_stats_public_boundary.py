from fastapi.testclient import TestClient

from backend.api.main import app, transpiler

client = TestClient(app)


def test_stats_exposes_only_public_aggregate_sections() -> None:
    response = client.get("/api/stats")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert set(data["stats"]) == {"overview", "functions", "types", "dialects"}
    assert set(data["stats"]["overview"]) == {
        "total_functions",
        "total_types",
        "total_dialects",
        "conversion_rules",
    }


def test_stats_does_not_expose_transpiler_runtime_internals() -> None:
    transpiler.clear_cache()
    result = transpiler.transpile("SELECT 1", "postgres", "mysql")
    assert result.success is True
    cache_stats = transpiler.get_stats()["cache"]
    assert cache_stats["misses"] == 1

    response = client.get("/api/stats")

    assert response.status_code == 200
    public_stats = response.json()["stats"]
    assert "cache" not in public_stats
    assert "security" not in public_stats
    assert "settings" not in public_stats
    assert "post_processor" not in public_stats
    assert "hits" not in public_stats
    assert "misses" not in public_stats
    assert "evictions" not in public_stats
    assert "hit_rate" not in public_stats
