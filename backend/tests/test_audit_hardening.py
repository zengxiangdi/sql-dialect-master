import sqlglot
from sqlglot import exp

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.post_processor import PostProcessor
from backend.core.transpiler import SQLTranspiler


def test_english_inclusive_comparison_preserves_gte():
    result = NL2SQLGenerator().generate("find products with price greater than or equal to 10", "postgres")
    assert result.success
    where = sqlglot.parse_one(result.sql, read="postgres").find(exp.Where)
    assert where is not None
    assert len(list(where.this.find_all(exp.GTE))) == 1
    assert len(list(where.this.find_all(exp.GT))) == 0


def test_english_inclusive_comparison_preserves_lte():
    result = NL2SQLGenerator().generate("find products with price less than or equal to 10", "postgres")
    assert result.success
    where = sqlglot.parse_one(result.sql, read="postgres").find(exp.Where)
    assert where is not None
    assert len(list(where.this.find_all(exp.LTE))) == 1
    assert len(list(where.this.find_all(exp.LT))) == 0


def test_simple_rownum_is_converted_to_limit():
    processed, notes = PostProcessor().process(
        "SELECT * FROM users WHERE status = 'ACTIVE' AND ROWNUM <= 10",
        "oracle",
        "postgres",
    )
    assert "LIMIT 10" in processed
    assert "ROWNUM" not in processed
    assert any("ROWNUM <= 10" in note for note in notes)


def test_rownum_with_order_by_is_not_silently_rewritten():
    sql = "SELECT * FROM users WHERE ROWNUM <= 10 ORDER BY created_at DESC"
    processed, notes = PostProcessor().process(sql, "oracle", "postgres")
    assert "ROWNUM <= 10" in processed
    assert "LIMIT 10" not in processed
    assert any("not provably LIMIT-equivalent" in note for note in notes)


def test_rownum_or_predicate_is_not_silently_rewritten():
    sql = "SELECT * FROM users WHERE status = 'ACTIVE' OR ROWNUM <= 10"
    processed, notes = PostProcessor().process(sql, "oracle", "postgres")
    assert "ROWNUM <= 10" in processed
    assert "LIMIT 10" not in processed
    assert any("not provably LIMIT-equivalent" in note for note in notes)


def test_security_ignores_strings_and_comments():
    result = SQLTranspiler()._validate_security(
        "SELECT 'DROP TABLE users', 'OR 1=1', 'SLEEP(10)' /* UNION SELECT information_schema.tables */"
    )
    assert result["blocked"] is False
    assert result["warnings"] == []


def test_security_ignores_postgres_dollar_quoted_strings():
    result = SQLTranspiler()._validate_security(
        "SELECT $$DROP TABLE users; OR 1=1 SLEEP(10)$$ AS body"
    )
    assert result["blocked"] is False
    assert result["warnings"] == []


def test_security_ignores_postgres_tagged_dollar_quoted_strings():
    result = SQLTranspiler()._validate_security(
        "SELECT $payload$UNION SELECT information_schema.tables$payload$ AS body"
    )
    assert result["blocked"] is False
    assert result["warnings"] == []


def test_security_ignores_oracle_q_quoted_strings():
    result = SQLTranspiler()._validate_security(
        "SELECT q'[DROP TABLE users; OR 1=1]' AS body"
    )
    assert result["blocked"] is False
    assert result["warnings"] == []


def test_dialect_rewrite_ignores_dollar_quoted_strings():
    generator = NL2SQLGenerator()
    adjusted = generator._apply_dialect_adjustments(
        "SELECT $$CURRENT_DATE DATE_SUB(CURRENT_DATE, 7)$$, CURRENT_DATE",
        "oracle",
    )
    assert "$$CURRENT_DATE DATE_SUB(CURRENT_DATE, 7)$$" in adjusted
    assert "TRUNC(SYSDATE)" in adjusted


def test_security_detects_update_without_where_using_ast():
    result = SQLTranspiler()._validate_security("UPDATE users SET name = 'x'")
    assert any("UPDATE without WHERE" in warning for warning in result["warnings"])


def test_security_does_not_flag_update_with_where():
    result = SQLTranspiler()._validate_security("UPDATE users SET name = 'x' WHERE id = 1")
    assert not any("UPDATE without WHERE" in warning for warning in result["warnings"])


def test_warning_keywords_ignore_literals():
    warnings = SQLTranspiler()._generate_warnings(
        "SELECT 'SELECT * FROM users JOIN orders' AS message", "mysql", "postgres"
    )
    assert warnings == []


def test_group_concat_nested_expression_is_converted():
    processed, _ = PostProcessor().process(
        "SELECT GROUP_CONCAT(CONCAT(first_name, last_name) SEPARATOR ';') FROM users",
        "mysql",
        "postgres",
    )
    assert "STRING_AGG" in processed
    assert ";" in processed
    assert "CONCAT(first_name, last_name)" in processed


def test_group_concat_distinct_and_order_by_are_preserved():
    processed, _ = PostProcessor().process(
        "SELECT GROUP_CONCAT(DISTINCT name ORDER BY name SEPARATOR ',') FROM users",
        "mysql",
        "postgres",
    )
    assert "STRING_AGG(DISTINCT (name)::TEXT, ',' ORDER BY name)" in processed


def test_nl2sql_date_rewrite_does_not_modify_string_literal():
    generator = NL2SQLGenerator()
    sql = "SELECT 'CURRENT_DATE', CURRENT_DATE"
    adjusted = generator._apply_dialect_adjustments(sql, "oracle")
    assert "'CURRENT_DATE'" in adjusted
    assert "TRUNC(SYSDATE)" in adjusted
