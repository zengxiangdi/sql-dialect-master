from backend.core.semantic_diff import SQLSemanticDiffer, diff_sql_ast


def test_semantic_diff_accepts_equivalent_cross_dialect_sql():
    result = diff_sql_ast(
        "SELECT id FROM users WHERE age > 10",
        "select id from users where age > 10",
        source_dialect="postgres",
        target_dialect="duckdb",
    )

    assert result.equivalent is True
    assert result.differences == []


def test_semantic_diff_detects_predicate_change():
    result = SQLSemanticDiffer.compare(
        "SELECT id FROM users WHERE age > 10",
        "SELECT id FROM users WHERE age >= 10",
        source_dialect="postgres",
        target_dialect="duckdb",
    )

    assert result.equivalent is False
    assert any("Canonical AST SQL differs" in item for item in result.differences)


def test_semantic_diff_reports_parse_failure():
    result = diff_sql_ast(
        "SELECT id FROM users",
        "SELECT FROM",
        source_dialect="postgres",
        target_dialect="duckdb",
    )

    assert result.equivalent is False
    assert result.parse_error
    assert result.differences == ["Unable to parse one or both SQL statements"]
