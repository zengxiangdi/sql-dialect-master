from backend.benchmarks.statement_validation_profile import run


def test_statement_validation_profile_reports_parse_breakdown():
    payload = run(iterations=4, repeats=1, dialect="mysql")
    measurements = payload["measurements"]

    if payload["workload"]["iterations"] != 4:
        raise AssertionError("unexpected workload iteration count")
    if measurements["has_multiple_statements"]["per_statement_ms"] < 0:
        raise AssertionError("negative has_multiple_statements timing")
    if measurements["sqlglot_parse_only"]["per_statement_ms"] < 0:
        raise AssertionError("negative parse-only timing")
    if measurements["sqlglot_parse_and_count"]["per_statement_ms"] < 0:
        raise AssertionError("negative parse-and-count timing")
    parse_share = payload["analysis"]["parse_share_of_statement_validation_percent"]
    if not 0 <= parse_share < 1000:
        raise AssertionError("invalid parse share")
