import pytest

from backend.benchmarks.transpiler_benchmark import (
    per_statement_seconds,
    summarize_timings,
)


def test_per_statement_seconds_normalizes_total_time() -> None:
    assert per_statement_seconds(2.0, 4) == 0.5


@pytest.mark.parametrize("statement_count", [0, -1, -10])
def test_per_statement_seconds_rejects_non_positive_count(statement_count: int) -> None:
    with pytest.raises(ValueError, match="statement_count must be positive"):
        per_statement_seconds(1.0, statement_count)


def test_summarize_timings_keeps_totals_and_adds_per_statement_metrics() -> None:
    summary = summarize_timings([1.0, 3.0], statement_count=2)

    assert summary["timings_seconds"] == [1.0, 3.0]
    assert summary["mean_seconds"] == 2.0
    assert summary["median_seconds"] == 2.0
    assert summary["statement_count"] == 2
    assert summary["per_statement_seconds"] == 1.0
    assert summary["per_statement_ms"] == 1000.0
