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


def test_semantic_diff_reports_only_changed_relevant_categories():
    result = diff_sql_ast(
        "SELECT department, COUNT(*) FROM users WHERE active = 1 GROUP BY department ORDER BY COUNT(*) DESC LIMIT 10",
        "SELECT department, COUNT(*) FROM users WHERE active = 0 GROUP BY department ORDER BY COUNT(*) ASC LIMIT 20",
        source_dialect="postgres",
        target_dialect="postgres",
    )

    assert result.equivalent is False
    assert result.status == "different"
    assert result.difference_categories == [
        "literal_or_type",
        "ordering",
        "predicate",
        "row_limit",
    ]


def test_predicate_only_change_does_not_report_projection_or_join():
    result = diff_sql_ast(
        "SELECT id FROM users WHERE active = 1",
        "SELECT id FROM users WHERE active = 0",
        source_dialect="postgres",
        target_dialect="postgres",
    )

    assert result.difference_categories == ["literal_or_type", "predicate"]


def test_projection_only_change_reports_projection():
    result = diff_sql_ast(
        "SELECT id FROM users",
        "SELECT name FROM users",
        source_dialect="postgres",
        target_dialect="postgres",
    )

    assert result.difference_categories == ["projection"]


def test_join_only_change_reports_join_without_projection():
    result = diff_sql_ast(
        "SELECT users.id FROM users",
        "SELECT users.id FROM users JOIN departments ON users.department_id = departments.id",
        source_dialect="postgres",
        target_dialect="postgres",
    )

    assert result.difference_categories == ["join"]


def test_limit_only_change_reports_row_limit():
    result = diff_sql_ast(
        "SELECT id FROM users LIMIT 10",
        "SELECT id FROM users LIMIT 20",
        source_dialect="postgres",
        target_dialect="postgres",
    )

    assert result.difference_categories == ["literal_or_type", "row_limit"]


def test_offset_evidence_includes_offset_values():
    result = diff_sql_ast(
        "SELECT id FROM users LIMIT 5 OFFSET 1",
        "SELECT id FROM users LIMIT 5 OFFSET 3",
        source_dialect="postgres",
        target_dialect="postgres",
    )

    row_limit = next(item for item in result.structured_differences if item.category == "row_limit")
    assert "OFFSET 1" in row_limit.source_fragment.upper()
    assert "OFFSET 3" in row_limit.target_fragment.upper()


def test_having_evidence_contains_changed_threshold():
    result = diff_sql_ast(
        "SELECT department, COUNT(*) FROM users GROUP BY department HAVING COUNT(*) > 1",
        "SELECT department, COUNT(*) FROM users GROUP BY department HAVING COUNT(*) > 2",
        source_dialect="postgres",
        target_dialect="postgres",
    )

    predicate = next(item for item in result.structured_differences if item.category == "predicate")
    grouping = next(item for item in result.structured_differences if item.category == "grouping")
    assert "> 1" in predicate.source_fragment
    assert "> 2" in predicate.target_fragment
    assert "> 1" in grouping.source_fragment
    assert "> 2" in grouping.target_fragment


def test_null_semantics_category_ignores_string_literal_text():
    result = diff_sql_ast(
        "SELECT 'NULL' FROM users",
        "SELECT 'NULL VALUE' FROM users",
        source_dialect="postgres",
        target_dialect="postgres",
    )

    assert "null_semantics" not in result.difference_categories
