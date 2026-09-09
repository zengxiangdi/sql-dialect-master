from backend.core.semantic_diff import SQLSemanticDiffer, diff_sql_ast


def test_semantic_diff_accepts_equivalent_cross_dialect_sql():
    result = diff_sql_ast(
        "SELECT id FROM users WHERE age > 10",
        "select id from users where age > 10",
        source_dialect="postgres",
        target_dialect="duckdb",
    )

    assert result.equivalent is True
    assert result.status == "equivalent"
    assert result.differences == []


def test_semantic_diff_detects_predicate_change():
    result = SQLSemanticDiffer.compare(
        "SELECT id FROM users WHERE age > 10",
        "SELECT id FROM users WHERE age >= 10",
        source_dialect="postgres",
        target_dialect="duckdb",
    )

    assert result.equivalent is False
    assert result.status == "different"
    assert "predicate" in result.difference_categories
    assert any("Canonical AST SQL differs" in item for item in result.differences)


def test_semantic_diff_reports_parse_failure():
    result = diff_sql_ast(
        "SELECT id FROM users",
        "SELECT FROM",
        source_dialect="postgres",
        target_dialect="duckdb",
    )

    assert result.equivalent is False
    assert result.status == "parse_error"
    assert result.parse_error
    assert result.differences == ["Unable to parse one or both SQL statements"]


def test_semantic_diff_marks_context_sensitive_functions_unknown():
    result = diff_sql_ast(
        "SELECT CURRENT_TIMESTAMP FROM users",
        "SELECT CURRENT_TIMESTAMP FROM users",
        source_dialect="postgres",
        target_dialect="duckdb",
    )

    assert result.equivalent is False
    assert result.status == "unknown"
    assert "context_sensitive" in result.difference_categories
    assert any("context-sensitive" in item.lower() for item in result.differences)
