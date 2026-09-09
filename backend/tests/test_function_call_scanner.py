from backend.core.post_processor import PostProcessor


def test_function_scanner_ignores_literals_and_comments():
    processor = PostProcessor()
    sql = "SELECT DECODE(x, 1, 'DECODE(ignored)', 0) AS v, 'DECODE(fake)' AS literal -- DECODE(fake)\n"

    result = processor._replace_function_calls(
        sql,
        "DECODE",
        lambda args, original: f"REPLACED({args})",
    )

    assert "REPLACED(x, 1, 'DECODE(ignored)', 0)" in result
    assert "'DECODE(fake)'" in result
    assert "-- DECODE(fake)" in result


def test_function_scanner_ignores_dollar_quoted_strings():
    processor = PostProcessor()
    sql = "SELECT $tag$ DECODE(fake(1)) $tag$, DECODE(x, 1, 2)"

    result = processor._replace_function_calls(
        sql,
        "DECODE",
        lambda args, original: f"REPLACED({args})",
    )

    assert "$tag$ DECODE(fake(1)) $tag$" in result
    assert result.endswith("REPLACED(x, 1, 2)")


def test_function_scanner_handles_nested_parentheses():
    processor = PostProcessor()
    sql = "SELECT DECODE(COALESCE(a, func(b, c)), 1, ABS(x), 0)"

    result = processor._replace_function_calls(
        sql,
        "DECODE",
        lambda args, original: f"REPLACED({args})",
    )

    assert result == "SELECT REPLACED(COALESCE(a, func(b, c)), 1, ABS(x), 0)"
