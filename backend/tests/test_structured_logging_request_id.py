import asyncio
import uuid

from fastapi import Response, Request

from backend.api.middleware import StructuredLoggingMiddleware


def test_structured_logging_request_ids_are_unique_with_same_timestamp() -> None:
    from backend.api import middleware as middleware_module

    original_time = middleware_module.time.time
    middleware_module.time.time = lambda: 100.1234
    try:
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

        async def exercise() -> tuple[str, str]:
            first = await middleware.dispatch(Request(scope), call_next)
            second = await middleware.dispatch(Request(scope), call_next)
            return first.headers["X-Request-ID"], second.headers["X-Request-ID"]

        first_id, second_id = asyncio.run(exercise())
    finally:
        middleware_module.time.time = original_time

    assert first_id != second_id
    assert uuid.UUID(first_id).version == 4
    assert uuid.UUID(second_id).version == 4
