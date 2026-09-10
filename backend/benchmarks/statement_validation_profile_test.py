from backend.benchmarks.statement_validation_profile import run


def test_statement_validation_profile_reports_parse_breakdown():
    payload = run(iterations=4, repeats=1, dialect="mysql")
    measurements = payload["measurements"]

    assert payload["workload"]["iterations"] == 4
    assert measurements["has_multiple_statements"]["per_statement_ms"] >= 0
    assert measurements["sqlglot_parse_only"]["per_statement_ms"] >= 0
    assert measurements["sqlglot_parse_and_count"]["per_statement_ms"] >= 0
    assert 0 <= payload["analysis"]["parse_share_of_statement_validation_percent"] < 1000
