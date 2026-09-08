import uuid

import pytest
from fastapi import Response, Request

from backend.api.middleware import StructuredLoggingMiddleware


@pytest.mark.asyncio
async def test_structured_logging_request_ids_are_unique_with_same_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("backend.api.middleware.time.time", lambda: 100.1234)

    middleware = StructuredLoggingMiddleware(app=None)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/test",
        "raw_path": b"/api/test",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "scheme": "http",
        "server": ("testserver", 80),
    }

    async def call_next(request: Request) -> Response:
        return Response("ok")

    first = await middleware.dispatch(Request(scope), call_next)
    second = await middleware.dispatch(Request(scope), call_next)

    first_id = first.headers["X-Request-ID"]
    second_id = second.headers["X-Request-ID"]

    assert first_id != second_id
    assert uuid.UUID(first_id).version == 4
    assert uuid.UUID(second_id).version == 4
