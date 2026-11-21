"""API field-length and body-size contract tests."""

from __future__ import annotations

from typing import cast

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
TRANSPILER_MAX = cast(int, settings.transpiler_max_sql_length)
PARSER_MAX = cast(int, settings.parser_max_sql_length or TRANSPILER_MAX)
NL2SQL_MAX = cast(int, settings.nl2sql_max_input_length)


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
            "source_sql": "x" * (PARSER_MAX + 1),
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
            "target_sql": "x" * (PARSER_MAX + 1),
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
            "sql": "x" * (TRANSPILER_MAX + 1),
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
            "statements": ["x" * (TRANSPILER_MAX + 1)],
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
            "sql": "x" * (PARSER_MAX + 1),
            "dialect": "postgres",
        },
        headers={"X-Request-ID": REQUEST_ID},
    )

    _assert_validation_error(response)


def test_nl2sql_text_over_limit_is_422():
    response = client.post(
        "/api/nl2sql",
        json={"text": "x" * (NL2SQL_MAX + 1), "dialect": "postgres"},
        headers={"X-Request-ID": REQUEST_ID},
    )

    _assert_validation_error(response)


def test_exact_field_limits_are_not_rejected_by_length_validation():
    ConvertRequest(
        sql=_sql_of_length(TRANSPILER_MAX),
        source_dialect="postgres",
        target_dialect="mysql",
        pretty=True,
    )
    BatchConvertRequest(
        statements=[_sql_of_length(TRANSPILER_MAX)],
        source_dialect="postgres",
        target_dialect="mysql",
    )
    ParseRequest(
        sql=_sql_of_length(PARSER_MAX),
        dialect="postgres",
    )
    DiffRequest(
        source_sql=_sql_of_length(PARSER_MAX),
        target_sql=_sql_of_length(PARSER_MAX),
        source_dialect="postgres",
        target_dialect="mysql",
    )
    NL2SQLRequest(
        text=("show users " + " " * NL2SQL_MAX)[:NL2SQL_MAX],
        dialect="postgres",
        table_hint=None,
        column_hints=None,
        schema=None,
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
    assert schema["ConvertRequest"]["properties"]["sql"]["maxLength"] == TRANSPILER_MAX
    assert schema["BatchConvertRequest"]["properties"]["statements"]["items"]["maxLength"] == TRANSPILER_MAX
    assert schema["ParseRequest"]["properties"]["sql"]["maxLength"] == PARSER_MAX
    assert schema["DiffRequest"]["properties"]["source_sql"]["maxLength"] == PARSER_MAX
    assert schema["DiffRequest"]["properties"]["target_sql"]["maxLength"] == PARSER_MAX
    assert schema["NL2SQLRequest"]["properties"]["text"]["maxLength"] == NL2SQL_MAX
