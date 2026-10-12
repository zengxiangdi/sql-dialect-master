"""Direct SDK comparisons obey the same statement boundary as the UI and parser."""
import pytest

from backend.core.semantic_diff import diff_sql_ast


@pytest.mark.parametrize("sql", ["SELECT 1; SELECT 2", "SELECT 1; DROP TABLE users", "SELECT 1;;"])
def test_semantic_diff_rejects_extra_statements(sql):
    result = diff_sql_ast(sql, "SELECT 1", "postgres", "postgres")
    assert result.semantic_classification == "parse_error"
    assert result.parse_error


def test_semantic_diff_accepts_single_statement_with_trailing_comment():
    result = diff_sql_ast("SELECT 1; -- comment", "SELECT 1", "postgres", "postgres")
    assert result.semantic_classification in {"equivalent", "structurally_equivalent"}
