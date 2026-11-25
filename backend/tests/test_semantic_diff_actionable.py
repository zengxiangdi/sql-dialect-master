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
    ("source", "target", "category"),
    [
        ("SELECT (1 + 2) * 3", "SELECT 1 + 2 * 3", "projection"),
        ("SELECT 1 - (2 - 3)", "SELECT 1 - 2 - 3", "projection"),
        (
            "SELECT id FROM users WHERE ((age + 2) * 3 > 20)",
            "SELECT id FROM users WHERE age + 2 * 3 > 20",
            "predicate",
        ),
    ],
)
def test_semantic_diff_preserves_arithmetic_grouping(source: str, target: str, category: str) -> None:
    result = diff_sql_ast(source, target, source_dialect="postgres", target_dialect="postgres")

    assert result.status == "different"
    assert result.equivalent is False
    difference = next(item for item in result.structured_differences if item.category == category)
    assert difference.source_fragment != difference.target_fragment


@pytest.mark.parametrize(
    "source, target",
    [
        ("SELECT (a + b) - c", "SELECT a + b - c"),
        ("SELECT (a - b) - c", "SELECT a - b - c"),
        ("SELECT (a * b) / c", "SELECT a * b / c"),
        ("SELECT (a / b) / c", "SELECT a / b / c"),
        ("SELECT (a / b) * c", "SELECT a / b * c"),
        ("SELECT a + (b - c)", "SELECT a + b - c"),
        ("SELECT NOT (a = 1)", "SELECT NOT a = 1"),
        ("SELECT id FROM users WHERE (a + 2) > 5", "SELECT id FROM users WHERE a + 2 > 5"),
    ],
)
def test_semantic_diff_accepts_safe_arithmetic_parentheses(source: str, target: str) -> None:
    result = diff_sql_ast(source, target, source_dialect="postgres", target_dialect="postgres")

    assert result.status == "equivalent"
    assert result.equivalent is True


@pytest.mark.parametrize(
    "source, target",
    [
        ("SELECT (a + b) * c", "SELECT a + b * c"),
        ("SELECT a - (b + c)", "SELECT a - b + c"),
        ("SELECT a - (b - c)", "SELECT a - b - c"),
        ("SELECT a * (b / c)", "SELECT a * b / c"),
        ("SELECT a / (b * c)", "SELECT a / b * c"),
        ("SELECT NOT (a OR b)", "SELECT NOT a OR b"),
    ],
)
def test_semantic_diff_keeps_unsafe_arithmetic_parentheses(source: str, target: str) -> None:
    result = diff_sql_ast(source, target, source_dialect="postgres", target_dialect="postgres")

    assert result.status == "different"
    assert result.equivalent is False


@pytest.mark.parametrize(
    "source, target",
    [
        ("SELECT (1 + 2)", "SELECT 1 + 2"),
        ("SELECT id FROM users WHERE (a + 2) > 5", "SELECT id FROM users WHERE a + 2 > 5"),
        ("SELECT id FROM users WHERE (a = 1)", "SELECT id FROM users WHERE a = 1"),
    ],
)
def test_semantic_diff_removes_redundant_parentheses(source: str, target: str) -> None:
    result = diff_sql_ast(source, target, source_dialect="postgres", target_dialect="postgres")

    assert result.status == "equivalent"
    assert result.equivalent is True


def test_semantic_diff_does_not_report_projection_null_as_null_semantics() -> None:
    result = diff_sql_ast(
        "SELECT NULL FROM users",
        "SELECT 1 FROM users",
        source_dialect="postgres",
        target_dialect="postgres",
    )

    assert result.status == "different"
    assert "projection" in result.difference_categories
    assert "null_semantics" not in result.difference_categories


def test_semantic_diff_reports_null_predicate_changes() -> None:
    result = diff_sql_ast(
        "SELECT 1 FROM users WHERE value IS NULL",
        "SELECT 1 FROM users WHERE value = NULL",
        source_dialect="postgres",
        target_dialect="postgres",
    )

    assert result.status == "different"
    assert "null_semantics" in result.difference_categories


def test_semantic_diff_ignores_unchanged_null_predicate_when_other_predicate_changes() -> None:
    result = diff_sql_ast(
        "SELECT 1 FROM users WHERE a = 1 AND b IS NULL",
        "SELECT 1 FROM users WHERE a = 2 AND b IS NULL",
        source_dialect="postgres",
        target_dialect="postgres",
    )

    assert "predicate" in result.difference_categories
    assert "literal_or_type" in result.difference_categories
    assert "null_semantics" not in result.difference_categories


def test_semantic_diff_reports_changed_null_predicate_alongside_other_predicate() -> None:
    result = diff_sql_ast(
        "SELECT 1 FROM users WHERE a = 1 AND b IS NULL",
        "SELECT 1 FROM users WHERE a = 2 AND b IS NOT NULL",
        source_dialect="postgres",
        target_dialect="postgres",
    )

    assert "predicate" in result.difference_categories
    assert "null_semantics" in result.difference_categories


def test_semantic_diff_scopes_null_semantics_to_having() -> None:
    unchanged = diff_sql_ast(
        "SELECT dept, COUNT(*) FROM users GROUP BY dept HAVING a = 1 AND b IS NULL",
        "SELECT dept, COUNT(*) FROM users GROUP BY dept HAVING a = 2 AND b IS NULL",
        source_dialect="postgres",
        target_dialect="postgres",
    )
    changed = diff_sql_ast(
        "SELECT dept, COUNT(*) FROM users GROUP BY dept HAVING a IS NULL",
        "SELECT dept, COUNT(*) FROM users GROUP BY dept HAVING a IS NOT NULL",
        source_dialect="postgres",
        target_dialect="postgres",
    )

    assert "null_semantics" not in unchanged.difference_categories
    assert "null_semantics" in changed.difference_categories


@pytest.mark.parametrize(
    "source, target",
    [
        ("SELECT a * (b)", "SELECT a * b"),
        ("SELECT (a) + b", "SELECT a + b"),
        ("SELECT a = (1)", "SELECT a = 1"),
        ("SELECT id FROM users WHERE (a) = 1", "SELECT id FROM users WHERE a = 1"),
        ("SELECT id FROM users WHERE a AND (b)", "SELECT id FROM users WHERE a AND b"),
        ("SELECT f((a)) FROM users", "SELECT f(a) FROM users"),
    ],
)
def test_semantic_diff_removes_atomic_parentheses(source: str, target: str) -> None:
    result = diff_sql_ast(source, target, source_dialect="postgres", target_dialect="postgres")

    assert result.status == "equivalent"
    assert result.equivalent is True


def test_semantic_diff_keeps_row_constructor_parentheses() -> None:
    result = diff_sql_ast(
        "SELECT (a, b) FROM users",
        "SELECT a, b FROM users",
        source_dialect="postgres",
        target_dialect="postgres",
    )

    assert result.status == "different"
    assert result.equivalent is False


def test_semantic_diff_keeps_subquery_and_in_parentheses() -> None:
    result = diff_sql_ast(
        "SELECT * FROM users WHERE id IN (SELECT id FROM accounts)",
        "SELECT * FROM users WHERE id IN (SELECT id FROM accounts)",
        source_dialect="postgres",
        target_dialect="postgres",
    )

    assert result.status == "equivalent"
    assert result.equivalent is True


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
