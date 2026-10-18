from fastapi.testclient import TestClient

from backend.api.main import app


client = TestClient(app)


def assert_cache(response, expected: str) -> None:
    assert response.headers["Cache-Control"] == expected


def test_sql_post_endpoints_are_no_store() -> None:
    assert_cache(
        client.post(
            "/api/convert",
            json={"sql": "SELECT 1", "source_dialect": "postgres", "target_dialect": "mysql"},
        ),
        "no-store",
    )
    assert_cache(client.post("/api/parse", json={"sql": "SELECT 1", "dialect": "postgres"}), "no-store")
    assert_cache(
        client.post(
            "/api/diff",
            json={
                "source_sql": "SELECT 1",
                "target_sql": "SELECT 1",
                "source_dialect": "postgres",
                "target_dialect": "mysql",
            },
        ),
        "no-store",
    )
    assert_cache(client.post("/api/nl2sql", json={"text": "list users", "dialect": "postgres"}), "no-store")
    assert_cache(
        client.post(
            "/api/types/map",
            json={"type_name": "VARCHAR", "source_dialect": "mysql", "target_dialect": "postgres"},
        ),
        "no-store",
    )


def test_catalog_get_endpoints_are_private_cached() -> None:
    responses = [
        client.get("/api/dialects"),
        client.get("/api/functions"),
        client.get("/api/functions/categories"),
        client.get("/api/functions/CONCAT"),
        client.get("/api/types"),
        client.get("/api/types/VARCHAR"),
    ]
    assert all(response.status_code == 200 for response in responses)
    assert all(response.headers["Cache-Control"] == "private, max-age=60" for response in responses)


def test_root_and_stats_use_short_private_cache() -> None:
    assert_cache(client.get("/"), "private, max-age=15")
    assert_cache(client.get("/api/stats"), "private, max-age=15")


def test_health_and_readiness_are_no_store_even_on_denial() -> None:
    assert_cache(client.get("/health"), "no-store")
    assert_cache(client.head("/health"), "no-store")
    ready = client.get("/ready")
    deep = client.get("/health/deep")
    assert ready.status_code == 403
    assert deep.status_code == 403
    assert_cache(ready, "no-store")
    assert_cache(deep, "no-store")


def test_options_and_docs_are_not_assigned_a_policy() -> None:
    options = client.options(
        "/api/convert",
        headers={
            "Origin": "http://localhost:8501",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "Cache-Control" not in options.headers
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert "Cache-Control" not in client.get(path).headers


def test_cache_policy_preserves_existing_header() -> None:
    from fastapi import FastAPI
    from starlette.responses import Response

    from backend.api.middleware import CacheControlMiddleware

    local_app = FastAPI()
    local_app.add_middleware(CacheControlMiddleware)

    @local_app.get("/api/stats")
    async def explicit_cache_header():
        return Response("ok", headers={"Cache-Control": "max-age=7"})

    response = TestClient(local_app).get("/api/stats")
    assert response.headers["Cache-Control"] == "max-age=7"
