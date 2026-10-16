"""HTTP contract tests for the semantic diff endpoint."""

from fastapi.testclient import TestClient

from backend.api import main
from backend.api.main import app


client = TestClient(app)


def _payload(**overrides):
    payload = {
        "source_sql": "SELECT id FROM users",
        "target_sql": "SELECT id FROM users",
        "source_dialect": "postgres",
        "target_dialect": "mysql",
    }
    payload.update(overrides)
    return payload


def test_semantic_diff_reports_equivalent_statements():
    response = client.post("/api/diff", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["status"] == "equivalent"
    assert body["equivalent"] is True


def test_semantic_diff_reports_categories_and_structured_findings():
    response = client.post(
        "/api/diff",
        json=_payload(target_sql="SELECT name FROM users"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "different"
    assert body["difference_categories"]
    assert body["structured_differences"]


def test_semantic_diff_returns_parse_error_as_analysis_result():
    response = client.post(
        "/api/diff",
        json=_payload(source_sql="SELEC FROM", target_sql="SELECT 1"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["status"] == "parse_error"
    assert body["error"]


def test_semantic_diff_rejects_unsupported_dialect():
    response = client.post("/api/diff", json=_payload(source_dialect="invalid"))

    assert response.status_code == 400


def test_existing_parse_and_convert_routes_remain_available():
    assert client.post("/api/parse", json={"sql": "SELECT 1", "dialect": "postgres"}).status_code == 200
    assert client.post(
        "/api/convert",
        json={"sql": "SELECT 1", "source_dialect": "postgres", "target_dialect": "mysql"},
    ).status_code == 200


def test_parse_reuses_cached_extraction_for_identical_requests(monkeypatch):
    sql = "SELECT cache_probe_column FROM cache_probe_table"
    main._parse_elements_cached.cache_clear()
    parser = main._get_sql_parser("postgres")
    original = parser.extract_elements
    calls = 0

    def counted(statement):
        nonlocal calls
        calls += 1
        return original(statement)

    monkeypatch.setattr(parser, "extract_elements", counted)
    assert client.post("/api/parse", json={"sql": sql, "dialect": "postgres"}).status_code == 200
    assert client.post("/api/parse", json={"sql": sql, "dialect": "postgres"}).status_code == 200
    assert calls == 1

