"""G1: NL2SQL semantic path convergence.

Regression tests for two post-v1.1.0 audit findings:

* G1-A — the ``time_range_query`` template already emits a WHERE clause, and
  post-processing re-appended a second, duplicate WHERE for the same date
  predicate. Successful generation must yield at most one WHERE clause, the
  date predicate must appear exactly once, and the rolling/calendar-relative
  semantics of D3 must be preserved. Combined-predicate inputs
  (numeric condition + date, status + date) must compose into a single
  conjunctive WHERE without losing or duplicating either predicate.

* G1-B — the ``join_query`` template path bypassed the D2 unknown-relationship
  fail-safe: unknown table pairs produced ``ON None`` / fabricated FKs with
  ``success=True``. Unknown relationships must fail safely with
  ``success=False``, ``sql=None``, ``confidence=0.0`` and an explicit
  explanation/suggestion, while known relationships keep their physical-join
  behaviour.

All assertions go through the canonical public entry point
(``backend.core.nl2sql.NL2SQLGenerator``) and verify structure via sqlglot
parsing rather than keyword sniffing.
"""
from __future__ import annotations

import re

import pytest
import sqlglot
from sqlglot import exp

from backend.core.nl2sql import NL2SQLGenerator


@pytest.fixture
def gen():
    return NL2SQLGenerator()


def executable_sql(result) -> str:
    """Strip comment lines so the payload can be parsed by sqlglot."""
    sql = result.sql or ""
    return "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))


def where_clauses(tree: exp.Expression) -> list:
    return list(tree.find_all(exp.Where))


def unique_where_bodies(tree: exp.Expression) -> list:
    """Canonical WHERE predicate bodies, de-duplicated by rendered text."""
    bodies = [w.this.sql() for w in where_clauses(tree)]
    seen: dict[str, str] = {}
    for body in bodies:
        seen[body] = body
    return list(seen)


# =============================================================================
# G1-A: Duplicate WHERE regression
# =============================================================================

class TestG1A_DuplicateWhere:
    """time_range inputs must produce at most one WHERE clause."""

    # (text, dialect) — covers EN, CN, with/without an explicit table.
    INPUTS = [
        "last 7 days",
        "last 30 days",
        "last week",
        "last month",
        "last year",
        "查询最近7天的订单",
        "find orders from last 7 days",
    ]
    DIALECTS = ["postgres", "hive", "mysql", "oracle", "tsql", "duckdb"]

    @pytest.mark.parametrize("text", INPUTS)
    @pytest.mark.parametrize("dialect", DIALECTS)
    def test_single_where_clause(self, gen, text, dialect):
        result = gen.generate(text, dialect)
        assert result.success is True, result.explanation
        assert result.sql is not None
        tree = sqlglot.parse_one(executable_sql(result), read=dialect)
        assert len(unique_where_bodies(tree)) == 1, result.sql

    @pytest.mark.parametrize("text", INPUTS)
    def test_date_predicate_not_duplicated(self, gen, text):
        """The date predicate must occur exactly once (no repeated bodies)."""
        result = gen.generate(text, "postgres")
        assert result.success is True
        tree = sqlglot.parse_one(executable_sql(result), read="postgres")
        bodies = [w.this.sql() for w in where_clauses(tree)]
        assert len(bodies) == len(set(bodies)), f"duplicate WHERE bodies: {bodies}"
        # There is at most one WHERE node total at the top level for these inputs.
        assert len(where_clauses(tree)) == 1, result.sql

    @pytest.mark.parametrize(
        "text,expected_fragment",
        [
            ("last 7 days", "7"),
            ("last 30 days", "30"),
            ("last week", "7"),
            ("last month", "1 month"),
            ("last year", "12 month"),
            ("find orders from last 7 days", "7"),
        ],
    )
    def test_d3_rolling_calendar_semantics_preserved(self, gen, text, expected_fragment):
        """D3 semantics: last week is a rolling 7-day window; last month/year are
        calendar-relative. Values must survive dialect adjustment intact."""
        result = gen.generate(text, "postgres")
        assert result.success is True
        sql = result.sql
        assert expected_fragment in sql
        # Calendar-relative periods must remain calendar arithmetic (1 month /
        # 12 month), not flattened to day rolling.
        if text in ("last month", "last year"):
            assert "MONTH" in sql.upper()

    def test_chinese_recent_days(self, gen):
        result = gen.generate("查询最近7天的订单", "postgres")
        assert result.success is True
        assert "orders" in result.sql.lower()
        tree = sqlglot.parse_one(executable_sql(result), read="postgres")
        assert len(unique_where_bodies(tree)) == 1

    @pytest.mark.parametrize("dialect", DIALECTS)
    def test_last_7_days_parseable_per_dialect(self, gen, dialect):
        result = gen.generate("last 7 days", dialect)
        assert result.success is True
        tree = sqlglot.parse_one(executable_sql(result), read=dialect)
        assert len(unique_where_bodies(tree)) == 1


# =============================================================================
# G1-A: Combined-predicate semantic preservation
# =============================================================================

class TestG1A_CombinedPredicates:
    """Condition + date combinations compose into one conjunctive WHERE.

    No predicate may be lost, duplicated, or have its value corrupted by a
    sibling predicate's number.
    """

    # (text, dialect, required_predicates) — each required predicate is a
    # substring of the sqlglot-rendered WHERE body of that dialect.
    @pytest.mark.parametrize(
        "text,dialect,required",
        [
            # numeric condition + yesterday
            (
                "find orders greater than 5 yesterday", "postgres",
                ["column > 5", "CURRENT_DATE"],
            ),
            # numeric condition + last 7 days — the condition value 5 must
            # survive alongside the 7-day window.
            (
                "find orders greater than 5 last 7 days", "postgres",
                ["column > 5", "INTERVAL '7 DAYS'"],
            ),
            # status condition + last 7 days
            (
                "find active orders from last 7 days", "postgres",
                ["status = 'active'", "INTERVAL '7 DAYS'"],
            ),
            # status condition + last month (calendar-relative)
            (
                "find active orders from last month", "postgres",
                ["status = 'active'", "INTERVAL '-1 MONTH'"],
            ),
            # status condition + last year (calendar-relative)
            (
                "find active orders from last year", "postgres",
                ["status = 'active'", "INTERVAL '-12 MONTH'"],
            ),
            # Same combined inputs across every dialect stay parseable with
            # a single WHERE clause.
            (
                "find orders greater than 5 last 7 days", "hive",
                ["column > 5", "DATE_ADD(CURRENT_DATE, 7 * -1)"],
            ),
            (
                "find active orders from last 7 days", "mysql",
                ["status = 'active'", "INTERVAL '7' DAY"],
            ),
            (
                "find active orders from last month", "oracle",
                ["status = 'active'", "ADD_MONTHS(TRUNC(SYSDATE, 'DD'), -1)"],
            ),
            (
                "find active orders from last year", "tsql",
                ["status = 'active'", "DATEADD(MONTH, -12, CAST(GETDATE() AS DATE))"],
            ),
            (
                "find active orders from last 7 days", "duckdb",
                ["status = 'active'", "INTERVAL '7' DAYS"],
            ),
        ],
    )
    def test_predicates_all_present(
        self, gen, text, dialect, required
    ):
        result = gen.generate(text, dialect)
        assert result.success is True, result.explanation
        sql = result.sql
        tree = sqlglot.parse_one(executable_sql(result), read=dialect)
        wheres = where_clauses(tree)
        if "EXISTS" not in sql.upper():
            assert len(wheres) == 1, sql
        # Predicate assertions run against the sqlglot-rendered body so that
        # dialect-specific syntax (INTERVAL '7' DAY vs INTERVAL '7 DAYS',
        # DATE_ADD(CURRENT_DATE, -7) vs DATE_SUB(CURRENT_DATE, 7)) is
        # normalized.
        body = wheres[0].this.sql(dialect=dialect) if wheres else sql
        for predicate in required:
            assert predicate in body, (
                f"missing predicate {predicate!r} in {body!r}"
            )

    @pytest.mark.parametrize(
        "text,dialect",
        [
            ("find orders greater than 5 yesterday", "postgres"),
            ("find orders greater than 5 last 7 days", "postgres"),
            ("find active orders from last 7 days", "postgres"),
            ("find active orders from last month", "postgres"),
            ("find active orders from last year", "postgres"),
        ],
    )
    def test_no_predicate_duplication(self, gen, text, dialect):
        """Every predicate must appear exactly once — no duplicated bodies."""
        result = gen.generate(text, dialect)
        assert result.success is True
        tree = sqlglot.parse_one(executable_sql(result), read=dialect)
        bodies = [w.this.sql() for w in where_clauses(tree)]
        assert len(bodies) == len(set(bodies)), f"duplicated: {bodies}"

    @pytest.mark.parametrize(
        "text,expected_fragment",
        [
            # Rolling semantics preserved inside combined predicates.
            ("find active orders from last 7 days", "DATE_SUB(CURRENT_DATE, 7)"),
            ("find active orders from last week", "DATE_SUB(CURRENT_DATE, 7)"),
            ("find active orders from last 7 weeks", "DATE_SUB(CURRENT_DATE, 49)"),
            # Calendar semantics preserved inside combined predicates.
            ("find active orders from last month", "ADD_MONTHS(CURRENT_DATE, -1)"),
            ("find active orders from last year", "ADD_MONTHS(CURRENT_DATE, -12)"),
        ],
    )
    def test_rolling_calendar_semantics_inside_combination(
        self, gen, text, expected_fragment
    ):
        result = gen.generate(text, "hive")
        assert result.success is True
        assert expected_fragment in result.sql, result.sql


# =============================================================================
# G1-B: Unknown relationship fail-safe regression
# =============================================================================

class TestG1B_UnknownRelationship:
    """Unknown relationships must fail safely across all paths."""

    # Relational EXISTential phrasings (enhanced path) and explicit physical
    # JOIN / CN-connective phrasings (join_query template path).
    UNKNOWN_INPUTS = [
        "find users who have invoices",
        "find users who have logs",
        "find products who have payments",
        "查询 users 和 invoices 的关联数据",
        "查询 users 与 invoices 连接",
        "find users join invoices",
    ]
    DIALECTS = ["postgres", "hive", "mysql", "oracle", "tsql", "duckdb"]

    @pytest.mark.parametrize("text", UNKNOWN_INPUTS)
    @pytest.mark.parametrize("dialect", DIALECTS)
    def test_unknown_relation_fails_safely(self, gen, text, dialect):
        result = gen.generate(text, dialect)
        assert result.success is False
        assert result.sql is None
        assert result.confidence == 0.0
        assert "Unable to safely infer" in result.explanation
        assert result.suggestions, "expected explicit next-step suggestions"
        # No fabricated join condition can leak into a null payload.
        assert "ON None" not in str(result.sql)

    def test_unknown_relation_has_actionable_suggestion(self, gen):
        result = gen.generate("find users who have invoices", "postgres")
        assert result.success is False
        joined = " ".join(result.suggestions).lower()
        assert "join condition" in joined or "relationship" in joined

    @pytest.mark.parametrize("text", UNKNOWN_INPUTS)
    def test_no_fabricated_fk_on_unknown(self, gen, text):
        """No FK may be guessed from table names for an unknown pair."""
        result = gen.generate(text, "postgres")
        if result.sql is None:
            return
        tree = sqlglot.parse_one(executable_sql(result), read="postgres")
        for join in tree.find_all(exp.Join):
            on = join.args.get("on")
            assert on is not None, "a JOIN with no ON condition is a fabricated/None FK"


# =============================================================================
# G1-B: Early boolean/null path fail-closed regression
# =============================================================================

class TestG1B_EarlyBooleanPath:
    """Unknown relationships must fail closed even when the input routes
    through the early boolean/null branch in generate(), which bypasses the
    ordinary enhanced-fallback gate.

    Inputs below use price/quantity/amount/rating columns (the ones matched
    by extract_boolean_conditions) combined with an unknown table pair.
    """

    # These inputs trigger boolean_conditions or has_explicit_null_predicate
    # in generate() before the template/enhanced-fallback gates.
    EARLY_PATH_INPUTS = [
        # price/quantity → two comparisons → boolean_conditions non-None
        "find users who have invoices where price = 1 and quantity = 2",
        "find users who have invoices where price > 5 or price < 3",
        "find products who have payments where amount = 10 and rating > 4",
        # price is null → has_explicit_null_predicate True
        "find users who have invoices where price is null and quantity > 1",
        # CN numeric + null
        "查询 users 和 invoices 的关联数据 where price > 10 and price is null",
    ]
    DIALECTS = ["postgres", "hive", "mysql", "oracle", "tsql", "duckdb"]

    @pytest.mark.parametrize("text", EARLY_PATH_INPUTS)
    @pytest.mark.parametrize("dialect", DIALECTS)
    def test_early_path_unknown_fails_safely(self, gen, text, dialect):
        result = gen.generate(text, dialect)
        assert result.success is False, (
            f"expected fail-closed for unknown pair in early path: {text!r} [{dialect}]\n"
            f"got success=True sql={result.sql!r}"
        )
        assert result.sql is None
        assert result.confidence == 0.0
        assert "Unable to safely infer" in result.explanation, result.explanation
        assert result.suggestions, "expected non-empty suggestions"
        # No fabricated FK may leak.
        assert "ON None" not in str(result.sql)

    @pytest.mark.parametrize("text", EARLY_PATH_INPUTS)
    def test_early_path_does_not_silently_drop_unknown_join(self, gen, text):
        """The unresolved join must not disappear while unrelated predicates remain.
        The result must be a fail-safe, not a valid-looking single-table query."""
        result = gen.generate(text, "postgres")
        assert result.success is False
        assert result.sql is None
        # The explanation must name the relationship problem, not just list conditions.
        assert "relationship" in result.explanation.lower()

    @pytest.mark.parametrize(
        "text,expected_pair",
        [
            ("find users who have invoices where price = 5 and quantity = 2", "users ⟷ invoices"),
            ("find products who have payments where price = 5 and quantity = 2", "products ⟷ payments"),
            ("find users join invoices", "users ⟷ invoices"),
            ("查询 users 和 invoices 的关联数据", "users ⟷ invoices"),
            ("find users who have invoices", "users ⟷ invoices"),
        ],
    )
    def test_fail_closed_explanation_names_actual_pair(self, gen, text, expected_pair):
        """The pair description must come from the join structure, not the
        final table variable — so 'invoices ⟷ invoices' is never emitted."""
        result = gen.generate(text, "postgres")
        assert result.success is False
        assert expected_pair in result.explanation, (
            f"expected {expected_pair!r} in explanation, got: {result.explanation!r}"
        )

    def test_early_path_known_pair_still_succeeds(self, gen):
        """A known pair with the same boolean-conditions shape must succeed."""
        result = gen.generate(
            "find users who have orders where price = 1 and quantity = 2",
            "postgres",
        )
        assert result.success is True, result.explanation
        assert result.sql is not None
        assert "EXISTS" in result.sql.upper() or "JOIN" in result.sql.upper()
        assert "users.id = orders.user_id" in result.sql

    def test_null_predicate_known_pair_succeeds(self, gen):
        """price is null + known pair must succeed via the early null path."""
        result = gen.generate(
            "find users who have orders where price is null and quantity > 1",
            "postgres",
        )
        assert result.success is True, result.explanation
        assert result.sql is not None

    @pytest.mark.parametrize("text", EARLY_PATH_INPUTS[:3])
    def test_early_path_table_hint_does_not_bypass(self, gen, text):
        """Even with a table_hint, an unknown pair in the early path must fail."""
        result = gen.generate(text, "postgres", table_hint="users")
        assert result.success is False, (
            f"table_hint must not bypass the unknown-relationship gate: {text!r}"
        )
        assert result.sql is None
        assert result.confidence == 0.0


# =============================================================================
# G1-B: Early boolean/null path — known-relationship subject-table semantics
# =============================================================================

class TestG1B_EarlyPathSubjectTable:
    """Relational inputs that enter the early boolean/null path must select
    the SUBJECT table for the outer FROM, not the relation table.

    For 'find users who have orders where price = 5':
      outer FROM == users        (subject, first-mentioned table)
      relation table == orders   (inside the EXISTS subquery)
      join condition == users.id = orders.user_id
      conditions appear inside the subquery, not at the outer level
    """

    # (text, outer_table, relation_table, canonical_fk, expected_exists)
    KNOWN_RELATION_INPUTS = [
        (
            "find users who have orders where price = 5 and quantity = 2",
            "users", "orders", "users.id = orders.user_id", "EXISTS",
        ),
        (
            "find users who have orders where price is null",
            "users", "orders", "users.id = orders.user_id", "EXISTS",
        ),
        (
            "find users who do not have orders where price = 5 and quantity = 2",
            "users", "orders", "users.id = orders.user_id", "NOT EXISTS",
        ),
        (
            "find users who do not have orders where price is null",
            "users", "orders", "users.id = orders.user_id", "NOT EXISTS",
        ),
        (
            "find customers who have orders where price = 5 and quantity = 2",
            "customers", "orders", "customers.id = orders.customer_id", "EXISTS",
        ),
        (
            "find orders who have products where price = 5 and quantity = 2",
            "orders", "products", "orders.product_id = products.id", "EXISTS",
        ),
        (
            "find employees who have departments where price = 5 and quantity = 2",
            "employees", "departments", "employees.dept_id = departments.id", "EXISTS",
        ),
    ]

    @pytest.mark.parametrize(
        "text,outer_table,relation_table,canonical_fk,expected_exists",
        KNOWN_RELATION_INPUTS,
    )
    def test_outer_from_is_subject_not_relation(
        self, gen, text, outer_table, relation_table, canonical_fk, expected_exists
    ):
        result = gen.generate(text, "postgres")
        assert result.success is True, result.explanation
        assert result.sql is not None
        tree = sqlglot.parse_one(executable_sql(result), read="postgres")

        # The outer FROM must be the subject table.
        from_clause = tree.find(exp.From)
        assert from_clause is not None
        assert from_clause.this.name == outer_table, (
            f"outer FROM must be {outer_table!r}, got {from_clause.this.name!r}\n"
            f"sql: {result.sql}"
        )

        # The canonical relationship must be present.
        assert canonical_fk in result.sql, result.sql

        # The expected EXISTS/NOT EXISTS must be present.
        assert expected_exists in result.sql.upper(), result.sql

        # The relation table must appear inside the subquery, not as the
        # outer FROM.
        subqueries = list(tree.find_all(exp.Select))
        subquery_tables = {
            t.name for sq in subqueries for t in sq.find_all(exp.Table)
        }
        assert relation_table in subquery_tables, (
            f"relation table {relation_table!r} must be inside a subquery, "
            f"subquery tables: {subquery_tables}\nsql: {result.sql}"
        )

    @pytest.mark.parametrize("text", [
        "find users who have orders where price = 5 and quantity = 2",
        "find users who have orders where price is null",
        "find users who do not have orders where price = 5 and quantity = 2",
        "find users who do not have orders where price is null",
    ])
    def test_conditions_scoped_inside_subquery(self, gen, text):
        """The boolean/null conditions must live inside the EXISTS/NOT EXISTS
        subquery, not at the outer WHERE level, and must not be duplicated."""
        result = gen.generate(text, "postgres")
        assert result.success is True
        tree = sqlglot.parse_one(executable_sql(result), read="postgres")
        exists = next(tree.find_all(exp.Exists))
        subquery = exists.this
        assert isinstance(subquery, exp.Select)
        subwhere = list(subquery.find_all(exp.Where))
        assert subwhere, (
            f"conditions must be scoped inside the subquery: {result.sql}"
        )
        # No duplicated predicate bodies anywhere in the tree.
        bodies = [w.this.sql() for w in where_clauses(tree)]
        assert len(bodies) == len(set(bodies)), f"duplicated: {bodies}"

    def test_non_relational_null_predicate_still_succeeds(self, gen):
        """A single-table null predicate must not be misclassified as relational."""
        result = gen.generate("find users where price is null", "postgres")
        assert result.success is True, result.explanation
        assert result.sql is not None
        assert "EXISTS" not in result.sql.upper()
        assert "NOT EXISTS" not in result.sql.upper()

    def test_non_relational_boolean_predicate_still_succeeds(self, gen):
        """A single-table boolean predicate must not be misclassified."""
        result = gen.generate("find users where price = 5 and quantity = 2", "postgres")
        assert result.success is True, result.explanation
        assert "EXISTS" not in result.sql.upper()


# =============================================================================
# G1-B: All-path fail-closed matrix
# =============================================================================

class TestG1B_AllPathFailClosed:
    """Explicit fail-closed contract across every G1-B path category."""

    DIALECTS = ["postgres", "hive", "mysql", "oracle", "tsql", "duckdb"]

    # (text, table_hint) — covers all 7 required path categories.
    @pytest.mark.parametrize(
        "text,table_hint",
        [
            # 1. join_query template path (physical JOIN wording, CN connective)
            ("查询 users 和 invoices 的关联数据", None),
            # 2. normal enhanced fallback (EXISTS wording)
            ("find users who have invoices", None),
            # 3. early boolean/null path (two comparisons → boolean_conditions)
            ("find users who have invoices where price = 1 and quantity = 2", None),
            # 4. early null path (has_explicit_null_predicate)
            ("find users who have invoices where price is null", None),
            # 5. physical JOIN wording (EN)
            ("find users join invoices", None),
            # 6. EXISTS wording + unknown pair
            ("find users who have logs", None),
            # 7. table_hint + unknown relationship
            ("find users who have invoices", "users"),
        ],
    )
    @pytest.mark.parametrize("dialect", DIALECTS)
    def test_fail_closed(self, gen, text, table_hint, dialect):
        result = gen.generate(text, dialect, table_hint=table_hint)
        assert result.success is False, (
            f"unknown relationship must fail closed: {text!r} hint={table_hint!r} [{dialect}]\n"
            f"got sql={result.sql!r}"
        )
        assert result.sql is None
        assert result.confidence == 0.0
        assert "Unable to safely infer" in result.explanation, result.explanation
        assert result.suggestions, "expected non-empty suggestions"
        assert "ON None" not in str(result.sql)

    @pytest.mark.parametrize(
        "text,expected_fk",
        [
            ("find users who have orders", "users.id = orders.user_id"),
            ("find customers with orders", "customers.id = orders.customer_id"),
            ("find users join orders", "users.id = orders.user_id"),
            ("查询 users 和 orders 的关联数据", "users.id = orders.user_id"),
            ("find users without orders", "users.id = orders.user_id"),
            ("find orders with products", "orders.product_id = products.id"),
        ],
    )
    def test_known_pairs_succeed(self, gen, text, expected_fk):
        result = gen.generate(text, "postgres")
        assert result.success is True, result.explanation
        assert result.sql is not None
        assert expected_fk in result.sql, result.sql
        assert result.confidence > 0.0


# =============================================================================
# G1-B known relationship regression
# =============================================================================

class TestG1B_KnownRelationship:
    """Known relationships keep their canonical EXISTS / NOT EXISTS / JOIN."""

    def test_users_have_orders_exists(self, gen):
        result = gen.generate("find users who have orders", "postgres")
        assert result.success is True
        assert result.sql is not None
        assert "users.id = orders.user_id" in result.sql
        tree = sqlglot.parse_one(executable_sql(result), read="postgres")
        assert tree.find(exp.Exists) is not None

    def test_customers_with_orders_exists(self, gen):
        result = gen.generate("find customers with orders", "postgres")
        assert result.success is True
        assert "customers.id = orders.customer_id" in result.sql

    def test_users_without_orders_not_exists(self, gen):
        result = gen.generate("find users without orders", "postgres")
        assert result.success is True
        assert "NOT EXISTS" in result.sql
        assert "users.id = orders.user_id" in result.sql

    def test_known_physical_join_orders(self, gen):
        result = gen.generate("find users join orders", "postgres")
        assert result.success is True
        assert "users.id = orders.user_id" in result.sql
        tree = sqlglot.parse_one(executable_sql(result), read="postgres")
        assert tree.find(exp.Exists) is not None or tree.find(exp.Join) is not None

    def test_known_cn_relation_data_join(self, gen):
        result = gen.generate("查询 users 和 orders 的关联数据", "postgres")
        assert result.success is True
        assert result.sql is not None
        assert "users.id = orders.user_id" in result.sql
        assert "orders" in result.sql

    def test_known_cn_relation_data_join_no_fabricated_fk(self, gen):
        """Known pair: the canonical FK must be the join condition, not a guess."""
        result = gen.generate("查询 users 和 orders 的关联数据", "postgres")
        tree = sqlglot.parse_one(executable_sql(result), read="postgres")
        joins = list(tree.find_all(exp.Join))
        assert joins, "expected a physical JOIN for the known pair"
        for join in joins:
            on = join.args.get("on")
            assert on is not None
            assert "users.id = orders.user_id" in on.sql()


# =============================================================================
# G1 non-relational regression
# =============================================================================

class TestG1_NonRelational:
    """Plain (non-relationship) queries must not be misclassified as joins."""

    @pytest.mark.parametrize(
        "text,expected_table",
        [
            ("find all users", "users"),
            ("find products with price greater than 100", "products"),
            ("calculate average price for products grouped by category", "products"),
            ("show users and products", None),
        ],
    )
    def test_plain_queries_parse(self, gen, text, expected_table):
        result = gen.generate(text, "postgres")
        assert result.success is True
        tree = sqlglot.parse_one(executable_sql(result), result.dialect)
        if expected_table:
            names = {t.name for t in tree.find_all(exp.Table)}
            assert expected_table in names, result.sql
        # 'with price' must be a plain condition, not a relationship join.
        if "with price" in text:
            assert "price" in result.sql

    def test_with_price_is_a_condition_not_a_relation(self, gen):
        """'with price greater than 100' is an ordinary filter, not a relationship."""
        result = gen.generate("find products with price greater than 100", "postgres")
        assert result.success is True
        assert "EXISTS" not in result.sql
        assert "NOT EXISTS" not in result.sql


# =============================================================================
# G1 D2 + D3 interaction regression
# =============================================================================

class TestG1_RelationWithDate:
    """Date predicates must sit inside the relational subquery, once."""

    @pytest.mark.parametrize(
        "text,expected_exists",
        [
            ("find users who have orders from last week", "EXISTS"),
            ("find users who have orders from last 7 days", "EXISTS"),
            ("find users who do not have orders from last month", "NOT EXISTS"),
            ("find users who do not have orders from last year", "NOT EXISTS"),
        ],
    )
    def test_date_in_relation_subquery(self, gen, text, expected_exists):
        result = gen.generate(text, "postgres")
        assert result.success is True
        sql = result.sql
        assert expected_exists in sql
        tree = sqlglot.parse_one(executable_sql(result), read="postgres")

        # The date predicate must live in the EXISTS/NOT EXISTS subquery.
        exists = next(tree.find_all(exp.Exists))
        subquery = exists.this
        assert isinstance(subquery, exp.Select)
        subwhere = list(subquery.find_all(exp.Where))
        assert subwhere, "date condition must be inside the relational subquery"
        assert any(
            re.search(r"CURRENT_DATE|INTERVAL|ADD_MONTHS|DATEADD|SYSDATE", w.this.sql())
            for w in subwhere
        ), f"no date predicate found inside subquery: {sql}"

        # It must not be duplicated at the outer level (single top-level WHERE).
        outer_wheres = where_clauses(tree)
        outer = [w for w in outer_wheres if w.find(exp.Exists) is not None]
        assert len(outer) == 1, f"expected exactly one EXISTS/NOT EXISTS outer WHERE, got {len(outer)}"
        # De-duplicated predicate bodies must stay unique overall.
        assert len(where_clauses(tree)) == len(unique_where_bodies(tree)), sql

    @pytest.mark.parametrize(
        "text,calendar_fragment",
        [
            ("find users who have orders from last month", "INTERVAL '-1 month'"),
            ("find users who do not have orders from last year", "INTERVAL '-12 month'"),
            ("find users who have orders from last 7 weeks", "INTERVAL '49 days'"),
        ],
    )
    def test_relation_date_semantics_preserved(
        self, gen, text, calendar_fragment
    ):
        """Calendar/rolling D3 semantics must survive the relational subquery."""
        result = gen.generate(text, "postgres")
        assert result.success is True
        sql = result.sql
        assert calendar_fragment in sql, f"{text!r}: expected {calendar_fragment!r} in {sql!r}"
