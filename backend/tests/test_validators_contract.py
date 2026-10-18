"""Public contract coverage for :mod:`backend.utils.validators`.

These tests exercise the validators through their public functions rather than
reaching into implementation details.  The statement splitter cases complement
the dialect-specific regression tests with lexical boundary and empty-input
contracts.
"""

from __future__ import annotations

import pytest

from backend.core.exceptions import UnsupportedDialectError, ValidationError
from backend.utils.validators import (
    sanitize_column_name,
    sanitize_table_name,
    split_sql_statements,
    validate_batch_size,
    validate_dialect,
    validate_function_name,
    validate_sql,
    validate_type_name,
)


class TestBasicValidators:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [("mysql", "mysql"), (" MYSQL ", "mysql"), ("PostGreS", "postgres")],
    )
    def test_validate_dialect_normalizes_supported_values(self, value, expected):
        assert validate_dialect(value) == expected

    def test_validate_dialect_rejects_missing_and_unknown_values(self):
        with pytest.raises(ValidationError, match="dialect is required"):
            validate_dialect("")

        with pytest.raises(UnsupportedDialectError, match="Unsupported dialect"):
            validate_dialect("not-a-dialect")

    def test_validate_sql_strips_and_rejects_empty_values(self):
        assert validate_sql("  SELECT 1  ") == "SELECT 1"

        with pytest.raises(ValidationError, match="required"):
            validate_sql(None)
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_sql(" \n\t ")

    def test_validate_sql_enforces_explicit_length_limit(self):
        assert validate_sql("SELECT", max_length=6) == "SELECT"
        with pytest.raises(ValidationError, match="maximum length of 5"):
            validate_sql("SELECT", max_length=5)

    @pytest.mark.parametrize("size", [0, -1])
    def test_validate_batch_size_rejects_non_positive_values(self, size):
        with pytest.raises(ValidationError, match="must be positive"):
            validate_batch_size(size)

    def test_validate_batch_size_clamps_to_limit(self):
        assert validate_batch_size(3, max_size=10) == 3
        assert validate_batch_size(11, max_size=10) == 10

    @pytest.mark.parametrize(
        ("validator", "value", "expected"),
        [
            (validate_type_name, " varchar2(20) ", "VARCHAR2(20)"),
            (validate_function_name, " coalesce ", "COALESCE"),
        ],
    )
    def test_name_validators_normalize_values(self, validator, value, expected):
        assert validator(value) == expected

    @pytest.mark.parametrize(
        ("validator", "message"),
        [
            (validate_type_name, "Type name is required"),
            (validate_function_name, "Function name is required"),
        ],
    )
    def test_name_validators_reject_missing_values(self, validator, message):
        with pytest.raises(ValidationError, match=message):
            validator("")

    @pytest.mark.parametrize("name", ["users", "app.users", "_staging_2"])
    def test_sanitize_table_name_accepts_identifiers(self, name):
        assert sanitize_table_name(name) == name

    @pytest.mark.parametrize("name", ["", "1users", "users-name", "users;DROP"])
    def test_sanitize_table_name_rejects_invalid_identifiers(self, name):
        with pytest.raises(ValidationError, match="Table name"):
            sanitize_table_name(name)

    @pytest.mark.parametrize("name", ["id", "_created_at", "col_2"])
    def test_sanitize_column_name_accepts_identifiers(self, name):
        assert sanitize_column_name(name) == name

    @pytest.mark.parametrize("name", ["", "2id", "first-name", "users.id"])
    def test_sanitize_column_name_rejects_invalid_identifiers(self, name):
        with pytest.raises(ValidationError, match="Column name"):
            sanitize_column_name(name)


class TestSplitSqlStatementsContract:
    def test_empty_input_and_semicolon_only_input_are_empty(self):
        assert split_sql_statements("") == []
        assert split_sql_statements(" \n\t ") == []
        assert split_sql_statements(";;; ") == []

    def test_statements_without_trailing_semicolon_are_returned(self):
        assert split_sql_statements("SELECT 1") == ["SELECT 1"]
        assert split_sql_statements("SELECT 1; SELECT 2") == ["SELECT 1", "SELECT 2"]

    def test_semicolons_inside_single_and_double_quoted_values_are_preserved(self):
        sql = 'SELECT \'a;\'\'b\' AS text, "a;b" AS identifier; SELECT 2;'
        assert split_sql_statements(sql) == [
            'SELECT \'a;\'\'b\' AS text, "a;b" AS identifier',
            "SELECT 2",
        ]

    def test_semicolons_inside_backticks_are_preserved(self):
        sql = "SELECT `a;b` FROM t; SELECT 2"
        assert split_sql_statements(sql, dialect="mysql") == [
            "SELECT `a;b` FROM t",
            "SELECT 2",
        ]

    def test_semicolons_inside_line_and_block_comments_are_preserved(self):
        sql = "SELECT 1 -- comment; remains\n; /* block; comment */ SELECT 2;"
        assert split_sql_statements(sql) == [
            "SELECT 1 -- comment; remains",
            "/* block; comment */ SELECT 2",
        ]

    @pytest.mark.parametrize(
        "quoted",
        [
            "$$body; SELECT 1$$",
            "$tag$body; SELECT 1$tag$",
        ],
    )
    def test_postgres_dollar_quoted_strings_do_not_split(self, quoted):
        sql = f"SELECT {quoted}; SELECT 2;"
        assert split_sql_statements(sql, dialect="postgres") == [
            f"SELECT {quoted}",
            "SELECT 2",
        ]

    def test_tsql_go_is_a_standalone_batch_separator(self):
        sql = "SELECT 1;\nGO\nSELECT 2\nGO 2\nSELECT 3"
        assert split_sql_statements(sql, dialect="tsql") == [
            "SELECT 1",
            "SELECT 2",
            "SELECT 3",
        ]

    def test_tsql_go_inside_string_or_mixed_line_is_not_a_separator(self):
        sql = "SELECT 'GO;';\nSELECT 1 GO SELECT 2"
        assert split_sql_statements(sql, dialect="tsql") == [
            "SELECT 'GO;'",
            "SELECT 1 GO SELECT 2",
        ]

    def test_oracle_plsql_begin_end_and_nested_control_blocks_are_one_statement(self):
        sql = (
            "BEGIN\n"
            "  IF enabled THEN\n"
            "    x := CASE WHEN flag THEN 1 ELSE 2 END;\n"
            "  END IF;\n"
            "  LOOP\n"
            "    NULL;\n"
            "    EXIT;\n"
            "  END LOOP;\n"
            "END;\n"
            "SELECT 1;"
        )
        result = split_sql_statements(sql, dialect="oracle")
        assert result == [
            "BEGIN\n"
            "  IF enabled THEN\n"
            "    x := CASE WHEN flag THEN 1 ELSE 2 END;\n"
            "  END IF;\n"
            "  LOOP\n"
            "    NULL;\n"
            "    EXIT;\n"
            "  END LOOP;\n"
            "END",
            "SELECT 1",
        ]

    def test_oracle_case_in_plain_select_does_not_swallow_terminator(self):
        sql = "SELECT CASE WHEN x = 1 THEN 'a' ELSE 'b' END FROM t; SELECT 2;"
        assert split_sql_statements(sql, dialect="oracle") == [
            "SELECT CASE WHEN x = 1 THEN 'a' ELSE 'b' END FROM t",
            "SELECT 2",
        ]

    def test_unterminated_quote_and_comment_are_conservative(self):
        quote = "SELECT 'unterminated; SELECT 2"
        comment = "SELECT 1; /* unterminated; SELECT 2"
        assert split_sql_statements(quote) == [quote]
        assert split_sql_statements(comment) == [
            "SELECT 1",
            "/* unterminated; SELECT 2",
        ]

