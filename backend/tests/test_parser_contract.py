"""Public contract tests for :mod:`backend.core.parser`."""

import pytest

from backend.core.config import settings
from backend.core.parser import SQLParser


def test_constructor_normalizes_supported_dialect_and_rejects_unknown() -> None:
    assert SQLParser("  MySQL ").dialect == "mysql"

    with pytest.raises(ValueError, match="Unsupported dialect"):
        SQLParser("not-a-dialect")


def test_parse_and_validate_input_errors_and_valid_sql(monkeypatch) -> None:
    parser = SQLParser("postgres")

    non_string = parser.parse(None)  # type: ignore[arg-type]
    assert non_string.success is False
    assert non_string.error == "SQL statement must be a string"
    assert parser.validate(None) == (False, "SQL statement must be a string")  # type: ignore[arg-type]

    for sql in ("", "   "):
        result = parser.parse(sql)
        assert result.success is False
        assert result.error == "Empty SQL statement"
        assert parser.validate(sql) == (False, "Empty SQL statement")

    invalid = parser.parse("SELECT * FROM")
    assert invalid.success is False
    assert invalid.error and "Expected table name" in invalid.error
    valid = parser.parse("SELECT id FROM users")
    assert valid.success is True
    assert valid.query_type == "SELECT"
    assert valid.ast is not None
    assert parser.validate("SELECT id FROM users") == (True, None)

    monkeypatch.setattr(settings, "parser_max_sql_length", 5)
    oversized = parser.parse("SELECT 1")
    assert oversized.success is False
    assert oversized.error == "SQL exceeds maximum length of 5 characters"
    assert parser.validate("SELECT 1") == (
        False,
        "SQL exceeds maximum length of 5 characters",
    )


def test_extract_elements_reports_error_for_invalid_sql() -> None:
    result = SQLParser("postgres").extract_elements("SELECT * FROM")
    assert set(result) == {"error"}
    assert "Expected table name" in result["error"]


def test_extract_elements_exposes_tables_columns_functions_joins_and_flags() -> None:
    sql = """
        WITH recent AS (
            SELECT user_id, SUM(amount) AS total FROM orders GROUP BY user_id
        )
        SELECT DISTINCT u.id,
               ROW_NUMBER() OVER (PARTITION BY u.id ORDER BY u.id) AS rn,
               COUNT(*)
        FROM users u
        JOIN recent r ON r.user_id = u.id
        LEFT JOIN profiles p ON p.user_id = u.id
        WHERE u.id IN (SELECT user_id FROM admins)
        GROUP BY u.id
        UNION SELECT 0
        ORDER BY 1
        LIMIT 10
    """
    elements = SQLParser("postgres").extract_elements(sql)

    assert elements["query_type"] == "UNION"
    assert {table["name"] for table in elements["tables"]} >= {
        "users",
        "recent",
        "profiles",
        "orders",
        "admins",
    }
    assert {column["name"] for column in elements["columns"]} >= {
        "id",
        "user_id",
        "amount",
    }
    assert {function["name"] for function in elements["functions"]} >= {
        "SUM",
        "ROW_NUMBER",
        "COUNT",
    }
    assert len(elements["joins"]) == 2
    assert elements["has_subquery"] is True
    assert elements["has_cte"] is True
    assert elements["has_window"] is True
    assert elements["has_aggregation"] is True
    assert elements["has_distinct"] is True
    assert elements["has_union"] is True
    assert elements["has_order_by"] is True
    assert elements["has_limit"] is True


def test_parser_deduplicates_repeated_tables_columns_and_functions() -> None:
    result = SQLParser("postgres").parse(
        "SELECT u.id, u.id, COUNT(*), COUNT(*) FROM users u "
        "JOIN users u ON u.id = u.id"
    )
    assert result.success is True, result.error
    assert result.tables == [{"name": "users", "alias": "u", "schema": None, "catalog": None}]
    assert result.columns == [{"name": "id", "table": "u", "alias": None}]
    assert result.functions == [
        {
            "name": "COUNT",
            "args_count": 1,
            "is_aggregate": True,
            "is_window": False,
        }
    ]


def test_join_extraction_covers_types_and_on_conditions() -> None:
    result = SQLParser("postgres").parse(
        "SELECT * FROM users u CROSS JOIN audit a "
        "RIGHT JOIN events e ON e.user_id = u.id"
    )
    assert result.success is True, result.error
    assert result.joins == [
        {"type": "CROSS", "table": "audit", "on_condition": None},
        {
            "type": "RIGHT OUTER",
            "table": "events",
            "on_condition": "e.user_id = u.id",
        },
    ]


@pytest.mark.parametrize(
    ("sql", "query_type"),
    [
        ("SELECT 1", "SELECT"),
        ("INSERT INTO users (id) VALUES (1)", "INSERT"),
        ("UPDATE users SET id = 2", "UPDATE"),
        ("DELETE FROM users", "DELETE"),
        ("CREATE TABLE users (id INT)", "CREATE"),
        ("DROP TABLE users", "DROP"),
        ("ALTER TABLE users ADD COLUMN name TEXT", "ALTER"),
        (
            "MERGE INTO users u USING incoming i ON u.id = i.id "
            "WHEN MATCHED THEN UPDATE SET name = i.name",
            "MERGE",
        ),
        ("SELECT 1 UNION SELECT 2", "UNION"),
    ],
)
def test_query_type_detection(sql: str, query_type: str) -> None:
    result = SQLParser("postgres").parse(sql)
    assert result.success is True, result.error
    assert result.query_type == query_type


@pytest.mark.parametrize(
    ("sql", "level"),
    [
        ("SELECT 1", "Simple"),
        ("SELECT 1 UNION SELECT 2", "Moderate"),
        (
            "SELECT u.id, COUNT(*) FROM users u "
            "JOIN orders o ON o.user_id = u.id "
            "JOIN events e ON e.user_id = u.id GROUP BY u.id",
            "Complex",
        ),
        (
            "WITH cte AS (SELECT user_id, SUM(amount) FROM orders GROUP BY user_id) "
            "SELECT DISTINCT u.id, ROW_NUMBER() OVER (ORDER BY u.id), COUNT(*) "
            "FROM users u JOIN cte c ON c.user_id = u.id "
            "LEFT JOIN profiles p ON p.user_id = u.id "
            "WHERE u.id IN (SELECT id FROM admins) GROUP BY u.id "
            "UNION SELECT 0",
            "Very Complex",
        ),
    ],
)
def test_complexity_score_levels(sql: str, level: str) -> None:
    complexity = SQLParser("postgres").get_complexity_score(sql)
    assert complexity["level"] == level
    assert complexity["score"] > 0
    assert complexity["tables_count"] >= 0


def test_complexity_score_reports_parse_error() -> None:
    complexity = SQLParser("postgres").get_complexity_score("SELECT * FROM")
    assert complexity["score"] == 0
    assert "Expected table name" in complexity["error"]

