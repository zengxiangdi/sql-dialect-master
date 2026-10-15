import re
import asyncio

from starlette.requests import Request
from starlette.responses import Response
from fastapi.testclient import TestClient

from backend.api.main import API_VERSION, add_process_time_header, app


client = TestClient(app)


def test_process_time_header_is_non_negative_seconds_with_four_decimals():
    response = client.get("/health")

    assert response.status_code == 200
    process_time = response.headers["X-Process-Time"]
    assert re.fullmatch(r"\d+\.\d{4}s", process_time)
    assert float(process_time[:-1]) >= 0.0


def test_api_version_header_matches_configured_api_version():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-API-Version"] == API_VERSION


def test_process_time_uses_monotonic_clock_when_wall_clock_moves_backwards(monkeypatch):
    """A host clock correction must not produce a negative API duration."""
    wall_clock = iter((100.0, 50.0))
    monotonic_clock = iter((10.0, 10.0123))
    monkeypatch.setattr("backend.api.main.time.time", lambda: next(wall_clock))
    monkeypatch.setattr("backend.api.main.time.perf_counter", lambda: next(monotonic_clock))
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/health",
            "raw_path": b"/health",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8000),
        }
    )

    async def call_next(_request):
        return Response(status_code=200)

    response = asyncio.run(add_process_time_header(request, call_next))
    assert response.headers["X-Process-Time"] == "0.0123s"
