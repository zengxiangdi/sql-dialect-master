"""Regression coverage for the production backend fixes."""

from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.api.main import app
from backend.core.config import AppSettings
from backend.core.nl2sql import NL2SQLGenerator
from backend.core.parser import SQLParser


client = TestClient(app)


def test_parse_rejects_empty_and_multiple_statements() -> None:
    empty = client.post("/api/parse", json={"sql": "", "dialect": "postgres"})
    multi = client.post(
        "/api/parse",
        json={"sql": "SELECT 1; DROP TABLE users", "dialect": "postgres"},
    )
    assert empty.status_code == 422
    assert empty.json()["success"] is False
    assert multi.status_code == 422
    assert "Multiple SQL statements" in multi.json()["error"]["message"]


def test_parser_rejects_multiple_statements() -> None:
    result = SQLParser("postgres").parse("SELECT 1; SELECT 2")
    assert result.success is False
    assert result.error == "Multiple SQL statements are not supported"


def test_parser_accepts_a_trailing_comment_and_rejects_comment_only_sql() -> None:
    parser = SQLParser("postgres")
    assert parser.parse("SELECT 1; -- trailing comment").success is True
    assert parser.parse("-- comment only").success is False


def test_nl2sql_uses_target_dialect_bind_markers() -> None:
    assert "$1" in (NL2SQLGenerator().generate("insert users", "postgres").sql or "")
    assert "%s" in (NL2SQLGenerator().generate("insert users", "mysql").sql or "")
    assert ":1" in (NL2SQLGenerator().generate("insert users", "oracle").sql or "")
    assert "@p1" in (NL2SQLGenerator().generate("insert users", "tsql").sql or "")


def test_nl2sql_limit_zero_is_preserved() -> None:
    result = NL2SQLGenerator().generate("limit 0 orders", "postgres")
    assert result.success is True
    assert "LIMIT 0" in (result.sql or "")


def test_nl2sql_rejects_huge_limit_without_raising() -> None:
    result = NL2SQLGenerator().generate("limit 999999999999999999999999 orders", "postgres")
    assert result.success is False
    assert result.sql is None
    assert "maximum supported" in result.explanation


def test_nl2sql_target_parse_failure_is_not_success(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.core.nl2sql_pipeline.renderer.validate_sql",
        lambda *_args, **_kwargs: -0.2,
    )
    monkeypatch.setattr(
        "backend.core.nl2sql_pipeline.templates.validate_sql",
        lambda *_args, **_kwargs: -0.2,
    )
    result = NL2SQLGenerator().generate("查询所有用户", "postgres")
    assert result.success is False
    assert result.sql is None


def test_invalid_runtime_limits_are_rejected_by_settings() -> None:
    for field in ("rate_limit_requests", "rate_limit_window", "request_timeout"):
        try:
            AppSettings(**{field: 0})
        except ValidationError:
            pass
        else:
            raise AssertionError(f"{field} accepted zero")
    try:
        AppSettings(cache_ttl=-1)
    except ValidationError:
        pass
    else:
        raise AssertionError("cache_ttl accepted a negative value")
