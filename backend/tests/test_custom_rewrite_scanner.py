import pytest

from backend.core.post_processor import PostProcessor


@pytest.mark.parametrize(
    "method, sql, expected_token, forbidden_literal",
    [
        (
            "_convert_decode_to_case",
            "SELECT DECODE(status, 1, 'ok', 0, 'no'), 'DECODE(fake, 1, 2)' FROM t",
            "CASE WHEN status = 1 THEN 'ok' WHEN status = 0 THEN 'no' ELSE NULL END",
            "'DECODE(fake, 1, 2)'",
        ),
        (
            "_convert_mysql_date_format",
            "SELECT DATE_FORMAT(created_at, '%Y-%m-%d') FROM t /* DATE_FORMAT(fake, '%Y') */",
            "TO_CHAR(created_at, 'YYYY-MM-DD')",
            "DATE_FORMAT(fake, '%Y')",
        ),
        (
            "_convert_postgres_to_char",
            "SELECT TO_CHAR(created_at, 'YYYY-MM-DD') FROM t /* TO_CHAR(fake, 'YYYY') */",
            "DATE_FORMAT(created_at, '%Y-%m-%d')",
            "TO_CHAR(fake, 'YYYY')",
        ),
        (
            "_convert_top_to_limit",
            "SELECT TOP 10 id FROM t WHERE note = 'TOP 99' -- TOP 88\n",
            "SELECT id FROM t WHERE note = 'TOP 99' -- TOP 88\n LIMIT 10",
            "TOP 99",
        ),
        (
            "_convert_rownum_to_limit",
            "SELECT * FROM t WHERE ROWNUM <= 10 AND note = 'ROWNUM <= 99' /* ROWNUM <= 88 */",
            "LIMIT 10",
            "ROWNUM <= 99",
        ),
        (
            "_fix_group_concat_default_separator",
            "SELECT GROUP_CONCAT(name), 'GROUP_CONCAT(fake)' FROM t",
            "STRING_AGG(name::TEXT, ',')",
            "GROUP_CONCAT(fake)",
        ),
    ],
)
def test_custom_rewrite_only_touches_executable_sql(method, sql, expected_token, forbidden_literal):
    processor = PostProcessor()
    result, notes = getattr(processor, method)(sql)
    assert expected_token in result
    assert forbidden_literal in result
    assert notes


def test_decode_scanner_handles_nested_calls_and_quoted_commas():
    processor = PostProcessor()
    sql = "SELECT DECODE(COALESCE(a, func(b, c)), 1, 'x,y', 0, 'z') FROM t"
    result, _ = processor._convert_decode_to_case(sql)
    assert result == "SELECT CASE WHEN COALESCE(a, func(b, c)) = 1 THEN 'x,y' WHEN COALESCE(a, func(b, c)) = 0 THEN 'z' ELSE NULL END FROM t"
