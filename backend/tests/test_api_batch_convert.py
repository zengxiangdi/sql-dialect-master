"""REST batches preserve item contracts while sharing one bounded worker slot."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Event

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.api import main
from backend.api.metrics import REGISTRY
from backend.api.middleware import DEFAULT_MAX_REQUEST_BODY_BYTES
from backend.api.workers import BoundedWorkerPool, WorkerCapacityError
from backend.core.config import settings
from backend.core.transpiler import TranspileResult


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "api_key", None)
    monkeypatch.setattr(settings, "security_check_enabled", True)
    monkeypatch.setattr(settings, "security_block_dangerous", True)
    with TestClient(main.app) as test_client:
        yield test_client


def batch_payload(statements=None, **overrides):
    payload = {
        "statements": ["SELECT 1"] if statements is None else statements,
        "source_dialect": "postgres",
        "target_dialect": "mysql",
    }
    payload.update(overrides)
    return payload


def assert_error_envelope(response, status, code):
    assert response.status_code == status
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == code
    assert payload["request_id"] == response.headers["X-Request-ID"]
    assert "results" not in payload
    datetime.fromisoformat(payload["timestamp"])


def batch_metric_snapshot(source="postgres", target="mysql"):
    def value(name, labels=None):
        return REGISTRY.get_sample_value(name, labels or {}) or 0

    snapshot = {}
    for result in ("success", "partial_failure", "error", "validation_error"):
        snapshot[f"requests_{result}"] = value(
            "sdm_transpile_batch_requests_total", {"source": source, "target": target, "result": result},
        )
    for result in ("success", "error"):
        snapshot[f"items_{result}"] = value(
            "sdm_transpile_batch_items_total", {"source": source, "target": target, "result": result},
        )
    for suffix in ("count", "sum"):
        snapshot[f"size_{suffix}"] = value(f"sdm_transpile_batch_size_{suffix}")
    for boundary in ("1.0", "2.0", "5.0", "10.0", "20.0", "50.0", "100.0", "+Inf"):
        snapshot[f"bucket_{boundary}"] = value("sdm_transpile_batch_size_bucket", {"le": boundary})
    snapshot["single_requests"] = sum(
        sample.value
        for metric in REGISTRY.collect()
        for sample in metric.samples
        if sample.name == "sdm_transpile_requests_total"
    )
    return snapshot


def assert_batch_metric_delta(
    before, *, request_result=None, succeeded=0, failed=0, size=None, source="postgres", target="mysql",
):
    after = batch_metric_snapshot(source, target)
    actual = {key: after[key] - before[key] for key in before}
    expected = dict.fromkeys(before, 0)
    if request_result:
        expected[f"requests_{request_result}"] = 1
    expected["items_success"] = succeeded
    expected["items_error"] = failed
    if size is not None:
        expected["size_count"] = 1
        expected["size_sum"] = size
        for boundary in ("1.0", "2.0", "5.0", "10.0", "20.0", "50.0", "100.0", "+Inf"):
            expected[f"bucket_{boundary}"] = int(size <= float(boundary))
    assert actual == expected


def test_batch_success_preserves_order_and_conversion_fields(client):
    statements = ["SELECT 1 AS first", "SELECT 2 AS second", "SELECT 3 AS third"]
    response = client.post("/api/convert/batch", json=batch_payload(statements, pretty=False))

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert (payload["count"], payload["succeeded"], payload["failed"]) == (3, 3, 0)
    datetime.fromisoformat(payload["timestamp"])
    assert response.headers["Cache-Control"] == "no-store"
    for index, (statement, item) in enumerate(zip(statements, payload["results"], strict=True)):
        assert item["index"] == index
        assert item["source_sql"] == statement
        assert item["target_sql"] == statement
        assert item["source_dialect"] == "postgres"
        assert item["target_dialect"] == "mysql"
        assert item["success"] is True
        assert item["error"] is None
        assert item["error_code"] is None
        assert item["target_validation_state"] == "target_valid"
        for key in ("compatibility_notes", "transformations", "warnings"):
            assert isinstance(item[key], list)
        datetime.fromisoformat(item["timestamp"])


def test_batch_partial_failures_keep_positions_and_continue(client):
    statements = ["SELECT 1 AS first", "  ", "DROP TABLE users", "SELECT 4 AS fourth"]
    response = client.post("/api/convert/batch", json=batch_payload(statements, pretty=False))

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert (payload["count"], payload["succeeded"], payload["failed"]) == (4, 2, 2)
    assert [item["index"] for item in payload["results"]] == [0, 1, 2, 3]
    assert [item["source_sql"] for item in payload["results"]] == statements
    assert [item["success"] for item in payload["results"]] == [True, False, False, True]
    assert [item["error_code"] for item in payload["results"]] == [
        None, "VALIDATION_FAILED", "SECURITY_VIOLATION", None,
    ]
    assert all(item["error"] for item in payload["results"][1:3])
    assert payload["results"][3]["target_sql"] == "SELECT 4 AS fourth"


def test_batch_preserves_warning_and_validation_fields(client, monkeypatch):
    result = TranspileResult(
        success=True,
        source_sql="SELECT 1",
        target_sql="SELECT 1",
        source_dialect="postgres",
        target_dialect="mysql",
        compatibility_notes=["compatibility note"],
        transformations=["applied transformation"],
        warnings=["generic parser accepted output"],
        target_validation_state="generic_only",
    )
    monkeypatch.setattr(main.transpiler, "batch_transpile", lambda *_args: [result])
    response = client.post("/api/convert/batch", json=batch_payload())

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["succeeded"] == 1
    item = payload["results"][0]
    assert {key: item[key] for key in result.to_dict()} == result.to_dict()
    assert item["index"] == 0


def test_batch_all_item_failures_still_return_200(client):
    response = client.post("/api/convert/batch", json=batch_payload(["", "DROP TABLE users"]))

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert (payload["count"], payload["succeeded"], payload["failed"]) == (2, 0, 2)
    assert [item["error_code"] for item in payload["results"]] == [
        "VALIDATION_FAILED", "SECURITY_VIOLATION",
    ]


@pytest.mark.parametrize(
    "changes,removed_field",
    [
        ({"statements": []}, None),
        ({"statements": ["SELECT 1"] * (settings.max_batch_size + 1)}, None),
        ({}, "statements"),
        ({}, "source_dialect"),
        ({}, "target_dialect"),
        ({"statements": "SELECT 1"}, None),
        ({"statements": None}, None),
        ({"statements": {"sql": "SELECT 1"}}, None),
        ({"statements": ["SELECT 1", 1]}, None),
        ({"statements": ["SELECT 1", True]}, None),
        ({"statements": ["SELECT 1", None]}, None),
        ({"statements": ["SELECT 1", {"sql": "SELECT 2"}]}, None),
    ],
    ids=[
        "empty", "over-limit", "missing-statements", "missing-source", "missing-target",
        "string-not-array", "null-not-array", "object-not-array", "number-item",
        "bool-item", "null-item", "object-item",
    ],
)
def test_batch_invalid_request_is_422_before_worker(client, monkeypatch, changes, removed_field):
    async def unexpected_worker(*_args):
        pytest.fail("invalid request must not submit worker work")

    monkeypatch.setattr(main, "_run_cpu_bound", unexpected_worker)
    payload = batch_payload()
    payload.update(changes)
    if removed_field:
        payload.pop(removed_field)
    response = client.post("/api/convert/batch", json=payload)

    assert_error_envelope(response, 422, "VALIDATION_FAILED")
    assert response.json()["error"]["details"]


def test_batch_accepts_exact_maximum_statement_count(client):
    statements = ["SELECT 1"] * settings.max_batch_size
    response = client.post("/api/convert/batch", json=batch_payload(statements))

    assert response.status_code == 200
    assert response.json()["count"] == settings.max_batch_size
    assert response.json()["succeeded"] == settings.max_batch_size
    assert response.json()["results"][-1]["index"] == settings.max_batch_size - 1


@pytest.mark.parametrize("field", ["source_dialect", "target_dialect"])
def test_batch_invalid_dialect_is_400_before_worker(client, monkeypatch, field):
    async def unexpected_worker(*_args):
        pytest.fail("invalid dialect must not submit worker work")

    monkeypatch.setattr(main, "_run_cpu_bound", unexpected_worker)
    response = client.post("/api/convert/batch", json=batch_payload(**{field: "not-a-dialect"}))

    assert_error_envelope(response, 400, "BAD_REQUEST")


def test_batch_normalizes_dialect_whitespace_and_case(client):
    response = client.post(
        "/api/convert/batch",
        json=batch_payload(source_dialect=" POSTGRES ", target_dialect=" MySQL "),
    )

    assert response.status_code == 200
    item = response.json()["results"][0]
    assert item["success"] is True
    assert item["source_dialect"] == "postgres"
    assert item["target_dialect"] == "mysql"


@pytest.mark.parametrize("pretty", [None, False])
def test_batch_pretty_default_and_explicit_false(client, pretty):
    sql = "SELECT id, name FROM users WHERE id > 1"
    overrides = {} if pretty is None else {"pretty": pretty}
    response = client.post("/api/convert/batch", json=batch_payload([sql], **overrides))

    assert response.status_code == 200
    item = response.json()["results"][0]
    assert item["success"] is True
    expected_pretty = settings.transpiler_pretty_default if pretty is None else pretty
    assert ("\n" in item["target_sql"]) is expected_pretty


def test_batch_overlong_sql_is_an_item_failure(client, monkeypatch):
    monkeypatch.setattr(settings, "transpiler_max_sql_length", 40)
    long_sql = "SELECT '" + "x" * 120 + "'"
    response = client.post("/api/convert/batch", json=batch_payload([long_sql, "SELECT 2"], pretty=False))

    assert response.status_code == 200
    payload = response.json()
    assert (payload["count"], payload["succeeded"], payload["failed"]) == (2, 1, 1)
    assert payload["results"][0]["index"] == 0
    assert payload["results"][0]["error_code"] == "VALIDATION_FAILED"
    assert payload["results"][0]["source_sql"] == long_sql[:100] + "..."
    assert payload["results"][1]["target_sql"] == "SELECT 2"


def test_batch_does_not_split_semicolons_in_literals_or_comments(client):
    statements = [
        "SELECT 'a;b' AS message",
        "SELECT 1 -- a comment; still one statement",
        "SELECT 2 /* another; comment */",
    ]
    response = client.post("/api/convert/batch", json=batch_payload(statements))

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["count"] == 3
    assert [item["source_sql"] for item in payload["results"]] == statements
    assert "a;b" in payload["results"][0]["target_sql"]


def test_batch_uses_one_slot_and_rejects_other_requests(client, monkeypatch):
    pool = BoundedWorkerPool(workers=1, queue_size=0)
    started = Event()
    release = Event()
    original_batch = main.transpiler.batch_transpile
    calls = []

    def blocked_batch(*args):
        calls.append(args)
        started.set()
        if not release.wait(5):
            raise AssertionError("test did not release batch worker")
        return original_batch(*args)

    monkeypatch.setattr(main, "_get_worker_pool", lambda: pool)
    monkeypatch.setattr(main.transpiler, "batch_transpile", blocked_batch)
    try:
        with ThreadPoolExecutor(max_workers=1) as requests:
            pending = requests.submit(
                client.post, "/api/convert/batch", json=batch_payload(["SELECT 1", "SELECT 2"]),
            )
            try:
                assert started.wait(2), "batch did not start"
                assert pool.stats()["in_use"] == 1
                rejected = client.post("/api/convert/batch", json=batch_payload())
                assert_error_envelope(rejected, 503, "SERVICE_UNAVAILABLE")
                assert rejected.headers["Retry-After"] == "1"
                assert pool.stats()["rejections"] == 1
                assert len(calls) == 1
            finally:
                release.set()
            response = pending.result(timeout=3)
        assert response.status_code == 200
        assert response.json()["succeeded"] == 2
        assert calls[0] == (["SELECT 1", "SELECT 2"], "postgres", "mysql", settings.transpiler_pretty_default)
        assert pool.stats()["in_use"] == 0
    finally:
        release.set()
        pool.shutdown()


def test_batch_timeout_holds_slot_until_background_batch_finishes(client, monkeypatch):
    pool = BoundedWorkerPool(workers=1, queue_size=0)
    started = Event()
    release = Event()
    finished = Event()
    original_batch = main.transpiler.batch_transpile
    background_results = []

    def blocked_batch(*args):
        started.set()
        if not release.wait(5):
            raise AssertionError("test did not release timed-out batch worker")
        results = original_batch(*args)
        background_results.extend(results)
        finished.set()
        return results

    monkeypatch.setattr(main, "_get_worker_pool", lambda: pool)
    monkeypatch.setattr(main.transpiler, "batch_transpile", blocked_batch)
    monkeypatch.setattr(settings, "request_timeout", 0.03)
    try:
        metrics_before = batch_metric_snapshot()
        response = client.post("/api/convert/batch", json=batch_payload(["SELECT 1", "SELECT 2"]))
        assert started.is_set()
        assert_error_envelope(response, 504, "REQUEST_TIMEOUT")
        assert pool.stats()["in_use"] == 1
        assert pool.stats()["timeouts"] == 1
        assert not finished.is_set()
        assert_batch_metric_delta(metrics_before, request_result="error", size=2)

        rejected = client.post("/api/convert/batch", json=batch_payload())
        assert_error_envelope(rejected, 503, "SERVICE_UNAVAILABLE")
        assert rejected.headers["Retry-After"] == "1"
        before_background_completion = batch_metric_snapshot()

        release.set()
        assert finished.wait(2), "background batch did not finish"
        # The single executor thread runs this barrier after its completion
        # callbacks, so observing a released slot needs no timing-based sleep.
        pool._executor.submit(lambda: None).result(timeout=2)
        assert pool.stats()["in_use"] == 0
        assert len(background_results) == 2
        assert all(item.success for item in background_results)
        assert_batch_metric_delta(before_background_completion)

        monkeypatch.setattr(settings, "request_timeout", 2)
        recovered = client.post("/api/convert/batch", json=batch_payload())
        assert recovered.status_code == 200
        assert recovered.json()["success"] is True
    finally:
        release.set()
        pool.shutdown()


@pytest.mark.parametrize(
    "statements,result,succeeded,failed",
    [
        (["SELECT 1", "SELECT 2", "SELECT 3"], "success", 3, 0),
        (["SELECT 1", "", "DROP TABLE users"], "partial_failure", 1, 2),
        (["", "DROP TABLE users"], "error", 0, 2),
    ],
    ids=["success", "partial-failure", "all-failed"],
)
def test_batch_result_metrics_have_exact_deltas(client, statements, result, succeeded, failed):
    before = batch_metric_snapshot()
    response = client.post(
        "/api/convert/batch",
        json=batch_payload(statements, source_dialect=" POSTGRES ", target_dialect=" MySQL "),
    )

    assert response.status_code == 200
    assert_batch_metric_delta(
        before, request_result=result, succeeded=succeeded, failed=failed, size=len(statements),
    )


@pytest.mark.parametrize("status", [503, 504])
def test_batch_worker_failure_metrics_do_not_invent_item_results(client, monkeypatch, status):
    class UnavailablePool:
        async def run(self, *_args, **_kwargs):
            if status == 503:
                raise WorkerCapacityError("test worker is busy")
            raise asyncio.TimeoutError()

    monkeypatch.setattr(main, "_get_worker_pool", lambda: UnavailablePool())
    before = batch_metric_snapshot()
    response = client.post("/api/convert/batch", json=batch_payload(["SELECT 1", "SELECT 2"]))

    code = "SERVICE_UNAVAILABLE" if status == 503 else "REQUEST_TIMEOUT"
    assert_error_envelope(response, status, code)
    assert_batch_metric_delta(before, request_result="error", size=2)


@pytest.mark.parametrize("failure", ["worker-exception", "malformed-result"])
def test_batch_unexpected_failure_metrics_do_not_count_items(client, monkeypatch, failure):
    if failure == "worker-exception":
        def fail_batch(*_args):
            raise RuntimeError("private worker failure detail")

        monkeypatch.setattr(main.transpiler, "batch_transpile", fail_batch)
    else:
        malformed_result = TranspileResult(
            success=True,
            source_sql="SELECT 1",
            target_sql=123,
            source_dialect="postgres",
            target_dialect="mysql",
        )
        monkeypatch.setattr(main.transpiler, "batch_transpile", lambda *_args: [malformed_result])
    before = batch_metric_snapshot()
    error_client = TestClient(main.app, raise_server_exceptions=False)
    try:
        response = error_client.post("/api/convert/batch", json=batch_payload())
    finally:
        error_client.close()

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "results" not in response.json()
    assert "private worker failure detail" not in response.text
    assert_batch_metric_delta(before, request_result="error", size=1)


@pytest.mark.parametrize(
    "field,source,target",
    [("source_dialect", "unknown", "unknown"), ("target_dialect", "postgres", "unknown")],
)
def test_batch_invalid_dialect_metrics_use_only_fixed_unknown_labels(client, field, source, target):
    before = batch_metric_snapshot(source, target)
    response = client.post(
        "/api/convert/batch", json=batch_payload(**{field: "private-unsupported-dialect-value"}),
    )

    assert_error_envelope(response, 400, "BAD_REQUEST")
    assert_batch_metric_delta(before, request_result="validation_error", source=source, target=target)
    for metric in REGISTRY.collect():
        for sample in metric.samples:
            if sample.name.startswith("sdm_transpile_batch_"):
                assert "private-unsupported-dialect-value" not in sample.labels.values()


@pytest.mark.parametrize("status", [401, 413, 422, 429])
def test_batch_prehandler_rejections_do_not_increment_batch_metrics(client, monkeypatch, status):
    before = batch_metric_snapshot()
    if status == 401:
        monkeypatch.setattr(settings, "api_key", SecretStr("test-business-api-key"))
        response = client.post("/api/convert/batch", json=batch_payload())
        code = "UNAUTHORIZED"
    elif status == 413:
        response = client.post(
            "/api/convert/batch", content=b"x",
            headers={"Content-Length": str(DEFAULT_MAX_REQUEST_BODY_BYTES + 1)},
        )
        code = "PAYLOAD_TOO_LARGE"
    elif status == 422:
        response = client.post("/api/convert/batch", json=batch_payload([]))
        code = "VALIDATION_FAILED"
    else:
        monkeypatch.setattr(main.rate_limiter, "is_allowed", lambda _client_id: (False, 0, 17))
        response = client.post("/api/convert/batch", json=batch_payload())
        code = "RATE_LIMITED"

    assert_error_envelope(response, status, code)
    assert_batch_metric_delta(before)


def test_batch_metrics_exposition_has_bounded_labels_and_no_request_data(client, monkeypatch):
    token = "batch-metrics-private-token"
    request_id = "ea6de6e7-75d1-45e9-8a82-cd6231c5a121"
    client_ip = "198.51.100.174"
    sql = "SELECT private_batch_column FROM private_batch_table"
    monkeypatch.setattr(settings, "metrics_enabled", True)
    monkeypatch.setattr(settings, "metrics_token", SecretStr(token))
    response = client.post(
        "/api/convert/batch?private-query=private-query-marker",
        json=batch_payload([sql, "DROP TABLE private_batch_table"]),
        headers={"X-Request-ID": request_id, "X-Forwarded-For": client_ip},
    )
    assert response.status_code == 200
    error_text = response.json()["results"][1]["error"]
    scrape = client.get("/metrics", headers={"X-Metrics-Token": token})

    assert scrape.status_code == 200
    for private_value in (
        token, request_id, client_ip, sql, "private_batch_column", "private_batch_table",
        "private-query", "private-query-marker", error_text,
    ):
        assert private_value not in scrape.text
    for metric in REGISTRY.collect():
        for sample in metric.samples:
            if sample.name in {"sdm_transpile_batch_requests_total", "sdm_transpile_batch_items_total"}:
                assert set(sample.labels) == {"source", "target", "result"}
                assert sample.labels["source"] in {*main.SUPPORTED_DIALECTS, "unknown"}
                assert sample.labels["target"] in {*main.SUPPORTED_DIALECTS, "unknown"}
                allowed_results = (
                    {"success", "error"}
                    if sample.name == "sdm_transpile_batch_items_total"
                    else {"success", "partial_failure", "error", "validation_error"}
                )
                assert sample.labels["result"] in allowed_results
            elif sample.name == "sdm_transpile_batch_size_bucket":
                assert set(sample.labels) == {"le"}
