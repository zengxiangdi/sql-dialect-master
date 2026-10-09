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
PARSE_ONLY_DIALECTS = ("postgres", "oracle", "tsql", "mysql")


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


def test_parse_only_dialects_are_recorded_not_claimed():
    """The audit's 'cannot-runtime-verify → say so' rule: the non-DuckDB
    dialects in this batch are sqlglot parse-checked only.  This test
    documents the fact structurally — it fails if the record is ever
    silently dropped from the module."""
    assert PARSE_ONLY_DIALECTS == ("postgres", "oracle", "tsql", "mysql")
    for dialect in PARSE_ONLY_DIALECTS:
        assert EVIDENCE_TIERS and dialect not in EVIDENCE_TIERS
