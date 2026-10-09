"""B1 — NL2SQL 语义正确性修复（批次 1）。

每个缺陷一个独立回归测试，全部走公开入口
``backend.core.nl2sql.NL2SQLGenerator``，结构断言用 sqlglot 解析，
不靠关键词或 golden 快照。

缺陷（复现见各测试 docstring）：

* B1-1 — 聚合列被 ``COLUMN_PATTERNS`` 首个命中（"age" 是 "average" 的
  子串）劫持：``calculate average price for products grouped by
  category`` 生成 ``AVG(age)`` 而不是 ``AVG(price)``。
* B1-2 — 英语复数时间范围丢失单位：``last 3 weeks`` / ``last 2
  months`` / ``last 1 year`` 全部被解释/执行成"天"（explanation 写
  查询最近N天数据，SQL 却按天/月/年各走一套）。
* B1-3 — Top-N + 过滤条件：WHERE 被排在 ORDER BY / LIMIT 之后，
  生成不可解析 SQL（``LIMIT 10\\nWHERE ...``）。
* B1-4 — 多个已知关系组合：两个 EXISTS 子句被渲染成两条独立的
  WHERE（``... WHERE EXISTS (...)\\nWHERE EXISTS (...)``），
  不可解析。
* B1-5 — 中文关系意图（有/没有 + 关系表）被普通 select 模板捕获，
  静默丢掉了关系，返回单表 SQL；未知关系对（供应商⟷订单）同样
  静默降级而不是失败关闭。

修复前的测试失败即本批次验收的第一道证据。
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp

import pytest

from backend.core.nl2sql import NL2SQLGenerator


@pytest.fixture
def gen():
    return NL2SQLGenerator()


def executable_sql(result) -> str:
    """Strip comment lines so the payload can be parsed by sqlglot."""
    sql = result.sql or ""
    return "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))


# =============================================================================
# B1-1 聚合列选择：price 必须胜过 "average" 子串中的 age
# =============================================================================


class TestB1_1_AggregationColumnSelection:
    """The aggregated column must come from the user's named metric
    (price), not from a spurious column-pattern hit inside the
    aggregate keyword ("ave**rage**" contains "age")."""

    @pytest.mark.parametrize(
        "text,expected_agg",
        [
            ("calculate average price for products grouped by category", "AVG(price)"),
            ("average price of products", "AVG(price)"),
            ("平均价格 of products", "AVG(price)"),
            ("max amount of orders", "MAX(amount)"),
            ("sum of price for products", "SUM(price)"),
        ],
    )
    def test_aggregate_uses_named_metric(self, gen, text, expected_agg):
        result = gen.generate(text, "hive")
        assert result.success is True, result.explanation
        tree = sqlglot.parse_one(executable_sql(result), read="hive")
        found = [
            f.sql("hive") for f in tree.find_all(exp.Avg, exp.Sum, exp.Max, exp.Min)
        ]
        assert any(expected_agg in f for f in found), (
            f"expected {expected_agg!r} in {found!r}\nsql: {result.sql}"
        )
        # The spurious age column must not appear in any aggregate call.
        for f in found:
            assert "age" not in f.lower(), f"spurious age column in {f!r}"

    def test_no_spurious_age_in_grouped_average(self, gen):
        result = gen.generate(
            "calculate average price for products grouped by category", "hive"
        )
        assert result.success is True
        assert "AVG(age)" not in result.sql, result.sql
        tree = sqlglot.parse_one(executable_sql(result), read="hive")
        assert tree.find(exp.Group) is not None, result.sql
        group_cols = [c.sql("hive") for c in tree.args["group"].expressions]
        assert "category" in group_cols, result.sql


# =============================================================================
# B1-2 英语复数时间范围单位
# =============================================================================


class TestB1_2_EnglishPluralTimeRanges:
    """Plural units must keep their unit in BOTH the SQL predicate and
    the explanation — never silently downgraded to days."""

    @pytest.mark.parametrize(
        "text,expected_sql_fragment,expected_explanation_unit",
        [
            ("last 3 weeks of orders", "DATE_SUB(CURRENT_DATE, 21)", "周"),
            ("last 2 months of orders", "ADD_MONTHS(CURRENT_DATE, -2)", "月"),
            ("last 1 year of orders", "ADD_MONTHS(CURRENT_DATE, -12)", "年"),
            ("last 4 weeks of orders", "DATE_SUB(CURRENT_DATE, 28)", "周"),
            ("past 3 months of sales", "ADD_MONTHS(CURRENT_DATE, -3)", "月"),
        ],
    )
    def test_plural_unit_survives_sql_and_explanation(
        self, gen, text, expected_sql_fragment, expected_explanation_unit
    ):
        result = gen.generate(text, "hive")
        assert result.success is True, result.explanation
        assert expected_sql_fragment in result.sql, result.sql
        assert expected_explanation_unit in result.explanation, (
            f"explanation must state the {expected_explanation_unit!r} unit, got: {result.explanation!r}"
        )
        # The wrong "N days" unit must not be present.
        tree = sqlglot.parse_one(executable_sql(result), read="hive")
        assert len(list(tree.find_all(exp.Where))) == 1, result.sql

    def test_last_3_weeks_not_reported_as_days(self, gen):
        result = gen.generate("last 3 weeks of orders", "hive")
        assert "天" not in result.explanation, result.explanation

    @pytest.mark.parametrize(
        "text,dialect,fragment",
        [
            ("last 3 weeks of orders", "postgres", "INTERVAL '21 days'"),
            ("last 3 weeks of orders", "mysql", "INTERVAL 21 DAY"),
            ("last 2 months of orders", "postgres", "INTERVAL '-2 month'"),
            ("last 1 year of orders", "oracle", "ADD_MONTHS(TRUNC(SYSDATE), -12)"),
        ],
    )
    def test_plural_ranges_parseable_per_dialect(
        self, gen, text, dialect, fragment
    ):
        result = gen.generate(text, dialect)
        assert result.success is True, result.explanation
        assert fragment in result.sql, result.sql
        tree = sqlglot.parse_one(executable_sql(result), read=dialect)
        assert len(list(tree.find_all(exp.Where))) == 1, result.sql

    def test_chinese_plural_range_stays_calendar(self, gen):
        """Chinese 最近3周/最近2月: the SQL already carries the correct
        unit (characterization gate); the explanation must not claim
        the query is in days."""
        result = gen.generate("查询最近3周的订单", "hive")
        assert result.success is True, result.explanation
        assert "DATE_SUB(CURRENT_DATE, 21)" in result.sql, result.sql
        assert "天" not in result.explanation, result.explanation
        assert "周" in result.explanation, result.explanation

        result = gen.generate("查询最近2月的订单", "hive")
        assert result.success is True, result.explanation
        assert "ADD_MONTHS(CURRENT_DATE, -2)" in result.sql, result.sql
        assert "天" not in result.explanation, result.explanation
        assert "月" in result.explanation, result.explanation


# =============================================================================
# B1-3 Top-N + 过滤条件：WHERE 顺序
# =============================================================================


class TestB1_3_TopNWithFilterClauseOrder:
    """WHERE must precede ORDER BY, which precedes LIMIT — and the
    result must parse in the target dialect."""

    @pytest.mark.parametrize(
        "text",
        [
            "前10条金额大于100的订单",
            "top 10 orders by amount where amount greater than 100",
        ],
    )
    def test_where_before_order_and_limit(self, gen, text):
        result = gen.generate(text, "hive")
        assert result.success is True, result.explanation
        tree = sqlglot.parse_one(executable_sql(result), read="hive")
        where = tree.find(exp.Where)
        order = tree.find(exp.Order)
        assert where is not None, result.sql
        assert order is not None, result.sql
        # Structural clause order: WHERE node must be attached before ORDER
        # in the rendered SQL.
        sql = executable_sql(result)
        assert sql.upper().find("WHERE") < sql.upper().find("ORDER BY"), result.sql
        assert sql.upper().find("ORDER BY") < sql.upper().find("LIMIT"), result.sql
        assert "LIMIT 10" in sql, result.sql

    def test_limit_not_immediately_before_where(self, gen):
        """The exact defect: 'LIMIT 10\\nWHERE amount > 10' must be gone.
        The filter threshold must be the operator-bound value (100),
        not the LIMIT count that happens to sit earlier in the text."""
        result = gen.generate("前10条金额大于100的订单", "hive")
        sql = " ".join((result.sql or "").split())
        assert "amount > 100" in sql, f"threshold must bind to the operator word, got: {sql}"
        idx_limit = sql.upper().find("LIMIT")
        idx_where = sql.upper().find("WHERE")
        assert idx_where < idx_limit, result.sql

    @pytest.mark.parametrize(
        "text,expected_operator,expected_threshold,expected_limit",
        [
            # Chinese operator words (value sits directly after the operator)
            ("前10条金额大于100的订单", ">", 100, 10),
            ("前5条金额大于250的订单", ">", 250, 5),
            # English operator phrases (value sits at the end of the phrase:
            # "greater than 100", "greater than or equal to 100", ...)
            ("top 10 orders with amount greater than 100", ">", 100, 10),
            ("top 5 orders with amount greater than 250", ">", 250, 5),
            ("top 10 orders with amount greater than or equal to 100", ">=", 100, 10),
            ("top 10 orders with amount less than 100", "<", 100, 10),
            ("top 10 orders with amount less than or equal to 100", "<=", 100, 10),
        ],
    )
    def test_top_n_threshold_distinct_from_count(
        self, gen, text, expected_operator, expected_threshold, expected_limit
    ):
        result = gen.generate(text, "duckdb")
        assert result.success is True, result.explanation
        tree = sqlglot.parse_one(executable_sql(result), read="duckdb")
        where = tree.find(exp.Where)
        assert where is not None, result.sql
        assert f"amount {expected_operator} {expected_threshold}" in where.sql(dialect="duckdb"), (
            f"expected 'amount {expected_operator} {expected_threshold}', sql: {result.sql}"
        )
        # The top-N count must not leak in as the threshold.
        assert where.sql(dialect="duckdb") != f"amount {expected_operator} {expected_limit}", result.sql
        assert tree.args.get("limit") is not None, result.sql
        assert int(tree.args["limit"].expression.this) == expected_limit, result.sql

    @pytest.mark.parametrize(
        "text,expected_operator,expected_threshold",
        [
            ("前10条金额大于等于100的订单", ">=", 100),
            ("前10条金额小于100的订单", "<", 100),
            ("前10条金额小于等于100的订单", "<=", 100),
        ],
    )
    def test_cn_operator_bound_thresholds(self, gen, text, expected_operator, expected_threshold):
        result = gen.generate(text, "duckdb")
        assert result.success is True, result.explanation
        tree = sqlglot.parse_one(executable_sql(result), read="duckdb")
        where = tree.find(exp.Where)
        assert f"amount {expected_operator} {expected_threshold}" in where.sql(dialect="duckdb"), result.sql

    @pytest.mark.parametrize("dialect", ["postgres", "mysql", "oracle", "tsql", "duckdb", "hive"])
    def test_parseable_per_dialect(self, gen, dialect):
        result = gen.generate("前10条金额大于100的订单", dialect)
        assert result.success is True, result.explanation
        tree = sqlglot.parse_one(executable_sql(result), read=dialect)
        assert tree.find(exp.Where) is not None, result.sql
        assert tree.find(exp.Order) is not None, result.sql


# =============================================================================
# B1-4 多关系布尔组合
# =============================================================================


class TestB1_4_MultipleRelationBooleanComposition:
    """Combining two known relationships must yield ONE parseable WHERE
    clause (or a single boolean combination), never two WHERE clauses."""

    @pytest.mark.parametrize(
        "text,required_fks",
        [
            ("users who have orders and products", [
                "users.id = orders.user_id", "users.id = products.user_id",
            ]),
            ("find customers who have orders and payments", [
                "customers.id = orders.customer_id",
                "customers.id = payments.customer_id",
            ]),
        ],
    )
    def test_single_where_with_both_relations(self, gen, text, required_fks):
        result = gen.generate(text, "hive")
        assert result.success is True, result.explanation
        tree = sqlglot.parse_one(executable_sql(result), read="hive")
        wheres = list(tree.find_all(exp.Where))
        top_level_wheres = [w for w in wheres if w.find(exp.Exists) is not None]
        assert len(top_level_wheres) == 1, (
            f"expected exactly one top-level WHERE combining both relations, got {len(top_level_wheres)}\n"
            f"sql: {result.sql}"
        )
        for fk in required_fks:
            assert fk in result.sql, f"missing {fk!r}\nsql: {result.sql}"
        assert len(list(tree.find_all(exp.Exists))) == 2, result.sql

    def test_repeated_where_is_gone(self, gen):
        result = gen.generate("users who have orders and products", "hive")
        tree = sqlglot.parse_one(executable_sql(result), read="hive")
        wheres = [w for w in tree.find_all(exp.Where) if w.find(exp.Exists) is not None]
        # Exactly one top-level WHERE combining both EXISTS clauses (the
        # other WHERE nodes live inside each EXISTS subquery, one per
        # subquery — that is correct and expected).
        assert len(wheres) == 1, result.sql

    @pytest.mark.parametrize("dialect", ["postgres", "mysql", "oracle", "tsql", "duckdb", "hive"])
    def test_parseable_per_dialect(self, gen, dialect):
        result = gen.generate("users who have orders and products", dialect)
        assert result.success is True, result.explanation
        tree = sqlglot.parse_one(executable_sql(result), read=dialect)
        assert len(list(tree.find_all(exp.Exists))) == 2, result.sql


# =============================================================================
# B1-5 中文关系意图端到端 + 失败关闭
# =============================================================================


class TestB1_5_ChineseRelationIntent:
    """Chinese relational intent must produce the relational SQL
    (EXISTS / NOT EXISTS) end-to-end, and unknown pairs must fail
    closed instead of silently returning the single-table SQL."""

    def test_chinese_exists_relation(self, gen):
        result = gen.generate("查询有订单的用户", "hive")
        assert result.success is True, result.explanation
        assert "EXISTS" in result.sql.upper(), (
            f"Chinese relational intent must yield EXISTS, got: {result.sql}"
        )
        assert "users.id = orders.user_id" in result.sql, result.sql
        tree = sqlglot.parse_one(executable_sql(result), read="hive")
        from_clause = tree.find(exp.From)
        assert from_clause.this.name == "users", result.sql
        assert tree.find(exp.Exists) is not None, result.sql

    def test_chinese_not_exists_relation(self, gen):
        result = gen.generate("查询没有订单的用户", "hive")
        assert result.success is True, result.explanation
        assert "NOT EXISTS" in result.sql.upper(), result.sql
        assert "users.id = orders.user_id" in result.sql, result.sql

    def test_chinese_known_pair_customers(self, gen):
        result = gen.generate("查询有订单的客户", "hive")
        assert result.success is True, result.explanation
        assert "EXISTS" in result.sql.upper(), result.sql
        assert "customers.id = orders.customer_id" in result.sql, result.sql

    def test_chinese_unknown_pair_fails_closed(self, gen):
        result = gen.generate("查询有发票的用户", "hive")
        assert result.success is False, (
            f"unknown pair must fail closed, got sql: {result.sql!r}"
        )
        assert result.sql is None
        assert result.confidence == 0.0
        assert "Unable to safely infer" in result.explanation, result.explanation

    def test_chinese_no_modifier_fails_closed_for_unknown_pair(self, gen):
        result = gen.generate("查询没有发票的用户", "hive")
        assert result.success is False, result.sql
        assert "Unable to safely infer" in result.explanation, result.explanation

    @pytest.mark.parametrize("dialect", ["postgres", "mysql", "oracle", "tsql", "duckdb", "hive"])
    def test_chinese_relation_parseable_per_dialect(self, gen, dialect):
        result = gen.generate("查询有订单的用户", dialect)
        assert result.success is True, result.explanation
        tree = sqlglot.parse_one(executable_sql(result), read=dialect)
        assert tree.find(exp.Exists) is not None, result.sql
