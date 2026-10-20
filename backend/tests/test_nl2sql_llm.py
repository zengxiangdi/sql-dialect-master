"""Optional LLM generation is bounded, read-only, and independent of live providers."""
from __future__ import annotations

import asyncio
import json
import logging
from threading import Thread
import traceback

import httpx
import pytest
from pydantic import SecretStr, ValidationError
from sqlglot import exp

from backend.core.config import AppSettings
from backend.core import nl2sql_llm
from backend.core.nl2sql_llm import LLMError, LLMGeneration, LLMN2SQLClient, validate_llm_sql


PRIVATE_KEY = "private-llm-api-key-for-tests"


def configured(**overrides):
    values = {
        "_env_file": None,
        "nl2sql_llm_enabled": True,
        "nl2sql_llm_api_key": PRIVATE_KEY,
        "nl2sql_llm_model": "provider/test-model",
    }
    values.update(overrides)
    return AppSettings(**values)


def completion(content="SELECT id FROM users", **extra):
    return {"choices": [{"message": {"content": content}}], **extra}


def generate_with(handler, **settings_overrides):
    client = LLMN2SQLClient(configured(**settings_overrides), httpx.MockTransport(handler))
    return asyncio.run(client.generate("Find users", "postgres", "users", ["users.id"]))


def test_settings_defaults_disable_external_generation():
    values = AppSettings(_env_file=None)
    assert values.nl2sql_llm_enabled is False
    assert values.nl2sql_llm_base_url == "https://openrouter.ai/api/v1"
    assert values.nl2sql_llm_api_key is None
    assert values.nl2sql_llm_model == ""
    assert values.nl2sql_llm_timeout == 15
    assert values.nl2sql_llm_max_tokens == 800
    assert values.nl2sql_llm_temperature == 0
    assert values.nl2sql_llm_fallback is True
    assert values.nl2sql_llm_app_name == "SQL Dialect Master"
    assert values.nl2sql_llm_app_url == ""


@pytest.mark.parametrize("key", [None, "", "  "])
def test_enabled_settings_require_a_nonblank_key(key):
    with pytest.raises(ValidationError, match="nl2sql_llm_api_key"):
        configured(nl2sql_llm_api_key=key)


@pytest.mark.parametrize("model", ["", " \t "])
def test_enabled_settings_require_a_nonblank_model_without_leaking_key(model):
    with pytest.raises(ValidationError, match="nl2sql_llm_model") as caught:
        configured(nl2sql_llm_model=model)
    assert PRIVATE_KEY not in str(caught.value)
    assert PRIVATE_KEY not in repr(caught.value)


@pytest.mark.parametrize("field,value", [
    ("nl2sql_llm_timeout", 0), ("nl2sql_llm_timeout", 61),
    ("nl2sql_llm_max_tokens", 0), ("nl2sql_llm_max_tokens", 8193),
    ("nl2sql_llm_temperature", -0.1), ("nl2sql_llm_temperature", 2.1),
])
def test_numeric_settings_have_bounds(field, value):
    with pytest.raises(ValidationError):
        configured(**{field: value})


def test_settings_accept_numeric_boundaries_and_mask_secrets():
    values = configured(nl2sql_llm_timeout=60, nl2sql_llm_max_tokens=8192, nl2sql_llm_temperature=2)
    assert isinstance(values.nl2sql_llm_api_key, SecretStr)
    assert PRIVATE_KEY not in str(values)
    assert PRIVATE_KEY not in repr(values)
    assert PRIVATE_KEY not in values.model_dump_json()
    assert PRIVATE_KEY not in repr(values.to_dict())


@pytest.mark.parametrize("url", [
    "", "ftp://provider.example", "https://", "//provider.example",
    "https://[broken", "https://provider.example:bad", "https://provider.example:70000",
    "https://provider. example", "https://provider.example/\x00path",
    f"https://user:{PRIVATE_KEY}@provider.example",
    f"https://provider.example?key={PRIVATE_KEY}",
    f"https://provider.example#{PRIVATE_KEY}",
])
def test_invalid_urls_raise_static_errors_without_secrets(url):
    with pytest.raises(ValidationError) as caught:
        configured(nl2sql_llm_base_url=url)
    assert PRIVATE_KEY not in str(caught.value)
    assert PRIVATE_KEY not in repr(caught.value)


def test_urls_are_normalized_and_optional_app_url_is_validated():
    values = configured(
        nl2sql_llm_base_url=" http://127.0.0.1:8000/api/v1/// ",
        nl2sql_llm_app_url="https://application.example/",
    )
    assert values.nl2sql_llm_base_url == "http://127.0.0.1:8000/api/v1"
    assert values.nl2sql_llm_app_url == "https://application.example"
    assert configured(nl2sql_llm_app_url="  ").nl2sql_llm_app_url == ""
    with pytest.raises(ValidationError):
        configured(nl2sql_llm_app_url="not-a-url")


def test_success_posts_expected_headers_options_and_messages():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=completion(model="untrusted/provider-model"))

    result = generate_with(
        handler, nl2sql_llm_base_url="https://provider.example/api/v1/",
        nl2sql_llm_app_name="Test app", nl2sql_llm_app_url="https://application.example/",
        nl2sql_llm_timeout=7, nl2sql_llm_temperature=0.3, nl2sql_llm_max_tokens=123,
    )
    assert result == LLMGeneration("SELECT id FROM users", "provider/test-model")
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://provider.example/api/v1/chat/completions"
    assert request.headers["Authorization"] == f"Bearer {PRIVATE_KEY}"
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["X-Title"] == "Test app"
    assert request.headers["HTTP-Referer"] == "https://application.example"
    assert request.extensions["timeout"] == {"connect": 7, "read": 7, "write": 7, "pool": 7}
    payload = json.loads(request.content)
    assert payload["model"] == "provider/test-model"
    assert payload["temperature"] == 0.3
    assert payload["max_tokens"] == 123
    assert [message["role"] for message in payload["messages"]] == ["system", "user"]
    system = payload["messages"][0]["content"]
    assert "SELECT or UNION" in system
    assert "postgres" in system
    assert "UNSAFE" in system
    assert "no Markdown, explanations, or comments" in system
    assert "If hints are absent" in system
    assert "infer reasonable table and column names" in system
    assert "provided, use them" in system
    assert "strongly implied" in system
    assert "do not invent unrelated tables" in system
    assert "cannot be satisfied safely" in system
    assert json.loads(payload["messages"][1]["content"]) == {
        "dialect": "postgres", "table_hint": "users", "column_hints": ["users.id"], "text": "Find users",
    }
    assert PRIVATE_KEY not in request.content.decode()
    assert PRIVATE_KEY not in repr(result)


def test_optional_headers_and_hints_are_not_invented():
    def handler(request):
        assert "HTTP-Referer" not in request.headers
        payload = json.loads(request.content)
        system = payload["messages"][0]["content"]
        assert "SELECT or UNION" in system
        assert "no Markdown, explanations, or comments" in system
        assert "Do not generate data modifications, DDL, SELECT INTO, or locking queries" in system
        assert "If hints are absent" in system
        assert "infer reasonable table and column names" in system
        assert "provided, use them" in system
        assert "strongly implied" in system
        assert "do not invent unrelated tables" in system
        assert "return exactly UNSAFE" in system
        user = json.loads(payload["messages"][1]["content"])
        assert user == {"dialect": "mysql", "table_hint": "", "column_hints": [], "text": "查询"}
        return httpx.Response(200, json=completion("SELECT 1"))

    client = LLMN2SQLClient(configured(), httpx.MockTransport(handler))
    assert asyncio.run(client.generate("查询", "mysql")).sql == "SELECT 1"


@pytest.mark.parametrize("content", ["UNSAFE", "SELECT id FROM users"])
def test_no_hint_response_still_requires_explicit_sql_validation(content):
    requests = []

    def handler(request):
        requests.append(request)
        payload = json.loads(request.content)
        assert json.loads(payload["messages"][1]["content"]) == {
            "dialect": "postgres", "table_hint": "", "column_hints": [], "text": "Find user ids",
        }
        return httpx.Response(200, json=completion(content))

    client = LLMN2SQLClient(configured(), httpx.MockTransport(handler))
    result = asyncio.run(client.generate("Find user ids", "postgres"))
    assert len(requests) == 1
    assert result.sql == content
    assert result.model == "provider/test-model"
    if content == "UNSAFE":
        with pytest.raises(LLMError, match="invalid_sql"):
            validate_llm_sql(result.sql, "postgres")
    else:
        assert validate_llm_sql(result.sql, "postgres") == content


def test_schema_is_added_to_prompt_only_when_provided():
    schema = {
        "tables": [
            {"name": "users", "columns": [{"name": "id", "type": "INTEGER"}]},
            {"name": "orders", "columns": [{"name": "user_id"}]},
        ],
        "relationships": [{
            "from_table": "orders", "from_column": "user_id",
            "to_table": "users", "to_column": "id",
        }],
    }
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=completion())

    client = LLMN2SQLClient(configured(), httpx.MockTransport(handler))
    asyncio.run(client.generate("Find users", "postgres", schema=schema))
    asyncio.run(client.generate("Find users", "postgres"))
    schema_payload, default_payload = requests
    assert json.loads(schema_payload["messages"][1]["content"]) == {
        "dialect": "postgres", "table_hint": "", "column_hints": [], "text": "Find users",
        "schema": schema,
    }
    assert (
        schema_payload["messages"][0]["content"]
        == default_payload["messages"][0]["content"]
        + " Prefer the provided schema. Do not reference tables or columns outside the schema."
    )
    assert "schema" not in json.loads(default_payload["messages"][1]["content"])
    assert "provided schema" not in default_payload["messages"][0]["content"]


SCHEMA = {
    "tables": [
        {"name": "users", "columns": [{"name": "id"}, {"name": "name"}]},
        {"name": "orders", "columns": [{"name": "user_id"}, {"name": "amount"}]},
        {"name": "events", "columns": []},
        {"name": "public.accounts", "columns": [{"name": "id"}]},
    ],
    "relationships": [],
}


@pytest.mark.parametrize("sql", [
    "SELECT id FROM users",
    "SELECT U.ID FROM USERS U",
    "SELECT u.id, o.amount FROM users u JOIN orders o ON u.id = o.user_id",
    "SELECT * FROM users",
    "SELECT u.* FROM users u",
    "SELECT arbitrary_column FROM events",
    "SELECT e.arbitrary_column FROM events e",
    "SELECT public.accounts.id FROM public.accounts",
    'SELECT "public"."accounts"."id" FROM "public"."accounts"',
    "SELECT a.id FROM public.accounts a",
    "SELECT id FROM users UNION ALL SELECT user_id FROM orders",
    "SELECT u.id FROM users u WHERE EXISTS (SELECT 1 FROM orders o WHERE o.user_id = u.id)",
    "SELECT u.id FROM users u WHERE EXISTS (SELECT u.amount FROM orders u)",
    "WITH chosen AS (SELECT id FROM users) SELECT chosen.id FROM chosen",
    "WITH chosen AS (SELECT * FROM users) SELECT chosen.name FROM chosen",
    "WITH chosen AS (SELECT * FROM users) SELECT chosen.id, chosen.name FROM chosen",
    "SELECT d.identifier FROM (SELECT id AS identifier FROM users) d",
    "SELECT d.id FROM (SELECT u.* FROM users u) d",
    "SELECT d.arbitrary_column FROM (SELECT * FROM events) d",
    "SELECT d.renamed FROM (SELECT id FROM users) d(renamed)",
    "SELECT d.id FROM (SELECT id FROM users UNION ALL SELECT user_id FROM orders) d",
])
def test_schema_validation_accepts_known_sources_and_scope_aliases(sql):
    # An unrestricted table permits arbitrary *qualified* columns. Unqualified
    # names follow the complete schema's explicit column set when one exists.
    schema = SCHEMA if sql != "SELECT arbitrary_column FROM events" else {
        "tables": [{"name": "events", "columns": []}],
    }
    assert validate_llm_sql(sql, "postgres", schema=schema) == sql


@pytest.mark.parametrize("sql", [
    "SELECT * FROM hidden_table",
    "SELECT id FROM users JOIN hidden_table h ON users.id = h.id",
    "SELECT users.secret FROM users",
    "SELECT secret FROM users",
    "SELECT missing.id FROM users",
    "SELECT missing.* FROM users",
    "SELECT u.secret FROM users u",
    "SELECT users.id FROM users u",
    "SELECT id FROM private.users",
    'SELECT id FROM "public.accounts"',
    "SELECT id FROM accounts",
    "SELECT private.accounts.id FROM public.accounts",
    'SELECT "public.accounts".id FROM public.accounts',
    'SELECT "public.accounts".* FROM public.accounts',
    "SELECT public.accounts.secret FROM public.accounts",
    "SELECT u.id FROM users u WHERE EXISTS (SELECT u.id FROM orders u)",
    "SELECT u.id FROM users u WHERE EXISTS (SELECT 1 FROM orders o WHERE u.secret = o.user_id)",
    "SELECT u.id FROM users u JOIN orders U ON u.id = U.user_id",
    "WITH chosen AS (SELECT id FROM hidden_table) SELECT chosen.id FROM chosen",
    "WITH chosen AS (SELECT id FROM users) SELECT chosen.secret FROM chosen",
    "SELECT d.secret FROM (SELECT * FROM users) d",
    "SELECT d.id FROM (SELECT id AS identifier FROM users) d",
    "SELECT id FROM users UNION ALL SELECT secret FROM orders",
    "SELECT id FROM users UNION ALL SELECT id FROM unknown",
    "SELECT u.id FROM users u SEMI JOIN unknown x ON u.id = x.id",
    "SELECT u.id FROM users u ANTI JOIN unknown x ON u.id = x.id",
    "WITH RECURSIVE x AS (SELECT * FROM x) SELECT x.id FROM x",
    "SELECT 1 FROM users WHERE EXISTS (SELECT unknown.id)",
    "SELECT * FROM users WHERE EXISTS (SELECT 1 FROM users u WHERE unknown.id = u.id)",
])
def test_schema_validation_rejects_unknown_tables_columns_and_aliases(sql):
    with pytest.raises(LLMError, match="invalid_sql"):
        validate_llm_sql(sql, "postgres", schema=SCHEMA)


def test_schema_without_column_information_leaves_column_names_unrestricted():
    schema = {"tables": [{"name": "users", "columns": []}]}
    sql = "SELECT unknown, u.anything, u.* FROM users u"
    assert validate_llm_sql(sql, "postgres", schema=schema) == sql
    with pytest.raises(LLMError, match="invalid_sql"):
        validate_llm_sql("SELECT unknown.id FROM users", "postgres", schema=schema)


def test_unqualified_columns_can_match_any_provided_table_column():
    sql = "SELECT amount FROM users"
    assert validate_llm_sql(sql, "postgres", schema=SCHEMA) == sql


def test_empty_schema_disallows_physical_tables_but_preserves_select_literals():
    assert validate_llm_sql("SELECT 1", "postgres", schema={}) == "SELECT 1"
    with pytest.raises(LLMError, match="invalid_sql"):
        validate_llm_sql("SELECT * FROM users", "postgres", schema={})


def test_schema_validation_preserves_original_sql_and_positional_settings_argument():
    sql = "SELECT u.id  FROM users u;"
    assert validate_llm_sql(sql, "postgres", configured(), schema=SCHEMA) == sql
    assert validate_llm_sql("SELECT hidden FROM unknown", "postgres", configured()) == "SELECT hidden FROM unknown"


def test_schema_failure_does_not_expose_schema_or_sql_in_logs_or_exceptions(caplog):
    schema = {"tables": [{"name": "sensitive_schema_table", "columns": [{"name": "private_column"}]}]}
    sql = "SELECT provider_private_sql FROM unrelated_table"
    with pytest.raises(LLMError, match="invalid_sql") as caught:
        validate_llm_sql(sql, "postgres", schema=schema)
    for private_text in ("sensitive_schema_table", "private_column", "provider_private_sql", "unrelated_table"):
        assert private_text not in caplog.text
        assert private_text not in "".join(traceback.format_exception(caught.value))


def test_schema_scope_diagnostics_and_unexpected_errors_are_sanitized(monkeypatch, caplog):
    sensitive_detail = "private-schema-and-sql-diagnostic"
    logger = logging.getLogger("sqlglot")
    previous_filters = list(logger.filters)

    def fail_scope_analysis(_statement):
        logger.warning(sensitive_detail)
        raise ValueError(sensitive_detail)

    monkeypatch.setattr(nl2sql_llm, "traverse_scope", fail_scope_analysis)
    with caplog.at_level(logging.WARNING, logger="sqlglot"):
        with pytest.raises(LLMError, match="invalid_sql") as caught:
            validate_llm_sql("SELECT id FROM users", "postgres", schema=SCHEMA)
        logger.warning("normal scope diagnostics remain enabled")
    assert sensitive_detail not in caplog.text
    assert sensitive_detail not in "".join(traceback.format_exception(caught.value))
    assert "normal scope diagnostics remain enabled" in caplog.text
    assert logger.filters == previous_filters


@pytest.mark.parametrize("enabled,missing_field", [(False, None), (True, "nl2sql_llm_api_key"), (True, "nl2sql_llm_model")])
def test_disabled_or_mutated_unconfigured_client_never_makes_a_request(enabled, missing_field):
    values = configured(nl2sql_llm_enabled=enabled)
    if missing_field:
        setattr(values, missing_field, None if missing_field.endswith("api_key") else " ")

    def unexpected(_request):
        pytest.fail("disabled client must not make HTTP requests")

    with pytest.raises(LLMError, match="disabled"):
        asyncio.run(LLMN2SQLClient(values, httpx.MockTransport(unexpected)).generate("query", "postgres"))


@pytest.mark.parametrize("exception,reason", [
    (httpx.ReadTimeout, "timeout"), (httpx.ConnectTimeout, "timeout"),
    (httpx.ConnectError, "http_error"), (httpx.RemoteProtocolError, "http_error"),
])
def test_network_failures_have_fixed_safe_reasons(exception, reason, caplog):
    def handler(_request):
        raise exception(f"private response detail {PRIVATE_KEY}")

    with pytest.raises(LLMError) as caught:
        generate_with(handler)
    assert caught.value.reason == reason
    assert str(caught.value) == reason
    assert PRIVATE_KEY not in "".join(traceback.format_exception(caught.value))
    assert PRIVATE_KEY not in caplog.text


@pytest.mark.parametrize("field", ["nl2sql_llm_api_key", "nl2sql_llm_app_name"])
def test_invalid_header_encoding_is_sanitized_before_transport(caplog, field):
    def unexpected(_request):
        pytest.fail("invalid HTTP headers must not reach transport")

    with pytest.raises(LLMError, match="http_error") as caught:
        generate_with(unexpected, **{field: PRIVATE_KEY + "中文"})
    assert PRIVATE_KEY not in str(caught.value)
    assert PRIVATE_KEY not in repr(caught.value)
    assert PRIVATE_KEY not in "".join(traceback.format_exception(caught.value))
    assert PRIVATE_KEY not in caplog.text


@pytest.mark.parametrize("status,reason", [
    (301, "http_error"), (400, "http_error"), (401, "http_error"),
    (429, "http_429"), (500, "http_5xx"), (503, "http_5xx"), (600, "http_error"),
])
def test_unsuccessful_http_responses_never_expose_provider_body(status, reason, caplog):
    def handler(_request):
        return httpx.Response(status, text=f"provider says {PRIVATE_KEY}", headers={"Location": "https://elsewhere.example"})

    with pytest.raises(LLMError) as caught:
        generate_with(handler)
    assert caught.value.reason == reason
    assert PRIVATE_KEY not in repr(caught.value)
    assert PRIVATE_KEY not in caplog.text


@pytest.mark.parametrize("body", [
    None, [], {}, {"choices": None}, {"choices": {}}, {"choices": []},
    {"choices": [None]}, {"choices": [{}]}, {"choices": [{"message": None}]},
    {"choices": [{"message": {}}]}, completion([]), completion({"text": "SELECT 1"}), completion(123),
])
def test_malformed_response_shapes_are_rejected(body):
    with pytest.raises(LLMError, match="invalid_response"):
        generate_with(lambda _request: httpx.Response(200, json=body))


def test_non_json_response_is_rejected_without_body_leaks():
    with pytest.raises(LLMError, match="invalid_response") as caught:
        generate_with(lambda _request: httpx.Response(200, text=PRIVATE_KEY))
    assert PRIVATE_KEY not in repr(caught.value)


@pytest.mark.parametrize("content", [None, "", " \n\t "])
def test_empty_content_has_distinct_fixed_reason(content):
    with pytest.raises(LLMError, match="empty_content"):
        generate_with(lambda _request: httpx.Response(200, json=completion(content)))


def test_response_cannot_echo_the_key_in_generated_sql_or_model():
    with pytest.raises(LLMError, match="invalid_response"):
        generate_with(lambda _request: httpx.Response(200, json=completion(f"SELECT '{PRIVATE_KEY}'")))
    with pytest.raises(LLMError, match="invalid_response"):
        generate_with(
            lambda _request: httpx.Response(200, json=completion()), nl2sql_llm_model=PRIVATE_KEY,
        )


@pytest.mark.parametrize("sql", [
    "SELECT id FROM users", "SELECT 1 UNION ALL SELECT 2",
    "WITH chosen AS (SELECT id FROM users) SELECT id FROM chosen",
    "SELECT 'a;b' AS message",
])
def test_sql_validation_accepts_select_union_and_select_cte(sql):
    assert validate_llm_sql(sql, "postgres") == sql


@pytest.mark.parametrize("content", [
    "```sql\nSELECT id FROM users\n```",
    "  ```SQL\nSELECT id FROM users\n```  ",
    "```\nSELECT id FROM users\n```",
])
def test_fences_are_preserved_until_mandatory_sql_validation(content):
    result = generate_with(lambda _request: httpx.Response(200, json=completion(content)))
    assert result.sql == content
    assert validate_llm_sql(result.sql, "postgres") == "SELECT id FROM users"


@pytest.mark.parametrize("sql", [
    None, "", "  ", "UNSAFE", " unsafe ", "SELECT (", "SELECT 1; SELECT 2",
    "DELETE FROM users", "UPDATE users SET id = 2", "INSERT INTO users VALUES (1)",
    "CREATE TABLE copied AS SELECT * FROM users", "DROP TABLE users",
    "SELECT id INTO copied FROM users",
    "WITH removed AS (DELETE FROM users RETURNING id) SELECT id FROM removed",
    "SELECT id FROM users FOR UPDATE",
    "SELECT 1 INTERSECT SELECT 1", "(SELECT 1)",
    "```sql\nSELECT 1\n```\nexplanation", "```sql\n\n```",
])
def test_non_readonly_multi_statement_or_invalid_output_is_rejected(sql):
    with pytest.raises(LLMError, match="invalid_sql"):
        validate_llm_sql(sql, "postgres")


def test_sql_length_limit_is_checked_before_parsing():
    with pytest.raises(LLMError, match="invalid_sql"):
        validate_llm_sql("SELECT '" + "x" * 50 + "'", "postgres", configured(transpiler_max_sql_length=20))


def test_unknown_error_reason_is_sanitized():
    error = LLMError(PRIVATE_KEY)
    assert error.reason == "invalid_response"
    assert PRIVATE_KEY not in str(error)
    assert PRIVATE_KEY not in repr(error)


def test_unsupported_command_diagnostics_do_not_echo_generated_content(caplog):
    logger = logging.getLogger("sqlglot")
    previous_filters = list(logger.filters)
    with caplog.at_level(logging.WARNING, logger="sqlglot"):
        with pytest.raises(LLMError, match="invalid_sql"):
            validate_llm_sql(f"CREATE MAGIC {PRIVATE_KEY}", "postgres")
        logger.warning("normal deterministic diagnostics remain enabled")
    assert PRIVATE_KEY not in caplog.text
    assert "normal deterministic diagnostics remain enabled" in caplog.text
    assert logger.filters == previous_filters


def test_sql_diagnostic_suppression_is_local_to_validation_context(monkeypatch, caplog):
    logger = logging.getLogger("sqlglot")

    def parse_with_diagnostics(_sql, _dialect):
        logger.warning(PRIVATE_KEY)
        thread = Thread(target=lambda: logger.warning("unrelated thread diagnostic"))
        thread.start()
        thread.join(timeout=2)
        assert not thread.is_alive()
        return exp.Select(expressions=[exp.Literal.number(1)])

    monkeypatch.setattr(nl2sql_llm, "parse_single_sql", parse_with_diagnostics)
    with caplog.at_level(logging.WARNING, logger="sqlglot"):
        assert validate_llm_sql("SELECT 1", "postgres") == "SELECT 1"
    assert PRIVATE_KEY not in caplog.text
    assert "unrelated thread diagnostic" in caplog.text
