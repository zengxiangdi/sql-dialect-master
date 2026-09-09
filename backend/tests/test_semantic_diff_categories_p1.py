from backend.core.semantic_diff import diff_sql_ast


def test_function_changes_are_reported_as_function_category():
    result = diff_sql_ast(
        "SELECT LENGTH(name) FROM users",
        "SELECT UPPER(name) FROM users",
        source_dialect="postgres",
        target_dialect="postgres",
    )

    assert result.equivalent is False
    assert result.status == "different"
    assert "function" in result.difference_categories


def test_semantic_diff_reports_multiple_relevant_categories():
    result = diff_sql_ast(
        "SELECT department, COUNT(*) FROM users WHERE active = 1 GROUP BY department ORDER BY COUNT(*) DESC LIMIT 10",
        "SELECT department, COUNT(*) FROM users WHERE active = 0 GROUP BY department ORDER BY COUNT(*) ASC LIMIT 20",
        source_dialect="postgres",
        target_dialect="postgres",
    )

    assert result.equivalent is False
    assert result.status == "different"
    assert {"predicate", "aggregate", "ordering", "row_limit", "grouping"}.issubset(
        set(result.difference_categories)
    )
