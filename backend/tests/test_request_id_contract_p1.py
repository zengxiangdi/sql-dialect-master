from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.middleware import StructuredLoggingMiddleware


def make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(StructuredLoggingMiddleware)

    @app.get("/api/test")
    async def test_endpoint():
        return {"success": True}

    return app


def test_valid_incoming_request_id_is_preserved():
    request_id = "12345678-1234-4234-8234-123456789abc"
    client = TestClient(make_app())

    response = client.get("/api/test", headers={"X-Request-ID": request_id})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request_id


def test_invalid_incoming_request_id_is_replaced():
    client = TestClient(make_app())

    response = client.get("/api/test", headers={"X-Request-ID": "not-a-uuid\nforged"})

    assert response.status_code == 200
    generated = response.headers["X-Request-ID"]
    assert generated != "not-a-uuid\nforged"
    assert len(generated) == 36
