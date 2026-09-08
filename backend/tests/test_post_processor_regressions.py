from backend.core.post_processor import PostProcessor


def test_decode_handles_nested_function_arguments():
    processor = PostProcessor()
    sql = "SELECT DECODE(status, COALESCE(active_status, fallback_status), 'active', 'inactive') FROM users"

    result, notes = processor._convert_decode_to_case(sql)

    assert "COALESCE(active_status, fallback_status)" in result
    assert "WHEN status = COALESCE(active_status, fallback_status) THEN 'active'" in result
    assert result.endswith("ELSE 'inactive' END FROM users")
    assert notes == ["Converted DECODE to CASE WHEN"]


def test_mysql_date_format_handles_nested_expression_with_comma():
    processor = PostProcessor()
    sql = "SELECT DATE_FORMAT(COALESCE(created_at, updated_at), '%Y-%m-%d') FROM users"

    result, notes = processor._convert_mysql_date_format(sql)

    assert result == "SELECT TO_CHAR(COALESCE(created_at, updated_at), 'YYYY-MM-DD') FROM users"
    assert notes == ["Converted DATE_FORMAT to TO_CHAR"]


def test_postgres_to_char_handles_nested_expression_with_comma():
    processor = PostProcessor()
    sql = "SELECT TO_CHAR(COALESCE(created_at, updated_at), 'YYYY-MM-DD') FROM users"

    result, notes = processor._convert_postgres_to_char(sql)

    assert result == "SELECT DATE_FORMAT(COALESCE(created_at, updated_at), '%Y-%m-%d') FROM users"
    assert notes == ["Converted TO_CHAR to DATE_FORMAT"]
