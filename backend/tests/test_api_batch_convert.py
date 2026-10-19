"""REST batches preserve item contracts while sharing one bounded worker slot."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Event

import pytest
from fastapi.testclient import TestClient

from backend.api import main
from backend.api.workers import BoundedWorkerPool
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
        response = client.post("/api/convert/batch", json=batch_payload(["SELECT 1", "SELECT 2"]))
        assert started.is_set()
        assert_error_envelope(response, 504, "REQUEST_TIMEOUT")
        assert pool.stats()["in_use"] == 1
        assert pool.stats()["timeouts"] == 1
        assert not finished.is_set()

        rejected = client.post("/api/convert/batch", json=batch_payload())
        assert_error_envelope(rejected, 503, "SERVICE_UNAVAILABLE")
        assert rejected.headers["Retry-After"] == "1"

        release.set()
        assert finished.wait(2), "background batch did not finish"
        # The single executor thread runs this barrier after its completion
        # callbacks, so observing a released slot needs no timing-based sleep.
        pool._executor.submit(lambda: None).result(timeout=2)
        assert pool.stats()["in_use"] == 0
        assert len(background_results) == 2
        assert all(item.success for item in background_results)

        monkeypatch.setattr(settings, "request_timeout", 2)
        recovered = client.post("/api/convert/batch", json=batch_payload())
        assert recovered.status_code == 200
        assert recovered.json()["success"] is True
    finally:
        release.set()
        pool.shutdown()
