"""B1 runtime semantic verification on DuckDB (Tier A).

Batch 1 of the post-v1.1.0 NL2SQL semantic-correctness audit.  These
tests execute the SQL the generator produces against a real in-process
DuckDB database and assert on the *returned values* — never on
SQL-string shape or keyword presence.

Evidence classification (mirrors G3/G5 conventions):
  A — native DuckDB runtime: the target engine actually executes the
        construct (standard JOIN / EXISTS / aggregates / LIMIT /
        ORDER BY / predicate arithmetic);
  B — compatible-engine only: the generated SQL targets another
        dialect and runs here merely because DuckDB accepts it —
        cited as compatible evidence, never as target-engine proof.

Per the audit brief, constructs that could only be parse-checked
(sqlglot structural acceptance for oracle/tsql/postgres/mysql) are
*recorded* here as parse-only evidence — they are never claimed as
runtime-verified.
"""
from __future__ import annotations

import pytest

duckdb = pytest.importorskip("duckdb")

from backend.core.nl2sql import NL2SQLGenerator

EVIDENCE_TIERS = {
    "avg_price_grouped_by_category": "A",
    "last_3_weeks": "A",
    "top_n_with_filter_clause_order": "A",
    "multi_relation_exists_composition": "A",
    "chinese_relation_intent_exists": "A",
    "chinese_unknown_pair_fail_closed": "A",
}

# Dialects whose generated SQL is only structurally parse-checked in
# this batch (sqlglot), not executed on a real engine — recorded per
# the audit's "cannot-runtime-verify → state explicitly" rule.
#
# Evidence ledger, by dialect, for all 5 B1 cases:
#   dialect   generated  sqlglot-parsed (own dialect)  executed
#   postgres     yes         yes                          NOT executed
#   mysql        yes         yes                          NOT executed
#   oracle       yes         yes                          NOT executed
#   tsql         yes         yes                          NOT executed
#   hive         yes         yes                          NOT executed
#   duckdb       yes         yes                          YES — Tier A,
#                                                            native in-process
#                                                            DuckDB execution
#
# The DuckDB-executed Tier A tests run the *duckdb*-dialect generated
# SQL, not the hive-dialect SQL.  DuckDB and Hive share only basic
# SQL surface syntax; Hive-specific constructs (e.g. DATE_SUB's
# 2-arg form) do not execute on DuckDB.  Claiming "hive engine
# verified" would be a false positive — hive SQL in this batch is
# parse-checked only.
PARSE_ONLY_DIALECTS = ("postgres", "oracle", "tsql", "mysql", "hive")


@pytest.fixture
def conn():
    db = duckdb.connect(":memory:")
    db.execute(
        """
        CREATE TABLE products (id INT, name VARCHAR, price DECIMAL,
                                 category VARCHAR, user_id INT);
        CREATE TABLE users (id INT, name VARCHAR, age INT);
        CREATE TABLE orders (id INT, user_id INT, product_id INT,
                             amount DECIMAL, date DATE, status VARCHAR);
        CREATE TABLE invoices (id INT, user_id INT, amount DECIMAL);
        """
    )
    db.execute(
        "INSERT INTO products VALUES "
        "(1, 'a', 100, 'cat_a', 1), (2, 'b', 200, 'cat_a', 2), "
        "(3, 'c', 300, 'cat_b', 1)"
    )
    db.execute("INSERT INTO users VALUES (1, 'alice', 30), (2, 'bob', 25)")
    db.execute(
        "INSERT INTO orders VALUES "
        "(1, 1, 1, 500, CURRENT_DATE - 3, 'active'), "
        "(2, 1, 2, 150, CURRENT_DATE - 30, 'active'), "
        "(3, 2, 1, 250, CURRENT_DATE - 2, 'active')"
    )
    yield db
    db.close()


@pytest.fixture
def gen():
    return NL2SQLGenerator()


def executable(result) -> str:
    sql = result.sql or ""
    return "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))


class TestB1RuntimeAggregation:
    """B1-1: AVG(price) must reflect the named metric column, not the
    spurious 'age' hit inside 'average'."""

    def test_average_price_grouped_by_category_returns_expected_values(self, conn, gen):
        result = gen.generate(
            "calculate average price for products grouped by category", "duckdb"
        )
        assert result.success is True, result.explanation
        rows = dict(
            conn.execute(executable(result)).fetchall()
        )
        assert rows == {"cat_a": 150.0, "cat_b": 300.0}, rows


class TestB1RuntimeTimeRange:
    """B1-2: 'last 3 weeks' must bound the window at 21 days and the
    explanation must name the week unit, not the day unit."""

    def test_last_3_weeks_window_excludes_30_day_old_rows(self, conn, gen):
        result = gen.generate("last 3 weeks of orders", "duckdb")
        assert result.success is True, result.explanation
        # orders 1 (3 days old) and 3 (2 days old) are inside 21 days;
        # order 2 (30 days old) is not.
        rows = [row[0] for row in conn.execute(executable(result)).fetchall()]
        assert sorted(rows) == [1, 3], rows
        assert result.explanation == "查询最近3周数据", result.explanation


class TestB1RuntimeClauseOrder:
    """B1-3: WHERE + ORDER BY + LIMIT must be emitted in that order and
    executed correctly by a real engine."""

    def test_top_n_with_filter_executes(self, conn, gen):
        result = gen.generate("前10条金额大于100的订单", "duckdb")
        assert result.success is True, result.explanation
        rows = [row[0] for row in conn.execute(executable(result)).fetchall()]
        # All three fixture orders have amount > 10; DESC puts 500 first.
        assert rows == [1, 3, 2], rows


class TestB1RuntimeMultiRelation:
    """B1-4: two known relations compose into a single parseable WHERE
    that a real engine accepts and that returns the correct subject rows."""

    def test_users_with_orders_and_products(self, conn, gen):
        result = gen.generate("users who have orders and products", "duckdb")
        assert result.success is True, result.explanation
        rows = [row[0] for row in conn.execute(executable(result)).fetchall()]
        # user 1: orders {1,2}, products user_id=1 {1,3}; user 2: order {3},
        # product user_id=2 {2}.  Both users have at least one of each.
        assert sorted(rows) == [1, 2], rows


class TestB1RuntimeChineseRelation:
    """B1-5: Chinese relational intent must reach the relational
    structure end-to-end on a real engine, and an unknown pair must
    fail closed with sql=None."""

    def test_chinese_users_with_orders(self, conn, gen):
        result = gen.generate("查询有订单的用户", "duckdb")
        assert result.success is True, result.explanation
        rows = [row[0] for row in conn.execute(executable(result)).fetchall()]
        assert sorted(rows) == [1, 2], rows

    def test_chinese_unknown_pair_fails_closed_with_no_sql(self, conn, gen):
        result = gen.generate("查询有发票的用户", "duckdb")
        assert result.success is False
        assert result.sql is None
        assert result.confidence == 0.0
        assert "Unable to safely infer" in result.explanation


class TestB1RuntimeChineseExistsNotExistsValues:
    """The 没有 / 没有任何 phrasings must each produce NOT EXISTS and
    return the correct row set, not just parse."""

    def _make_two_user_db(self):
        db = duckdb.connect(":memory:")
        db.execute("CREATE TABLE users (id INT, name VARCHAR, age INT)")
        db.execute("CREATE TABLE orders (id INT, user_id INT, amount DECIMAL)")
        db.execute("CREATE TABLE invoices (id INT, user_id INT, amount DECIMAL)")
        # user 1 has orders; user 2 has none; both have invoices
        db.execute("INSERT INTO users VALUES (1, 'alice', 30), (2, 'bob', 25)")
        db.execute("INSERT INTO orders VALUES (1, 1, 100), (2, 1, 50)")
        db.execute("INSERT INTO invoices VALUES (1, 1, 10), (2, 2, 20)")
        return db

    def test_no_orders_not_exists_returns_only_user_without_orders(self, gen):
        db = self._make_two_user_db()
        result = gen.generate("查询没有订单的用户", "duckdb")
        assert result.success is True, result.explanation
        rows = [row[0] for row in db.execute(executable(result)).fetchall()]
        assert rows == [2], rows

    def test_no_any_orders_not_exists_returns_only_user_without_orders(self, gen):
        db = self._make_two_user_db()
        result = gen.generate("查询没有任何订单的用户", "duckdb")
        assert result.success is True, result.explanation
        rows = [row[0] for row in db.execute(executable(result)).fetchall()]
        assert rows == [2], rows

    def test_has_orders_exists_returns_only_user_with_orders(self, gen):
        db = self._make_two_user_db()
        result = gen.generate("查询有订单的用户", "duckdb")
        assert result.success is True, result.explanation
        rows = [row[0] for row in db.execute(executable(result)).fetchall()]
        assert rows == [1], rows

    def test_unknown_pair_no_invoice_relation_fails_closed(self, gen):
        db = self._make_two_user_db()
        result = gen.generate("查询有发票的用户", "duckdb")
        assert result.success is False
        assert result.sql is None
        assert result.confidence == 0.0


class TestB1RuntimeTopNThreshold:
    """B1-3 follow-up: the filter threshold must bind to the operator
    word (or its tail, for English operator phrases), not to the
    Top-N count that sits earlier in the text."""

    def _make_orders_db(self, amounts):
        db = duckdb.connect(":memory:")
        db.execute("CREATE TABLE orders (id INT, amount DECIMAL)")
        rows = ", ".join(f"({i + 1}, {a})" for i, a in enumerate(amounts))
        db.execute(f"INSERT INTO orders VALUES {rows}")
        return db

    def test_threshold_is_100_not_10(self, gen):
        db = self._make_orders_db([50, 100, 150, 250])
        result = gen.generate("前10条金额大于100的订单", "duckdb")
        assert result.success is True, result.explanation
        rows = [float(a) for _, a in db.execute(executable(result)).fetchall()]
        assert all(a > 100 for a in rows), rows
        assert rows == [250.0, 150.0], rows

    def test_threshold_distinct_from_count_and_desc_ordered(self, gen):
        db = self._make_orders_db([50, 100, 250, 300, 400])
        result = gen.generate("前5条金额大于250的订单", "duckdb")
        assert result.success is True, result.explanation
        rows = [float(a) for _, a in db.execute(executable(result)).fetchall()]
        assert rows == [400.0, 300.0], rows

    def test_en_greater_than_tail_threshold_not_count(self, gen):
        db = self._make_orders_db([50, 100, 150, 250])
        result = gen.generate("top 10 orders with amount greater than 100", "duckdb")
        assert result.success is True, result.explanation
        rows = [float(a) for _, a in db.execute(executable(result)).fetchall()]
        # strict >: the 100 boundary must be excluded
        assert rows == [250.0, 150.0], rows

    def test_en_greater_than_tail_distinct_count_and_threshold(self, gen):
        db = self._make_orders_db([50, 100, 250, 300, 400])
        result = gen.generate("top 5 orders with amount greater than 250", "duckdb")
        assert result.success is True, result.explanation
        rows = [float(a) for _, a in db.execute(executable(result)).fetchall()]
        assert rows == [400.0, 300.0], rows

    def test_en_greater_or_equal_includes_boundary(self, gen):
        db = self._make_orders_db([50, 100, 150, 250])
        result = gen.generate(
            "top 10 orders with amount greater than or equal to 100", "duckdb"
        )
        assert result.success is True, result.explanation
        rows = [float(a) for _, a in db.execute(executable(result)).fetchall()]
        assert rows == [250.0, 150.0, 100.0], rows

    def test_en_less_than_excludes_boundary(self, gen):
        db = self._make_orders_db([50, 100, 150, 250])
        result = gen.generate("top 10 orders with amount less than 100", "duckdb")
        assert result.success is True, result.explanation
        rows = [float(a) for _, a in db.execute(executable(result)).fetchall()]
        assert rows == [50.0], rows

    def test_en_less_or_equal_includes_boundary(self, gen):
        db = self._make_orders_db([50, 100, 150, 250])
        result = gen.generate(
            "top 10 orders with amount less than or equal to 100", "duckdb"
        )
        assert result.success is True, result.explanation
        rows = [float(a) for _, a in db.execute(executable(result)).fetchall()]
        assert rows == [100.0, 50.0], rows

    def test_cn_greater_or_equal_includes_boundary(self, gen):
        db = self._make_orders_db([50, 100, 150, 250])
        result = gen.generate("前10条金额大于等于100的订单", "duckdb")
        assert result.success is True, result.explanation
        rows = [float(a) for _, a in db.execute(executable(result)).fetchall()]
        assert rows == [250.0, 150.0, 100.0], rows

    def test_cn_less_than_excludes_boundary(self, gen):
        db = self._make_orders_db([50, 100, 150, 250])
        result = gen.generate("前10条金额小于100的订单", "duckdb")
        assert result.success is True, result.explanation
        rows = [float(a) for _, a in db.execute(executable(result)).fetchall()]
        assert rows == [50.0], rows

    def test_cn_less_or_equal_includes_boundary(self, gen):
        db = self._make_orders_db([50, 100, 150, 250])
        result = gen.generate("前10条金额小于等于100的订单", "duckdb")
        assert result.success is True, result.explanation
        rows = [float(a) for _, a in db.execute(executable(result)).fetchall()]
        assert rows == [100.0, 50.0], rows


def test_parse_only_dialects_are_recorded_not_claimed():
    """The audit's 'cannot-runtime-verify → say so' rule: the non-DuckDB
    dialects in this batch are sqlglot parse-checked only.  This test
    documents the fact structurally — it fails if the record is ever
    silently dropped from the module.  Note: hive is parse-checked
    here, not engine-verified (see the PARSE_ONLY_DIALECTS comment)."""
    assert PARSE_ONLY_DIALECTS == ("postgres", "oracle", "tsql", "mysql", "hive")
    for dialect in PARSE_ONLY_DIALECTS:
        assert EVIDENCE_TIERS and dialect not in EVIDENCE_TIERS
