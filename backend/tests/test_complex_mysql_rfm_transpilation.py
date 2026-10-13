"""Regression coverage for a realistic MySQL CTE/window/rollup report.

This fixture intentionally combines constructs that are easy for a generic
``sqlglot`` parse to accept while still being executable only in the source
dialect: interval arithmetic, date differences, JSON aggregation, and
``WITH ROLLUP``.  The transpiler must normalize the constructs it can
represent in a target dialect, or report the conversion as incompatible.  A
successful generic parse alone is not sufficient evidence of target
correctness.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.core.transpiler import SQLTranspiler

FIXTURE = Path(__file__).resolve().parent / "data" / "complex_mysql_rfm.sql"
MYSQL_RFM_SQL = FIXTURE.read_text(encoding="utf-8")
DATE_WINDOW_SQL = "SELECT DATE_SUB(a.today, INTERVAL 24 MONTH) AS cutoff FROM anchor AS a"
ROLLUP_SQL = "SELECT category_name, SUM(net_amount) FROM cat_top3 GROUP BY category_name WITH ROLLUP"
ORACLE_DATES_SQL = (
    "SELECT DATE_SUB(a.today, INTERVAL 24 MONTH) AS cutoff, "
    "DATEDIFF((SELECT today FROM anchor), MAX(last_buy_date)) AS recency_days "
    "FROM cust_cat AS cc CROSS JOIN anchor AS a"
)
TSQL_CONCAT_SQL = "SELECT CONCAT(r_score, '-', f_score, '-', m_score) AS rfm FROM cust_seg"
SNOWFLAKE_DATE_FORMAT_SQL = "SELECT DATE_FORMAT(last_buy_date, '%Y-%m-%d') FROM cust_cat"
TARGETS = (
    "hive",
    "oracle",
    "tsql",
    "postgres",
    "spark",
    "trino",
    "snowflake",
    "redshift",
    "clickhouse",
    "duckdb",
    "databricks",
)


@pytest.fixture(scope="module")
def transpiler() -> SQLTranspiler:
    return SQLTranspiler()


@pytest.mark.parametrize("target", TARGETS)
def test_complex_mysql_fixture_transpiles_or_reports_target_issue(transpiler, target):
    """The full query must never be rejected as multiple/empty SQL.

    Some target engines do not have a faithful equivalent for the JSON
    aggregate in this report.  Those conversions may be reported as a
    target incompatibility, but a result marked ``target_valid`` must still
    be a real target-dialect result (the focused tests below enforce the
    date/rollup invariants).
    """

    result = transpiler.transpile(MYSQL_RFM_SQL, "mysql", target, pretty=False)

    assert result.error not in {
        "Empty SQL statement",
        "Multiple SQL statements are not supported; submit one statement per request",
    }
    if result.success:
        assert result.target_sql
        assert result.target_validation_state in {"target_valid", "generic_only"}
    else:
        assert result.error


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("hive", r"ADD_MONTHS\(a\.today,\s*-24\)"),
        ("spark", r"ADD_MONTHS\(a\.today,\s*-24\)"),
        ("databricks", r"ADD_MONTHS\(a\.today,\s*-24\)"),
        ("postgres", r"a\.today\s*-\s*INTERVAL\s+'24 MONTH'"),
        ("redshift", r"a\.today\s*-\s*INTERVAL\s+'24 MONTH'"),
        ("duckdb", r"a\.today\s*-\s*INTERVAL\s+'24'\s+MONTH"),
        ("trino", r"DATE_ADD\('MONTH',\s*[^,]+,\s*a\.today\)"),
        ("snowflake", r"DATEADD\(MONTH,\s*[^,]+,\s*a\.today\)"),
        ("oracle", r"ADD_MONTHS\(a\.today,\s*-24\)"),
        ("tsql", r"DATEADD\(MONTH,\s*-24,\s*a\.today\)"),
        ("clickhouse", r"(?:subtractMonths|dateSub)\(a\.today,\s*24\)"),
    ],
)
def test_complex_fixture_preserves_24_month_window_for_target(
    transpiler, target, expected
):
    """MySQL DATE_SUB(... INTERVAL 24 MONTH) must retain month semantics."""

    result = transpiler.transpile(DATE_WINDOW_SQL, "mysql", target, pretty=False)
    assert result.success, result.error
    assert result.target_sql
    assert re.search(expected, result.target_sql, flags=re.IGNORECASE), (
        f"{target} output lost the 24-month window: {result.target_sql}"
    )
    # A target result must never carry the MySQL three-argument DATE_SUB form.
    if target != "hive" and target != "spark" and target != "databricks":
        assert not re.search(r"\bDATE_SUB\s*\(", result.target_sql, re.IGNORECASE)


@pytest.mark.parametrize(
    "target",
    (
        "oracle",
        "tsql",
        "postgres",
        "spark",
        "trino",
        "snowflake",
        "redshift",
        "duckdb",
        "databricks",
    ),
)
def test_complex_fixture_does_not_leave_mysql_with_rollup_syntax(
    transpiler, target
):
    """Targets without MySQL's ``WITH ROLLUP`` need ``ROLLUP(...)`` syntax.

    Hive and ClickHouse also accept ``WITH ROLLUP`` in supported server
    versions, so they are intentionally excluded from this guard.
    """

    result = transpiler.transpile(ROLLUP_SQL, "mysql", target, pretty=False)
    if not result.success:
        # A target that cannot represent MySQL rollup semantics may fail
        # closed.  The bug is claiming success while returning the source
        # modifier unchanged.
        assert result.error
        return
    assert result.target_sql
    assert not re.search(r"\bWITH\s+ROLLUP\b", result.target_sql, re.IGNORECASE)


def test_complex_fixture_oracle_uses_target_date_functions(transpiler):
    result = transpiler.transpile(ORACLE_DATES_SQL, "mysql", "oracle", pretty=False)
    assert result.success, result.error
    assert result.target_sql
    assert not re.search(r"\b(?:DATE_SUB|DATEDIFF)\s*\(", result.target_sql, re.IGNORECASE)


def test_complex_fixture_tsql_avoids_integer_plus_string_rfm_concat(transpiler):
    result = transpiler.transpile(TSQL_CONCAT_SQL, "mysql", "tsql", pretty=False)
    assert result.success, result.error
    assert result.target_sql
    # SQL Server's `+` would attempt numeric conversion for the NTILE scores.
    assert not re.search(
        r"r_score\s*\+\s*['\"]-['\"]", result.target_sql, re.IGNORECASE
    )


def test_complex_fixture_snowflake_uses_unambiguous_date_format(transpiler):
    result = transpiler.transpile(SNOWFLAKE_DATE_FORMAT_SQL, "mysql", "snowflake", pretty=False)
    assert result.success, result.error
    assert result.target_sql
    assert "'YYYY-MM-DD'" in result.target_sql
    assert "'yyyy-mm-DD'" not in result.target_sql


@pytest.mark.parametrize(
    ("target", "required"),
    [
        ("hive", "TO_JSON(COLLECT_LIST(NAMED_STRUCT("),
        ("spark", "TO_JSON(COLLECT_LIST(NAMED_STRUCT("),
        ("databricks", "TO_JSON(COLLECT_LIST(NAMED_STRUCT("),
        ("postgres", "JSON_AGG(JSON_BUILD_OBJECT("),
        ("duckdb", "JSON_GROUP_ARRAY(JSON_OBJECT("),
        ("snowflake", "ARRAY_AGG(OBJECT_CONSTRUCT_KEEP_NULL("),
        ("trino", "JSON_FORMAT(CAST(ARRAY_AGG(JSON_OBJECT("),
    ],
)
def test_complex_fixture_json_aggregate_uses_target_expression(
    transpiler, target, required
):
    """JSON_ARRAYAGG(JSON_OBJECT(...)) must not silently remain generic."""

    result = transpiler.transpile(MYSQL_RFM_SQL, "mysql", target, pretty=False)
    if target == "clickhouse" and not result.success:
        # Mixed JSON values cannot be represented by a ClickHouse map without
        # an explicit schema/cast; refusing the conversion is the safe result.
        assert result.error
        return
    assert result.success, result.error
    assert result.target_sql
    assert required.lower() in result.target_sql.lower()


@pytest.mark.parametrize("target", ("oracle", "trino"))
def test_complex_fixture_json_object_uses_value_pairs(transpiler, target):
    """Oracle/Trino JSON_OBJECT syntax uses KEY/VALUE pairs, not ``key: value``."""

    result = transpiler.transpile(MYSQL_RFM_SQL, "mysql", target, pretty=False)
    if not result.success:
        # Oracle/Trino may reject the generic JSON object when no portable
        # expression-level representation is available.
        assert result.error
        return
    assert result.target_sql
    assert "'customer_id':" not in result.target_sql
    assert re.search(r"'customer_id'\s+(?:KEY\s+)?VALUE\s+", result.target_sql, re.IGNORECASE)


@pytest.mark.parametrize("target", ("oracle", "trino"))
def test_json_value_colons_are_not_treated_as_pair_separators(transpiler, target):
    """A colon inside a JSON string value must survive target rewriting."""

    sql = "SELECT JSON_ARRAYAGG(JSON_OBJECT('url', 'http://x:y')) FROM events"
    result = transpiler.transpile(sql, "mysql", target, pretty=False)
    assert result.success, result.error
    assert result.target_sql
    assert "http://x:y" in result.target_sql
    assert "'url' VALUE 'http://x:y'" in result.target_sql or "KEY 'url' VALUE 'http://x:y'" in result.target_sql


def test_complex_fixture_clickhouse_json_values_are_type_safe(transpiler):
    """ClickHouse maps cannot mix numeric, date, and string value types."""

    result = transpiler.transpile(MYSQL_RFM_SQL, "mysql", "clickhouse", pretty=False)
    if not result.success:
        assert result.error
        return
    assert result.target_sql
    # A raw heterogeneous map is accepted by sqlglot but rejected by
    # ClickHouse's type inference at execution time.
    assert "map('customer_id', t.customer_id" not in result.target_sql


@pytest.mark.parametrize("target", ("postgres", "redshift", "duckdb"))
def test_complex_fixture_rfm_concat_does_not_pipe_integers_to_text(
    transpiler, target
):
    """Numeric NTILE scores need explicit text conversion before concatenation."""

    result = transpiler.transpile(MYSQL_RFM_SQL, "mysql", target, pretty=False)
    if not result.success:
        assert result.error
        return
    assert result.target_sql
    assert not re.search(
        r"(?:seg\.)?r_score\s*\|\|\s*['\"]-['\"]",
        result.target_sql,
        re.IGNORECASE,
    )
