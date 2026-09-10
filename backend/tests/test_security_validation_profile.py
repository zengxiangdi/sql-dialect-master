from backend.benchmarks.security_validation_profile import SECURITY_CASES, run


def test_security_validation_profile_shape():
    payload = run(iterations=4, repeats=1)

    assert set(payload) == {
        "environment",
        "workload",
        "measurements",
        "analysis",
        "boundary_cases",
        "notes",
    }
    assert payload["workload"]["iterations"] == 4
    assert payload["workload"]["repeats"] == 1
    assert payload["workload"]["case_count"] == len(SECURITY_CASES)

    expected_stages = {
        "mask_non_executable",
        "dangerous_operation_regex",
        "sqlglot_parse",
        "dangerous_pattern_scan",
        "warning_pattern_scan",
        "validate_security",
    }
    assert set(payload["measurements"]) == expected_stages
    for measurement in payload["measurements"].values():
        assert measurement["mean_seconds"] >= 0
        assert measurement["median_seconds"] >= 0
        assert measurement["per_statement_ms"] >= 0
        assert len(measurement["timings_seconds"]) == 1

    assert set(payload["analysis"]) == {
        "substage_share_of_full_validation_percent",
        "full_validation_total_seconds_mean",
        "patterns",
    }
    assert len(payload["boundary_cases"]) == len(SECURITY_CASES)
    assert all(
        {"name", "sql", "blocked", "multiple_statements", "warning_count"}
        <= set(case)
        for case in payload["boundary_cases"]
    )
