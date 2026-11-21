import pytest

from backend.core.nl2sql_pipeline.clause_extract import (
    check_distinct,
    extract_group_by,
    extract_limit,
    extract_ordering,
)
from backend.core.nl2sql_pipeline.suggestions import generate_suggestions
from backend.core.nl2sql_pipeline.validation import validate_sql


@pytest.mark.parametrize(
    ("sql", "dialect", "adjustment"),
    [
        ("  -- no query\n  ", "postgres", 0.0),
        ("-- preview\nSELECT id FROM users", "postgres", 0.15),
        ("SELECT :1 FROM dual", "oracle", 0.15),
        ("SELECT 'literal :1' FROM", "oracle", -0.2),
        ("SELECT :1 FROM", "oracle", -0.2),
        ("SELECT 1", "unknown_dialect", -0.2),
    ],
    ids=["comments-only", "valid", "bind-fallback", "quoted-bind", "invalid-after-fallback", "unknown-dialect"],
)
def test_sql_validation_confidence(sql: str, dialect: str, adjustment: float) -> None:
    assert validate_sql(sql, dialect) == adjustment


@pytest.mark.parametrize(
    ("term", "expected"),
    [("date", ["date"]), ("month", ["MONTH(date)"]), ("year", ["YEAR(date)"]), ("orders", [])],
)
def test_group_by_fallback_with_supplied_vocabulary(term: str, expected: list[str]) -> None:
    assert extract_group_by(
        f"count events per {term}",
        column_patterns={"status": "status"},
        table_patterns={term: term},
    ) == expected


def test_group_by_ignores_unrecognized_labels_and_uses_later_clause() -> None:
    assert extract_group_by("count events group by unknown per user") == ["user_id"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [("lowest price", ("price", "ASC")), ("lowest", ("amount", "ASC"))],
)
def test_ordering_lowest_is_ascending(text: str, expected: tuple[str, str]) -> None:
    assert extract_ordering(text) == expected


def test_quoted_and_commented_clause_keywords_are_ignored() -> None:
    text = "show orders where status is 'distinct group by status order by id top 4' -- only 9"
    assert extract_group_by(text) == []
    assert extract_ordering(text) is None
    assert extract_limit(text) is None
    assert check_distinct(text) is False


def test_executable_limit_and_distinct_are_recognized() -> None:
    text = "show distinct orders where status is 'top 4' limit 1000000"
    assert extract_limit(text) == 1_000_000
    assert check_distinct(text) is True


@pytest.mark.parametrize(
    ("text", "sql", "dialect", "expected"),
    [
        ("show users", "SELECT id FROM users", "postgres", []),
        ("find by id", "SELECT id FROM users WHERE id = ?", "postgres", ["💡 请替换 ? 占位符为实际值"]),
        ("delete users", "DELETE FROM users", "postgres", ["⚠️ DELETE 没有 WHERE 条件将删除所有数据！"]),
        ("update users", "UPDATE users SET active = 0", "postgres", ["⚠️ UPDATE 没有 WHERE 条件将更新所有数据！"]),
        ("sort users", "SELECT id FROM users ORDER BY id", "hive", ["💡 Hive 中 ORDER BY 建议配合 LIMIT 使用"]),
        ("sort users", "SELECT id FROM users ORDER BY id LIMIT 4", "hive", []),
    ],
    ids=["none", "placeholder", "unfiltered-delete", "unfiltered-update", "hive-sort", "bounded-hive-sort"],
)
def test_sql_suggestions(text: str, sql: str, dialect: str, expected: list[str]) -> None:
    assert generate_suggestions(text, sql, dialect) == expected
