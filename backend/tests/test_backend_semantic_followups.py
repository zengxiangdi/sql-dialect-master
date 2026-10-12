"""Regression tests for the v1.1.4 backend semantic hardening."""

from fastapi.testclient import TestClient

from backend.api.main import app
from backend.core.functions_lookup import FunctionEncyclopedia
from backend.core.nl2sql import NL2SQLGenerator
from backend.core.transpiler import SQLTranspiler
from backend.core.type_mapping import TypeMapper
from backend.core.config import settings


def test_nl2sql_rejects_empty_unknown_and_ddl_intent() -> None:
    generator = NL2SQLGenerator()
    for text in ("", "   ", "blahxyz", "drop users", "create users"):
        result = generator.generate(text, "postgres")
        assert result.success is False
        assert result.sql is None


def test_nl2sql_ddl_intent_ignores_quoted_values() -> None:
    generator = NL2SQLGenerator()
    for text in ("show users where name = 'drop'", "show users where name = 'create'"):
        result = generator.generate(text, "postgres")
        assert result.success is True
    for text in ("请删除用户表", "删除表 users", "创建用户表", "please drop users",
                 "I want to drop users", "please help me drop users"):
        result = generator.generate(text, "postgres")
        assert result.success is False
        assert "DDL" in result.explanation


def test_unknown_words_containing_time_keywords_fail() -> None:
    for text in ("blahday", "lastxyz", "displays", "weekdayfoo"):
        result = NL2SQLGenerator().generate(text, "postgres")
        assert result.success is False


def test_date_range_is_bounded_before_int_conversion_and_all_ranges_checked() -> None:
    generator = NL2SQLGenerator()
    result = generator.generate("find orders from last " + "9" * 4500 + " days", "postgres")
    assert result.success is False
    assert "exceeds" in result.explanation
    assert "negative" not in result.explanation
    result = generator.generate("find orders last 7 days and last 999999 years", "postgres")
    assert result.success is False
    assert "exceeds" in result.explanation


def test_nl2sql_confidence_threshold_is_used(monkeypatch) -> None:
    monkeypatch.setattr(settings, "nl2sql_confidence_threshold", 1.0)
    result = NL2SQLGenerator().generate("insert users", "postgres")
    assert result.success is False
    assert result.sql is None
    assert "threshold" in result.explanation


def test_nl2sql_parameter_metadata_is_only_for_executable_dml_markers() -> None:
    generator = NL2SQLGenerator()
    assert generator._parameter_metadata("SELECT '%s' FROM users", "mysql") == (None, [])
    assert generator._parameter_metadata("DELETE FROM users WHERE name = '%s'", "mysql") == (None, [])
    assert generator._parameter_metadata("INSERT INTO users (name) VALUES ($1)", "redshift") == ("numeric", ["$1"])
    assert generator._parameter_metadata("UPDATE users SET name = :1 WHERE id = :2", "oracle") == ("numeric", [":1", ":2"])


def test_nl2sql_does_not_extract_date_from_update() -> None:
    result = NL2SQLGenerator().generate("update user name", "postgres")
    assert result.success is True
    assert "date =" not in (result.sql or "").lower()


def test_nl2sql_rejects_absurd_date_range() -> None:
    result = NL2SQLGenerator().generate(
        "find orders from last 999999999999999999999 days", "postgres"
    )
    assert result.success is False
    assert "date interval" in result.explanation.lower()


def test_date_and_limit_accept_reasonable_leading_zeros() -> None:
    generator = NL2SQLGenerator()
    assert generator.generate("最近000007天的订单", "mysql").success
    limited = generator.generate("show users limit 0000000007", "postgres")
    assert limited.success
    assert "LIMIT 7" in limited.sql
    too_long = generator.generate("最近" + "0" * 4500 + "7天的订单", "mysql")
    assert not too_long.success


def test_transpiler_cache_results_are_isolated() -> None:
    transpiler = SQLTranspiler()
    first = transpiler.transpile("SELECT 1", "postgres", "mysql")
    first.warnings.append("caller mutation")
    second = transpiler.transpile("SELECT 1", "postgres", "mysql")
    assert "caller mutation" not in second.warnings
    assert first.warnings is not second.warnings


def test_function_search_limit_zero_is_explicit() -> None:
    assert FunctionEncyclopedia().search("date", limit=0) == []


def test_public_data_queries_do_not_expose_shared_mutable_records() -> None:
    encyclopedia = FunctionEncyclopedia()
    first = encyclopedia.search("date", limit=1)[0]
    original_name = first["name"]
    first["name"] = "mutated"
    assert encyclopedia.get_function(original_name)["name"] == original_name
    mapper = TypeMapper()
    matrix = mapper.get_matrix()
    matrix["INT"]["postgres"] = "mutated"
    assert mapper.compare_types("INT")["dialects"]["postgres"] != "mutated"


def test_type_alias_is_available_to_compare_endpoint() -> None:
    result = TypeMapper().compare_types("INTEGER")
    assert result["type"] == "INT"
    assert result["dialects"]


def test_nl2sql_api_exposes_dml_parameter_metadata() -> None:
    response = TestClient(app).post(
        "/api/nl2sql",
        json={"text": "insert users", "dialect": "postgres"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["parameter_style"] == "numeric"
    assert payload["parameters"] == ["$1", "$2"]
    assert payload["evidence"]["score"] == payload["confidence"]


def test_functions_api_rejects_unknown_category() -> None:
    response = TestClient(app).get("/api/functions?category=not-a-category")
    assert response.status_code == 400


def test_convert_accepts_trailing_comment_after_single_statement() -> None:
    response = TestClient(app).post(
        "/api/convert",
        json={
            "sql": "SELECT 1; -- trailing comment",
            "source_dialect": "postgres",
            "target_dialect": "mysql",
        },
    )
    assert response.status_code == 200
    assert response.json()["success"] is True


def test_mysql_non_comment_expression_cannot_be_dropped(monkeypatch) -> None:
    from backend.core.parser import SQLParser
    sql = "SELECT 1;\n/* c */\n--c"
    assert not SQLParser("mysql").parse(sql).success
    for security_enabled in (True, False):
        monkeypatch.setattr(settings, "security_check_enabled", security_enabled)
        assert not SQLTranspiler().transpile(sql, "mysql", "postgres").success
    assert SQLTranspiler().transpile("SELECT 1; -- comment", "mysql", "postgres").success


def test_mysql_adjacent_minus_preserves_expression_and_quoted_values() -> None:
    result = SQLTranspiler().transpile("SELECT a--b, 'a--b' AS txt FROM users", "mysql", "postgres")
    assert result.success
    assert "a - -b" in result.target_sql
    assert "'a--b'" in result.target_sql
