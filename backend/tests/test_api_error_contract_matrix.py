"""Focused regression coverage for the middleware error-code matrix."""

import asyncio
import json

import pytest
from starlette.responses import JSONResponse, Response, StreamingResponse
from fastapi import HTTPException

from backend.api.middleware import StructuredLoggingMiddleware
from backend.api.main import custom_http_exception_handler


REQUEST_ID = "12345678-1234-4123-8123-123456789abc"


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (400, "BAD_REQUEST"),
        (404, "NOT_FOUND"),
        (405, "METHOD_NOT_ALLOWED"),
        (413, "PAYLOAD_TOO_LARGE"),
        (422, "VALIDATION_FAILED"),
        (429, "RATE_LIMITED"),
    ],
)
def test_error_status_matrix_has_stable_code(status_code, expected_code):
    response = JSONResponse(
        status_code=status_code,
        content={"detail": "request rejected"},
    )

    normalized = asyncio.run(
        StructuredLoggingMiddleware._normalize_error_response(response, REQUEST_ID)
    )

    assert normalized.status_code == status_code
    data = json.loads(normalized.body)
    assert data["success"] is False
    assert data["error"]["code"] == expected_code
    assert data["request_id"] == REQUEST_ID
    assert "timestamp" in data


def test_domain_error_code_is_preserved_across_4xx_normalization():
    response = JSONResponse(
        status_code=400,
        content={
            "success": False,
            "error": {
                "code": "TRANSPILE_FAILED",
                "message": "transpiler rejected statement",
                "details": {},
            },
        },
    )

    normalized = asyncio.run(
        StructuredLoggingMiddleware._normalize_error_response(response, REQUEST_ID)
    )

    assert json.loads(normalized.body)["error"]["code"] == "TRANSPILE_FAILED"


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [(503, "SERVICE_UNAVAILABLE"), (504, "REQUEST_TIMEOUT")],
)
def test_http_exception_handler_uses_string_codes_for_5xx(status_code, expected_code):
    response = asyncio.run(
        custom_http_exception_handler(
            None, HTTPException(status_code=status_code, detail="temporary failure")
        )
    )

    assert json.loads(response.body)["error"]["code"] == expected_code


def test_non_json_response_is_left_unchanged():
    response = Response(content="plain text", status_code=400)

    normalized = asyncio.run(
        StructuredLoggingMiddleware._normalize_error_response(response, REQUEST_ID)
    )

    assert normalized is response
    assert normalized.body.decode() == "plain text"


def test_malformed_streaming_json_keeps_response_body():
    async def body():
        yield b"not-json"

    response = StreamingResponse(body(), status_code=400, media_type="application/json")

    normalized = asyncio.run(
        StructuredLoggingMiddleware._normalize_error_response(response, REQUEST_ID)
    )

    assert normalized.status_code == 400
    assert normalized.body == b"not-json"
