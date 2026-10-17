"""Regression tests for lexical fallbacks and scanner-backed JSON rewrites.

After the P5 audit, the one genuinely high-risk semantic rule that is the
*solo* mechanism (``clickhouse_array_join_to_postgres``) was migrated to an
AST transform in :mod:`backend.core.transpiler` and removed from the rule
engine (see :mod:`backend.tests.test_array_join_ast`).

The remaining ``LEGACY_REGEX`` rules below are retained as simple lexical
rewrites because the authoritative target output is already produced by
``sqlglot``'s native transpile path for every dialect pair they cover.
The JSON rules that previously used unsafe argument regexes now use the same
scanner-backed path as the other structural rules.  This file locks both
contracts:

* each rule's pure-regex ``apply()`` still produces the expected lexical
  rewrite (so a future regex bug is caught even though the pipeline no
  longer depends on it);
* literal/comment boundaries are not crossed;
* the full production pipeline yields the authoritative sqlglot output,
  with a valid ``target_validation_state``.
"""
import pytest
import sqlglot

from backend.core.rules import RuleSafety, TRANSFORM_RULES


def _rule(name: str):
    for rule in TRANSFORM_RULES:
        if rule.name == name:
            return rule
    raise AssertionError(f"Missing rule: {name}")


def _is_legacy(rule_name: str) -> bool:
    return _rule(rule_name).safety == RuleSafety.LEGACY_REGEX


class TestLexicalApplyContract:
    """Each retained LEGACY_REGEX rule still performs its documented rewrite
    when applied in isolation (regex apply()), which is what the rule engine
    exercises.  These lock the lexical behavior independent of the pipeline."""

    def test_getdate_tsql_to_mysql(self):
        assert _is_legacy("tsql_getdate_to_mysql")
        out, applied = _rule("tsql_getdate_to_mysql").apply("SELECT GETDATE() FROM t")
        assert applied
        assert out == "SELECT NOW() FROM t"

    def test_getdate_tsql_to_postgres(self):
        assert _is_legacy("tsql_getdate_to_postgres")
        out, applied = _rule("tsql_getdate_to_postgres").apply("SELECT GETDATE() FROM t")
        assert applied
        assert out == "SELECT CURRENT_TIMESTAMP FROM t"

    def test_now_mysql_to_oracle(self):
        assert _is_legacy("mysql_now_to_oracle")
        out, applied = _rule("mysql_now_to_oracle").apply("SELECT NOW() FROM t")
        assert applied
        assert out == "SELECT SYSDATE FROM t"

    def test_unix_timestamp_hive_to_postgres(self):
        assert _is_legacy("hive_unix_timestamp_to_postgres")
        out, applied = _rule("hive_unix_timestamp_to_postgres").apply("SELECT UNIX_TIMESTAMP() FROM t")
        assert applied
        assert "EXTRACT(EPOCH FROM CURRENT_TIMESTAMP)::BIGINT" in out

    def test_limit_offset_mysql_to_postgres(self):
        assert _is_legacy("mysql_limit_offset_to_postgres")
        out, applied = _rule("mysql_limit_offset_to_postgres").apply("SELECT a FROM t LIMIT 10, 5")
        assert applied
        assert out == "SELECT a FROM t LIMIT 5 OFFSET 10"

    def test_json_extract_mysql_to_postgres(self):
        # Scanner-backed replacement consumes the complete call, including
        # the quoted path argument, without crossing lexical boundaries.
        assert not _is_legacy("mysql_json_extract_to_postgres")
        out, applied = _rule("mysql_json_extract_to_postgres").apply(
            "SELECT JSON_EXTRACT(payload, '$.name') FROM t"
        )
        assert applied
        assert out == "SELECT payload->>'name' FROM t"

    def test_json_extract_rule_matches_within_single_segment(self):
        assert not _is_legacy("mysql_json_extract_to_postgres")
        out, applied = _rule("mysql_json_extract_to_postgres").apply(
            "SELECT JSON_EXTRACT(COALESCE(payload, fallback), '$.a.b.c')"
        )
        assert applied
        assert out == "SELECT COALESCE(payload, fallback)->'a'->'b'->>'c'"

    def test_parse_json_snowflake_to_postgres(self):
        assert not _is_legacy("snowflake_parse_json_to_postgres")
        out, applied = _rule("snowflake_parse_json_to_postgres").apply(
            "SELECT PARSE_JSON(COALESCE(a, b)) FROM t"
        )
        assert applied
        assert out == "SELECT COALESCE(a, b)::JSONB FROM t"

    def test_substr_nested_arguments_only_change_function_name(self):
        rule = _rule("oracle_substr_to_mysql")
        out, applied = rule.apply(
            "SELECT SUBSTR(COALESCE(value, fallback), 1, COALESCE(2, 3)) FROM t"
        )
        assert applied
        assert out == "SELECT SUBSTRING(COALESCE(value, fallback), 1, COALESCE(2, 3)) FROM t"

    def test_array_length_postgres_to_hive(self):
        assert _is_legacy("postgres_array_length_to_hive")
        out, applied = _rule("postgres_array_length_to_hive").apply("SELECT ARRAY_LENGTH(arr, 1) FROM t")
        assert applied
        assert out == "SELECT SIZE(arr) FROM t"

    def test_legacy_literal_boundary_getdate(self):
        """GETDATE inside a string literal must not be rewritten."""
        out, applied = _rule("tsql_getdate_to_postgres").apply("SELECT 'GETDATE()' AS label FROM t")
        assert not applied or "GETDATE()" in out, f"literal was mutated: {out!r}"

    def test_legacy_literal_boundary_parse_json(self):
        """PARSE_JSON inside a string literal must not be rewritten."""
        out, applied = _rule("snowflake_parse_json_to_postgres").apply(
            "SELECT 'PARSE_JSON(col)' AS label FROM t"
        )
        assert "PARSE_JSON(col)" in out, f"literal was mutated: {out!r}"


class TestProductionPipelineContract:
    """End-to-end: the production pipeline for these dialect pairs must yield
    the authoritative sqlglot output and a valid target state.  The retained
    lexical rules do not change this result; this locks that guarantee."""

    @classmethod
    def setup_class(cls):
        from backend.core.transpiler import SQLTranspiler
        cls.t = SQLTranspiler()

    @pytest.mark.parametrize(
        ("sql", "source", "target", "must_contain"),
        [
            ("SELECT GETDATE() FROM t", "tsql", "mysql", "CURRENT_TIMESTAMP"),
            ("SELECT GETDATE() FROM t", "tsql", "postgres", "CURRENT_TIMESTAMP"),
            ("SELECT NOW() FROM t", "mysql", "oracle", "SYSDATE"),
            ("SELECT UNIX_TIMESTAMP() FROM t", "hive", "postgres", "CURRENT_TIMESTAMP"),
            ("SELECT a FROM t LIMIT 10, 5", "mysql", "postgres", "OFFSET 10"),
            ("SELECT JSON_EXTRACT(payload, '$.name') FROM t", "mysql", "postgres", "JSON_EXTRACT_PATH"),
            ("SELECT PARSE_JSON(col) FROM t", "snowflake", "postgres", "JSON"),
            ("SELECT ARRAY_LENGTH(arr, 1) FROM t", "postgres", "hive", "SIZE"),
        ],
    )
    def test_pipeline_output_valid(self, sql, source, target, must_contain):
        result = self.t.transpile(sql, source=source, target=target, pretty=False, validate=True)
        assert result.success is True, result.error
        assert result.target_validation_state in ("target_valid", "generic_only")
        assert must_contain in result.target_sql, f"expected {must_contain!r} in {result.target_sql!r}"

    def test_limit_offset_native_is_authoritative(self):
        """sqlglot natively rewrites MySQL LIMIT offset,count; confirm the
        rule-engine path agrees (no drift between the two mechanisms)."""
        result = self.t.transpile("SELECT a FROM t LIMIT 10, 5", source="mysql", target="postgres",
                                 pretty=False, validate=True)
        assert result.success
        # Either the rule-engine or native path must produce LIMIT 5 OFFSET 10.
        assert "LIMIT 5 OFFSET 10" in result.target_sql

    def test_parse_json_native_cast_is_valid_postgres(self):
        """Native snowflake→postgres produces a JSON cast; the retained lexical
        ``::JSONB`` rule must not corrupt it.  The target must parse."""
        result = self.t.transpile(
            "SELECT PARSE_JSON(col) FROM t", source="snowflake", target="postgres",
            pretty=False, validate=True,
        )
        assert result.success
        # Output must be valid postgres regardless of which cast form won.
        sqlglot.parse_one(result.target_sql, read="postgres")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
