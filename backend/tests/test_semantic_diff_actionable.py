import pytest

from backend.core.semantic_diff import diff_sql_ast


def test_structured_difference_exposes_fields_for_predicate_change():
    result = diff_sql_ast(
        "SELECT id FROM users WHERE age > 10",
        "SELECT id FROM users WHERE age >= 10",
        source_dialect="postgres",
        target_dialect="duckdb",
    )

    assert result.status == "different"
    assert result.structured_differences
    difference = result.structured_differences[0]
    assert difference.category == "predicate"
    assert difference.severity in {"warning", "error"}
    assert difference.source_fragment
    assert difference.target_fragment
    assert difference.explanation
    assert result.semantic_classification == "definitely_different"


def test_textually_different_but_structurally_equivalent_sql_is_equivalent():
    result = diff_sql_ast(
        "SELECT id FROM users WHERE age > 10",
        "SELECT id FROM users WHERE (age > 10)",
        source_dialect="postgres",
        target_dialect="duckdb",
    )

    assert result.status == "equivalent"
    assert result.equivalent is True
    assert result.structured_differences == []
    assert result.semantic_classification == "structurally_equivalent"


@pytest.mark.parametrize(
    "source, target, expected_status, category",
    [
        (
            "SELECT id FROM users WHERE a = 1 OR b = 2 AND c = 3",
            "SELECT id FROM users WHERE (a = 1 OR b = 2) AND c = 3",
            "different",
            "predicate",
        ),
        (
            "SELECT id FROM users WHERE deleted_at IS NULL",
            "SELECT id FROM users WHERE deleted_at = NULL",
            "different",
            "null_semantics",
        ),
        (
            "SELECT id FROM users ORDER BY created_at",
            "SELECT id FROM users ORDER BY created_at DESC",
            "different",
            "ordering",
        ),
        (
            "SELECT id FROM users LIMIT 10",
            "SELECT TOP 20 id FROM users",
            "different",
            "row_limit",
        ),
    ],
)
def test_high_risk_regions_report_structured_categories(source, target, expected_status, category):
    result = diff_sql_ast(source, target, source_dialect="postgres", target_dialect="tsql")

    assert result.status == expected_status
    assert any(item.category == category for item in result.structured_differences)
