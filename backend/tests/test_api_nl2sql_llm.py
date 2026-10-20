"""Optional API LLM routing preserves deterministic and HTTP error contracts."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.api import main, readiness
from backend.api.metrics import REGISTRY
from backend.api.middleware import DEFAULT_MAX_REQUEST_BODY_BYTES
from backend.api.workers import WorkerCapacityError
from backend.core.config import settings
from backend.core.nl2sql_llm import LLMError, LLMGeneration, LLMN2SQLClient


MODEL = "test-provider/test-model"
API_KEY = "test-openrouter-secret-never-expose"
SQL = "SELECT id FROM users LIMIT 2"
RESULTS = (
    "success", "timeout", "http_429", "http_5xx", "http_error",
    "invalid_response", "empty_content", "invalid_sql", "disabled",
)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "api_key", None)
    monkeypatch.setattr(settings, "nl2sql_llm_enabled", True)
    monkeypatch.setattr(settings, "nl2sql_llm_api_key", SecretStr(API_KEY))
    monkeypatch.setattr(settings, "nl2sql_llm_model", MODEL)
    monkeypatch.setattr(settings, "nl2sql_llm_base_url", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(settings, "nl2sql_llm_fallback", True)
    with TestClient(main.app) as test_client:
        yield test_client


def payload(**changes):
    request = {"text": "show users", "dialect": "postgres"}
    request.update(changes)
    return request


def stub_llm(monkeypatch, *, sql=SQL, reason=None):
    generate = AsyncMock(
        return_value=LLMGeneration(sql=sql, model=MODEL),
        side_effect=LLMError(reason) if reason else None,
    )
    factory = Mock(return_value=SimpleNamespace(generate=generate))
    monkeypatch.setattr(main, "LLMN2SQLClient", factory)
    return factory, generate


def metric_snapshot():
    snapshot = {
        result: REGISTRY.get_sample_value("sdm_nl2sql_llm_requests_total", {"result": result}) or 0
        for result in RESULTS
    }
    snapshot["duration"] = REGISTRY.get_sample_value("sdm_nl2sql_llm_duration_seconds_count") or 0
    snapshot["fallbacks"] = REGISTRY.get_sample_value("sdm_nl2sql_llm_fallbacks_total") or 0
    return snapshot


def assert_metric_delta(before, result=None, *, fallback=False):
    after = metric_snapshot()
    expected = dict.fromkeys(before, 0)
    if result:
        expected[result] = 1
        expected["duration"] = 1
    expected["fallbacks"] = int(fallback)
    assert {key: after[key] - before[key] for key in before} == expected


def deterministic_fields(request):
    result = main.nl2sql_generator.generate(
        request["text"], request.get("dialect", "hive").strip().lower(),
        request.get("table_hint"), request.get("column_hints"),
    )
    return {
        "success": result.success,
        "input_text": result.input_text,
        "sql": result.sql,
        "dialect": result.dialect,
        "explanation": result.explanation,
        "confidence": result.confidence,
        "suggestions": list(result.suggestions[: settings.nl2sql_max_suggestions]),
        "parameter_style": result.parameter_style,
        "parameters": list(result.parameters),
        "evidence": result.evidence.to_dict() if result.evidence is not None else None,
    }


def assert_deterministic_response(response, expected, *, fallback_reason=None):
    assert response.status_code == 200
    actual = response.json()
    assert {key: actual[key] for key in expected} == expected
    assert actual["provider"] == "deterministic"
    assert actual["model"] is None
    assert actual["fallback_reason"] == fallback_reason
    assert actual["schema_used"] is False


def test_disabled_llm_keeps_existing_worker_call_and_all_result_fields(client, monkeypatch):
    monkeypatch.setattr(settings, "nl2sql_llm_enabled", False)
    factory, generate = stub_llm(monkeypatch)
    request = payload(
        dialect=" MySQL ", table_hint="users", column_hints=["users.id", "users.name"],
    )
    expected = deterministic_fields(request)
    worker = AsyncMock(wraps=main._run_cpu_bound)
    monkeypatch.setattr(main, "_run_cpu_bound", worker)
    before = metric_snapshot()

    response = client.post("/api/nl2sql", json=request)

    assert_deterministic_response(response, expected)
    worker.assert_awaited_once_with(
        main.nl2sql_generator.generate, request["text"], "mysql", "users", ["users.id", "users.name"],
    )
    factory.assert_not_called()
    generate.assert_not_awaited()
    assert_metric_delta(before)


@pytest.mark.parametrize("text", ["insert users", "update user name", "delete users"])
def test_dml_uses_deterministic_generator_even_with_llm_enabled(client, monkeypatch, text):
    factory, generate = stub_llm(monkeypatch)
    request = payload(text=text)
    expected = deterministic_fields(request)
    worker = AsyncMock(wraps=main._run_cpu_bound)
    monkeypatch.setattr(main, "_run_cpu_bound", worker)
    before = metric_snapshot()

    response = client.post("/api/nl2sql", json=request)

    assert_deterministic_response(response, expected)
    worker.assert_awaited_once_with(main.nl2sql_generator.generate, text, "postgres", None, None)
    factory.assert_not_called()
    generate.assert_not_awaited()
    assert_metric_delta(before)


def test_llm_success_preserves_input_normalizes_dialect_and_skips_cpu_pool(client, monkeypatch):
    _, generate = stub_llm(monkeypatch, sql=f"```sql\n{SQL};\n```")
    worker = AsyncMock(side_effect=AssertionError("valid LLM result must not consume an API worker slot"))
    monkeypatch.setattr(main, "_run_cpu_bound", worker)
    request = payload(
        text="  Show two user ids  ", dialect=" POSTGRES ", table_hint="users", column_hints=["users.id"],
    )
    before = metric_snapshot()

    response = client.post("/api/nl2sql", json=request)

    assert response.status_code == 200
    actual = response.json()
    assert actual["success"] is True
    assert actual["input_text"] == request["text"]
    assert actual["sql"].rstrip(";") == SQL
    assert "```" not in actual["sql"]
    assert actual["dialect"] == "postgres"
    assert actual["provider"] == "llm"
    assert actual["model"] == MODEL
    assert actual["fallback_reason"] is None
    assert actual["explanation"] == f"Generated by {MODEL} via OpenRouter."
    assert actual["confidence"] == 0.8
    assert actual["schema_used"] is False
    assert actual["parameter_style"] is None
    assert actual["parameters"] == []
    assert actual["evidence"] == {
        "score": 0.8,
        "items": [{
            "evidence_id": "llm_generated",
            "label": "Generated by the configured LLM",
            "weight": 0.8,
            "detail": MODEL,
        }],
    }
    assert actual["suggestions"]
    assert any("review" in suggestion.lower() for suggestion in actual["suggestions"])
    generate.assert_awaited_once()
    assert generate.await_args.args == (request["text"], "postgres", "users", ["users.id"])
    worker.assert_not_awaited()
    assert_metric_delta(before, "success")


@pytest.mark.parametrize(
    "input_payload,status",
    [
        (payload(dialect="unsupported-db"), 400),
        (payload(table_hint="users; DROP TABLE users"), 400),
        (payload(text=""), 200),
        (payload(text="   "), 200),
        (payload(text="x" * (settings.nl2sql_max_input_length + 1)), 200),
        (payload(column_hints=["users.id;DROP TABLE users"]), 422),
        (payload(column_hints=["users.id"] * 101), 422),
        (payload(column_hints=[1]), 422),
        (payload(text=None), 422),
    ],
    ids=["dialect", "table", "empty", "blank", "overlength", "unsafe-column", "too-many-columns", "nonstring-column", "null-text"],
)
def test_invalid_inputs_preserve_disabled_behavior_without_llm_metrics(client, monkeypatch, input_payload, status):
    factory, generate = stub_llm(monkeypatch)
    monkeypatch.setattr(settings, "nl2sql_llm_enabled", False)
    baseline = client.post("/api/nl2sql", json=input_payload)
    monkeypatch.setattr(settings, "nl2sql_llm_enabled", True)
    before = metric_snapshot()

    response = client.post("/api/nl2sql", json=input_payload)

    assert response.status_code == baseline.status_code == status
    actual = response.json()
    expected = baseline.json()
    if status == 200:
        assert actual == expected
        assert actual["success"] is False
        assert actual["sql"] is None
    else:
        assert actual["error"] == expected["error"]
        assert actual["request_id"] == response.headers["X-Request-ID"]
    factory.assert_not_called()
    generate.assert_not_awaited()
    assert_metric_delta(before)


@pytest.mark.parametrize("reason", RESULTS[1:])
def test_llm_error_falls_back_once_without_changing_deterministic_fields(client, monkeypatch, reason):
    _, generate = stub_llm(monkeypatch, reason=reason)
    request = payload()
    expected = deterministic_fields(request)
    before = metric_snapshot()

    response = client.post("/api/nl2sql", json=request)

    assert_deterministic_response(response, expected, fallback_reason=reason)
    generate.assert_awaited_once()
    assert_metric_delta(before, reason, fallback=True)


@pytest.mark.parametrize("reason", RESULTS[1:])
def test_llm_error_without_fallback_returns_safe_failed_result(client, monkeypatch, reason):
    monkeypatch.setattr(settings, "nl2sql_llm_fallback", False)
    _, generate = stub_llm(monkeypatch, reason=reason)
    worker = AsyncMock(side_effect=AssertionError("disabled fallback must not run the SDK"))
    monkeypatch.setattr(main, "_run_cpu_bound", worker)
    before = metric_snapshot()

    response = client.post("/api/nl2sql", json=payload())

    assert response.status_code == 200
    actual = response.json()
    assert actual["success"] is False
    assert actual["sql"] is None
    assert actual["confidence"] == 0
    assert actual["input_text"] == "show users"
    assert actual["dialect"] == "postgres"
    assert actual["provider"] == "llm"
    assert actual["model"] is None
    assert actual["fallback_reason"] is None
    assert actual["explanation"]
    assert API_KEY not in response.text
    generate.assert_awaited_once()
    worker.assert_not_awaited()
    assert_metric_delta(before, reason)


@pytest.mark.parametrize("sql", ["SELECT (", "DELETE FROM users", "SELECT 1; SELECT 2", "UNSAFE"])
def test_invalid_or_unsafe_generated_sql_is_a_controlled_fallback(client, monkeypatch, sql):
    stub_llm(monkeypatch, sql=sql)
    expected = deterministic_fields(payload())
    before = metric_snapshot()

    response = client.post("/api/nl2sql", json=payload())

    assert_deterministic_response(response, expected, fallback_reason="invalid_sql")
    assert_metric_delta(before, "invalid_sql", fallback=True)


def test_fallback_provenance_does_not_mutate_the_sdk_result(client, monkeypatch):
    original = main.nl2sql_generator.generate("show users", "postgres")
    assert original.provider == "deterministic"
    assert original.model is None
    assert original.fallback_reason is None
    stub_llm(monkeypatch, reason="timeout")
    generator = Mock(return_value=original)
    monkeypatch.setattr(main.nl2sql_generator, "generate", generator)
    before = metric_snapshot()

    response = client.post("/api/nl2sql", json=payload())

    assert response.status_code == 200
    assert response.json()["provider"] == "deterministic"
    assert response.json()["fallback_reason"] == "timeout"
    assert original.provider == "deterministic"
    assert original.model is None
    assert original.fallback_reason is None
    generator.assert_called_once_with("show users", "postgres", None, None)
    assert_metric_delta(before, "timeout", fallback=True)


@pytest.mark.parametrize("path", ["/ready", "/health/deep"])
def test_health_probes_remain_deterministic_with_llm_enabled(client, monkeypatch, path):
    monkeypatch.setattr(settings, "health_probe_token", SecretStr("test-health-probe"))
    monkeypatch.setattr(readiness, "_READINESS_CACHE", {"checks": None, "cached_at": 0.0})
    factory, generate = stub_llm(monkeypatch)
    before = metric_snapshot()

    response = client.get(path, headers={"X-Health-Probe-Token": "test-health-probe"})

    assert response.status_code == 200
    assert response.json()["checks"]["nl2sql"]["status"] == "ok"
    factory.assert_not_called()
    generate.assert_not_awaited()
    assert_metric_delta(before)


@pytest.mark.parametrize("status,code", [(503, "SERVICE_UNAVAILABLE"), (504, "REQUEST_TIMEOUT")])
def test_failed_llm_fallback_preserves_worker_error_contract(client, monkeypatch, status, code):
    stub_llm(monkeypatch, reason="timeout")

    class UnavailablePool:
        async def run(self, *_args, **_kwargs):
            if status == 503:
                raise WorkerCapacityError("Request processing capacity is exhausted")
            raise asyncio.TimeoutError()

    monkeypatch.setattr(main, "_get_worker_pool", lambda: UnavailablePool())
    before = metric_snapshot()

    response = client.post("/api/nl2sql", json=payload())

    assert response.status_code == status
    actual = response.json()
    assert actual["success"] is False
    assert actual["error"]["code"] == code
    assert actual["request_id"] == response.headers["X-Request-ID"]
    if status == 503:
        assert response.headers["Retry-After"] == "1"
    assert_metric_delta(before, "timeout", fallback=True)


@pytest.mark.parametrize("status", [401, 413, 429])
def test_prehandler_rejection_does_not_attempt_llm(client, monkeypatch, status):
    factory, generate = stub_llm(monkeypatch)
    before = metric_snapshot()
    if status == 401:
        monkeypatch.setattr(settings, "api_key", SecretStr("business-key"))
        response = client.post("/api/nl2sql", json=payload())
    elif status == 413:
        response = client.post(
            "/api/nl2sql", content=b"x",
            headers={"Content-Length": str(DEFAULT_MAX_REQUEST_BODY_BYTES + 1)},
        )
    else:
        monkeypatch.setattr(main.rate_limiter, "is_allowed", lambda _client: (False, 0, 17))
        response = client.post("/api/nl2sql", json=payload())

    assert response.status_code == status
    factory.assert_not_called()
    generate.assert_not_awaited()
    assert_metric_delta(before)


def test_api_uses_real_client_mock_transport_without_exposing_provider_secrets(client, monkeypatch, caplog):
    provider_error = "private upstream response containing bearer credentials"
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "openrouter.ai"
        assert request.headers["Authorization"] == f"Bearer {API_KEY}"
        body = json.loads(request.content)
        assert body["model"] == MODEL
        return httpx.Response(503, json={"error": {"message": provider_error}})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(main, "LLMN2SQLClient", lambda: LLMN2SQLClient(settings_obj=settings, transport=transport))
    before = metric_snapshot()

    response = client.post("/api/nl2sql", json=payload())

    assert response.status_code == 200
    assert len(calls) == 1
    assert response.json()["provider"] == "deterministic"
    assert response.json()["fallback_reason"] == "http_5xx"
    assert API_KEY not in response.text
    assert API_KEY not in caplog.text
    assert provider_error not in response.text
    assert provider_error not in caplog.text
    assert_metric_delta(before, "http_5xx", fallback=True)
    for metric in REGISTRY.collect():
        for sample in metric.samples:
            if sample.name == "sdm_nl2sql_llm_requests_total":
                assert set(sample.labels) == {"result"}
                assert sample.labels["result"] in RESULTS
            elif sample.name.startswith("sdm_nl2sql_llm_duration_seconds"):
                assert set(sample.labels) <= {"le"}
            elif sample.name == "sdm_nl2sql_llm_fallbacks_total":
                assert sample.labels == {}


def test_invalid_secret_bearing_model_is_not_echoed_when_fallback_is_disabled(client, monkeypatch, caplog):
    monkeypatch.setattr(settings, "nl2sql_llm_fallback", False)
    monkeypatch.setattr(settings, "nl2sql_llm_model", f"test-provider/{API_KEY}")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": SQL}}]})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(main, "LLMN2SQLClient", lambda: LLMN2SQLClient(settings_obj=settings, transport=transport))
    before = metric_snapshot()

    response = client.post("/api/nl2sql", json=payload())

    assert response.status_code == 200
    actual = response.json()
    assert actual["success"] is False
    assert actual["sql"] is None
    assert actual["provider"] == "llm"
    assert actual["model"] is None
    assert actual["fallback_reason"] is None
    assert len(calls) <= 1
    assert API_KEY not in response.text
    assert API_KEY not in caplog.text
    assert_metric_delta(before, "invalid_response")
