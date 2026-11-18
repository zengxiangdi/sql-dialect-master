"""API field-length and body-size contract tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api.main import (
    BatchConvertRequest,
    ConvertRequest,
    DiffRequest,
    NL2SQLRequest,
    ParseRequest,
    app,
)
from backend.core.config import settings


client = TestClient(app)
REQUEST_ID = "12345678-1234-4123-8123-123456789abc"


def _assert_validation_error(response):
    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_FAILED"
    assert body["request_id"] == REQUEST_ID
    assert "timestamp" in body


def _sql_of_length(length: int) -> str:
    prefix = "SELECT 1"
    return prefix + " " * (length - len(prefix))


def test_diff_source_sql_over_limit_is_422():
    response = client.post(
        "/api/diff",
        json={
            "source_sql": "x" * (settings.parser_max_sql_length + 1),
            "target_sql": "SELECT 1",
            "source_dialect": "postgres",
            "target_dialect": "mysql",
        },
        headers={"X-Request-ID": REQUEST_ID},
    )

    _assert_validation_error(response)


def test_diff_target_sql_over_limit_is_422():
    response = client.post(
        "/api/diff",
        json={
            "source_sql": "SELECT 1",
            "target_sql": "x" * (settings.parser_max_sql_length + 1),
            "source_dialect": "postgres",
            "target_dialect": "mysql",
        },
        headers={"X-Request-ID": REQUEST_ID},
    )

    _assert_validation_error(response)


def test_convert_sql_over_limit_is_422():
    response = client.post(
        "/api/convert",
        json={
            "sql": "x" * (settings.transpiler_max_sql_length + 1),
            "source_dialect": "postgres",
            "target_dialect": "mysql",
        },
        headers={"X-Request-ID": REQUEST_ID},
    )

    _assert_validation_error(response)


def test_batch_statement_over_limit_is_422():
    response = client.post(
        "/api/convert/batch",
        json={
            "statements": ["x" * (settings.transpiler_max_sql_length + 1)],
            "source_dialect": "postgres",
            "target_dialect": "mysql",
        },
        headers={"X-Request-ID": REQUEST_ID},
    )

    _assert_validation_error(response)


def test_parse_sql_over_limit_is_422():
    response = client.post(
        "/api/parse",
        json={
            "sql": "x" * (settings.parser_max_sql_length + 1),
            "dialect": "postgres",
        },
        headers={"X-Request-ID": REQUEST_ID},
    )

    _assert_validation_error(response)


def test_nl2sql_text_over_limit_is_422():
    response = client.post(
        "/api/nl2sql",
        json={"text": "x" * (settings.nl2sql_max_input_length + 1), "dialect": "postgres"},
        headers={"X-Request-ID": REQUEST_ID},
    )

    _assert_validation_error(response)


def test_exact_field_limits_are_not_rejected_by_length_validation():
    ConvertRequest(
        sql=_sql_of_length(settings.transpiler_max_sql_length),
        source_dialect="postgres",
        target_dialect="mysql",
    )
    BatchConvertRequest(
        statements=[_sql_of_length(settings.transpiler_max_sql_length)],
        source_dialect="postgres",
        target_dialect="mysql",
    )
    ParseRequest(
        sql=_sql_of_length(settings.parser_max_sql_length),
        dialect="postgres",
    )
    DiffRequest(
        source_sql=_sql_of_length(settings.parser_max_sql_length),
        target_sql=_sql_of_length(settings.parser_max_sql_length),
        source_dialect="postgres",
        target_dialect="mysql",
    )
    NL2SQLRequest(
        text=("show users " + " " * settings.nl2sql_max_input_length)[: settings.nl2sql_max_input_length],
        dialect="postgres",
    )


def test_valid_length_syntax_error_keeps_diff_parse_error_analysis():
    response = client.post(
        "/api/diff",
        json={
            "source_sql": "SELEC FROM",
            "target_sql": "SELECT 1",
            "source_dialect": "postgres",
            "target_dialect": "mysql",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "parse_error"


def test_openapi_exposes_request_field_max_lengths():
    schema = client.get("/openapi.json").json()["components"]["schemas"]
    assert schema["ConvertRequest"]["properties"]["sql"]["maxLength"] == settings.transpiler_max_sql_length
    assert schema["BatchConvertRequest"]["properties"]["statements"]["items"]["maxLength"] == settings.transpiler_max_sql_length
    assert schema["ParseRequest"]["properties"]["sql"]["maxLength"] == settings.parser_max_sql_length
    assert schema["DiffRequest"]["properties"]["source_sql"]["maxLength"] == settings.parser_max_sql_length
    assert schema["DiffRequest"]["properties"]["target_sql"]["maxLength"] == settings.parser_max_sql_length
    assert schema["NL2SQLRequest"]["properties"]["text"]["maxLength"] == settings.nl2sql_max_input_length
