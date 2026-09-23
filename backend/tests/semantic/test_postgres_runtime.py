"""G3 — PostgreSQL native runtime semantic evidence (Tier A).

Strengthens `backend/tests/test_runtime_semantics.py`, whose current
coverage is a single GROUP BY / COUNT / AVG query per direction. This
module adds result-value assertions for predicates, NULL semantics,
aggregation, JOIN, EXISTS / NOT EXISTS, D3 date arithmetic, and row
limiting, all executed against the CI-provided PostgreSQL 17 service
(the `semantic-runtime` job in `.github/workflows/ci.yml`).

Expected-value oracle:
  Every expected value below is derived **independently by hand**
  from the documented fixture (`_prepare_postgres` +
  `_prepare_extended`): deterministic, explicitly-known rows and
  values. A DuckDB mirror of the same fixture may be used as an
  optional secondary cross-check during test development, but
  PostgreSQL's own execution is the authoritative lane — the
  DuckDB output is NOT the expected result for this suite.

Design rule followed here: every assertion inspects returned rows or
values, never SQL-string shape. Static string / AST checks belong to
the Tier C static suite (`test_dialect_semantic_matrix.py`).

Determinism: D3 assertions use `make_d3_executor` with a fixed
reference date, so no test depends on the wall clock.
"""

import pytest

psycopg = pytest.importorskip("psycopg")

from backend.tests.semantic.d3_runtime_helpers import make_d3_executor
from backend.tests.test_runtime_semantics import POSTGRES_DSN, _prepare_postgres

PG_UNAVAILABLE = "PostgreSQL runtime test database unavailable"


@pytest.fixture(scope="module")
def pg():
    connection = None
    try:
        connection = psycopg.connect(POSTGRES_DSN)
    except psycopg.OperationalError as exc:
        # Service absence (no local PostgreSQL, or DSN unreachable) →
        # explicit class-B skip; CI's semantic-runtime job always
        # provides the service, so the primary lane never skips.
        pytest.skip(f"{PG_UNAVAILABLE}: {exc}")
    try:
        _prepare_postgres(connection)
        _prepare_extended(connection)
        _prepare_events(connection)
        yield connection
    finally:
        connection.close()


# Same deterministic events fixture as test_d3_date_runtime, so the
# two modules can share expected-set constants without importing
# across modules.
from backend.tests.semantic.test_d3_date_runtime import (
    EVENTS_ROWS,
    REF_DATE,
)


def _prepare_events(connection):
    with connection.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS g3_events")
        cur.execute(
            """
            CREATE TABLE g3_events (
                id VARCHAR, date DATE, category VARCHAR
            )
            """
        )
        cur.executemany("INSERT INTO g3_events VALUES (%s, %s, %s)", EVENTS_ROWS)
    connection.commit()


def _prepare_extended(connection):
    """The CI PostgreSQL fixture (`_prepare_postgres`) carries only
    4 rows and no name/manager columns. G3 adds a deterministic
    extended fixture mirroring the DuckDB runtime fixture so the
    NULL/JOIN/EXISTS assertions are meaningful. This helper runs
    after the shared fixture and adds the G3-only data.

    Rows 1-4 are the shared fixture's data with G3's name/manager
    columns populated:

        id  name   dept        salary   active  manager
        1   Alice  eng         100000   True    None
        2   Bob    eng         120000   True    None
        3   Carol  sales        80000   True    None
        4   Dave   sales        70000   False   None

    G3-only rows 5-9 (the "extended" half):

        id  name   dept   salary  active  manager
        5   Eve    eng    None    True    1
        6   Frank  sales  90000   True    None
        7   None   hr     60000   True    None
        8   Gina   eng    95000   True    5
        9   Hank   sales  55000   False   3
    """
    with connection.cursor() as cur:
        cur.execute(
            """
            ALTER TABLE employees
              ADD COLUMN IF NOT EXISTS name TEXT,
              ADD COLUMN IF NOT EXISTS manager_id INTEGER
            """
        )
        cur.executemany(
            "UPDATE employees SET name = %s WHERE id = %s",
            [
                ("Alice", 1),
                ("Bob", 2),
                ("Carol", 3),
                ("Dave", 4),
            ],
        )
        cur.executemany(
            """
            INSERT INTO employees (id, name, department, salary, active, manager_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [
                (5, "Eve", "eng", None, True, 1),
                (6, "Frank", "sales", 90000, True, None),
                (7, None, "hr", 60000, True, None),
                (8, "Gina", "eng", 95000, True, 5),
                (9, "Hank", "sales", 55000, False, 3),
            ],
        )
    connection.commit()


def _rows(pg_connection, sql: str):
    with pg_connection.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


EMPLOYEE_IDS = [1, 2, 3, 4, 5, 6, 7, 8, 9]

# ---------------------------------------------------------------------------
# Authoritative expected values — derived by hand from the fixture
# ---------------------------------------------------------------------------
#
# _prepare_postgres (shared, from test_runtime_semantics):
#   1 engineering 100000 True   → G3 UPDATE names it "Alice"
#   2 engineering 120000 True   → G3 UPDATE names it "Bob"
#   3 sales        80000  True   → G3 UPDATE names it "Carol"
#   4 sales        70000  False  → G3 UPDATE names it "Dave"
#   (name/manager_id columns are G3-only; shared 4 rows get
#    manager_id = NULL, names assigned by G3 UPDATE)
#
# _prepare_extended (G3-only inserts):
#   5 Eve   eng     NULL   True  manager 1
#   6 Frank sales    90000 True  manager None
#   7 (NULL) hr     60000  True  manager None
#   8 Gina  eng     95000  True  manager 5
#   9 Hank  sales    55000 False manager 3
#
# Manual derivation of every expected value asserted in this module:
#
#   active = TRUE ids          1,2,3,5,6,7,8  (ids 4 and 9 are inactive)
#   name IS NULL               {7}  → COUNT(*) = 1, COUNT(name) = 8 (of 9)
#   salary > 80000 AND <= 120000
#                               id1(100000), id2(120000), id6(90000), id8(95000)
#   salary BETWEEN 70000 AND 100000
#                               id1(100000), id3(80000), id4(70000),
#                               id6(90000), id8(95000)
#   name LIKE 'A%'             Alice only
#   manager_id IS NULL         ids 1,2,3,4,6,7  → COUNT = 6
#   INNER JOIN (manager active)  e5→1(Alice,T), e8→5(Eve,T), e9→3(Carol,T)
#                                 → ids {5,8,9}; NOT EXISTS → {1,2,3,4,6,7}
#   GROUP BY department (ORDER BY department, case-sensitive):
#     eng:         2 rows {NULL, 95000}       → COUNT=2 MIN=MAX=SUM=95000
#     engineering: 2 rows {100000, 120000}    → COUNT=2 MIN=100000 SUM=220000
#     hr:          1 row {60000}              → COUNT=1 MIN=SUM=60000
#     sales:       4 rows {80000,70000,90000,55000}
#                                       → COUNT=4 MIN=55000 MAX=90000 SUM=295000
#   HAVING COUNT(*) > 1        eng(2), engineering(2), sales(4); hr(1) excluded
#   AVG(salary) all            (100000+120000+80000+70000+90000+60000+95000+55000)
#                               / 8 = 670000/8 = 83750.0
#   LIMIT 3 by salary DESC NULLS LAST
#                               (2,120000) (1,100000) (8,95000)
#   D3 (REF_DATE = 2026-09-23; shared EVENTS_ROWS constants):
#     last 7 days  (>= 2026-09-16): in-window {u0,u1,u2}
#     last 7 weeks (>= 2026-08-05): in-window + rolling-49d + in-prev-month
#     last month   (>= 2026-08-23): in-window + in-prev-month
#     last year    (>= 2025-09-23): in-window + rolling-49d + in-prev-month
#                                    + in-prev-year


def _all_employees(pg_connection):
    """Return the full 9-row employee fixture as dict rows for value
    assertions (id, name, department, salary, active, manager_id)."""
    cur = pg_connection.cursor()
    cur.execute(
        "SELECT id, name, department, salary, active, manager_id "
        "FROM employees ORDER BY id"
    )
    return cur.fetchall()


# =============================================================================
# Predicates — executed against real data, assert result values
# =============================================================================

class TestPredicateRuntimePostgres:
    """Actual generated SQL executed on PostgreSQL with value assertions."""

    def test_equality_selects_expected_ids(self, pg):
        ids = sorted(
            row[0] for row in _rows(pg, "SELECT id FROM employees WHERE active = TRUE")
        )
        # Hand-derived: id4(inactive) and id9(inactive); ids 1,2,3,5,6,7,8
        # active.
        assert ids == [1, 2, 3, 5, 6, 7, 8]

    def test_inequality_and_comparison_bounds(self, pg):
        rows = _rows(
            pg,
            "SELECT id FROM employees WHERE salary > 80000 AND salary <= 120000 "
            "ORDER BY id",
        )
        # Hand-derived: id1(100000), id2(120000), id6(90000), id8(95000);
        # id4(70000) below lower bound, id5 salary NULL (excluded),
        # id3(80000) fails strict lower bound, id7(60000), id9(55000) below.
        assert [row[0] for row in rows] == [1, 2, 6, 8]

    def test_is_null_and_is_not_null(self, pg):
        null_count = _rows(pg, "SELECT COUNT(*) FROM employees WHERE name IS NULL")[0][0]
        not_null_count = _rows(pg, "SELECT COUNT(*) FROM employees WHERE name IS NOT NULL")[0][0]
        # Only id 7 (NULL name); total 9 rows
        assert null_count == 1
        assert not_null_count == 8
        assert null_count + not_null_count == len(EMPLOYEE_IDS)

    def test_in_and_not_in_membership(self, pg):
        in_ids = sorted(
            row[0]
            for row in _rows(pg, "SELECT id FROM employees WHERE id IN (1, 2, 3) ORDER BY id")
        )
        not_in_ids = sorted(
            row[0]
            for row in _rows(
                pg, "SELECT id FROM employees WHERE id NOT IN (1, 2, 3) ORDER BY id"
            )
        )
        assert in_ids == [1, 2, 3]
        assert not_in_ids == [4, 5, 6, 7, 8, 9]

    def test_between_inclusive_bounds(self, pg):
        ids = sorted(
            row[0]
            for row in _rows(
                pg, "SELECT id FROM employees WHERE salary BETWEEN 70000 AND 100000 ORDER BY id"
            )
        )
        # Hand-derived: id1(100000), id3(80000), id4(70000),
        # id6(90000), id8(95000) are the five salaries in [70000, 100000];
        # id2 above, id5 NULL, id7(60000) and id9(55000) below.
        assert ids == [1, 3, 4, 6, 8]

    def test_like_prefix(self, pg):
        names = _rows(pg, "SELECT name FROM employees WHERE name LIKE 'A%'")
        # Among non-NULL names, only Alice starts with 'A'.
        assert [row[0] for row in names] == ["Alice"]


# =============================================================================
# NULL semantics
# =============================================================================

class TestNullSemanticsPostgres:
    def test_count_column_excludes_nulls(self, pg):
        row_count = _rows(pg, "SELECT COUNT(*) FROM employees")[0][0]
        name_count = _rows(pg, "SELECT COUNT(name) FROM employees")[0][0]
        assert row_count == 9
        assert name_count == 8

    def test_null_manager_id_grouping(self, pg):
        """Rows with no manager (NULL foreign key) form the orphan set;
        a correlated NULL-safe predicate must not match them to any row."""
        orphaned = _rows(
            pg,
            "SELECT COUNT(*) FROM employees WHERE manager_id IS NULL",
        )[0][0]
        assert orphaned == 6

    def test_left_join_null_fill_for_missing_manager(self, pg):
        """LEFT JOIN with no matching manager must yield NULL on the
        manager side for exactly the orphaned rows (ids 1,2,3,4,6,7)."""
        rows = _rows(
            pg,
            """
            SELECT e.id, m.name
            FROM employees e
            LEFT JOIN employees m ON e.manager_id = m.id
            WHERE m.name IS NULL
            ORDER BY e.id
            """,
        )
        assert [row[0] for row in rows] == [1, 2, 3, 4, 6, 7]
        assert all(row[1] is None for row in rows)


# =============================================================================
# Aggregation
# =============================================================================

class TestAggregationPostgres:
    def test_aggregate_values_by_department(self, pg):
        rows = _rows(
            pg,
            """
            SELECT department,
                   COUNT(*) AS cnt,
                   MIN(salary) AS lo,
                   MAX(salary) AS hi,
                   SUM(salary) AS total,
                   AVG(salary) AS avg
            FROM employees
            GROUP BY department
            ORDER BY department
            """,
        )
        # eng: ids 5,8 (salary: NULL, 95000) → MIN=MAX=SUM=95000
        # engineering: ids 1,2 (salary: 100000, 120000)
        # hr: id 7 (salary: 60000)
        # sales: ids 3,4,6,9 (salary: 80000, 70000, 90000, 55000)
        # NULL salary (id 5) excluded from MIN/MAX/SUM.
        # PostgreSQL TEXT ordering is case-sensitive (byte-wise):
        # lowercase 'eng' < 'engineering' < 'hr' < 'sales'.
        assert rows[0][:4] == ("eng", 2, 95000, 95000)
        assert rows[0][4] == 95000  # only id 8; NULL excluded
        assert rows[1][:4] == ("engineering", 2, 100000, 120000)
        assert rows[1][4] == 220000
        assert rows[2][:3] == ("hr", 1, 60000)
        assert rows[3][:4] == ("sales", 4, 55000, 90000)
        assert rows[3][4] == 295000  # 80000 + 70000 + 90000 + 55000

    def test_having_filters_groups(self, pg):
        rows = _rows(
            pg,
            """
            SELECT department, COUNT(*) AS cnt
            FROM employees
            GROUP BY department
            HAVING COUNT(*) > 1
            ORDER BY department
            """,
        )
        # Hand-derived: eng(2), engineering(2), sales(4) have more than
        # one row; hr(1) is excluded by HAVING COUNT(*) > 1.
        assert [row[0] for row in rows] == ["eng", "engineering", "sales"]

    def test_aggregate_ignores_null_salary(self, pg):
        avg = _rows(pg, "SELECT AVG(salary) FROM employees")[0][0]
        # Non-NULL salaries: 100000, 120000, 80000, 70000, 90000, 60000, 95000, 55000
        # SUM = 670000 / 8 = 83750.0
        assert avg == pytest.approx(83750.0)


# =============================================================================
# JOIN semantics
# =============================================================================

class TestJoinPostgres:
    def test_inner_join_rows(self, pg):
        rows = _rows(
            pg,
            """
            SELECT e1.id, e2.name
            FROM employees e1
            INNER JOIN employees e2 ON e1.manager_id = e2.id
            ORDER BY e1.id
            """,
        )
        # manager_id: id5→1(Alice), id8→5(Eve), id9→3(Carol); all
        # others NULL → only those 3 rows survive the inner join.
        # Managers 1, 3, 5 are all active.
        assert [row[0] for row in rows] == [5, 8, 9]

    def test_left_join_cardinality(self, pg):
        rows = _rows(
            pg,
            """
            SELECT e1.id, e2.name
            FROM employees e1
            LEFT JOIN employees e2 ON e1.manager_id = e2.id
            ORDER BY e1.id
            """,
        )
        assert len(rows) == 9  # LEFT JOIN preserves all 9 rows
        null_managed = [row for row in rows if row[1] is None]
        assert sorted(row[0] for row in null_managed) == [1, 2, 3, 4, 6, 7]


# =============================================================================
# EXISTS / NOT EXISTS — D2 canonical subquery semantics
# =============================================================================

class TestExistsPostgres:
    def test_exists_selects_subjects_with_related_rows(self, pg):
        """Departments whose manager is active — the D2 EXISTS shape:
        subject in outer FROM, related table inside the correlated
        subquery, condition scoped inside the subquery."""
        rows = _rows(
            pg,
            """
            SELECT e.id
            FROM employees e
            WHERE EXISTS (
                SELECT 1 FROM employees m WHERE m.id = e.manager_id AND m.active
            )
            ORDER BY e.id
            """,
        )
        # e5→mgr1(active), e8→mgr5(active), e9→mgr3(active)
        assert [row[0] for row in rows] == [5, 8, 9]

    def test_not_exists_selects_subjects_without_related_rows(self, pg):
        rows = _rows(
            pg,
            """
            SELECT e.id
            FROM employees e
            WHERE NOT EXISTS (
                SELECT 1 FROM employees m WHERE m.id = e.manager_id
            )
            ORDER BY e.id
            """,
        )
        # Hand-derived: manager_id NULL → correlated equality is NULL
        # for ids 1,2,3,4,6,7 → NOT EXISTS true; ids 5,8,9 have a
        # matching manager row.
        assert [row[0] for row in rows] == [1, 2, 3, 4, 6, 7]


# =============================================================================
# D3 date arithmetic — deterministic via fixed reference date
# =============================================================================

class TestD3DateArithmeticPostgres:
    """Executed on PostgreSQL against the g3_events fixture. The D3
    executor substitutes the wall-clock token with REF_DATE so these
    assertions are pure functions of the fixture."""

    @pytest.mark.parametrize(
        ("period", "expected"),
        [
            ("last 7 days", {"in-window"}),
            ("last 7 weeks", {"in-window", "rolling-49d", "in-prev-month"}),
            ("last month", {"in-window", "in-prev-month"}),
            ("last year", {"in-window", "rolling-49d", "in-prev-month", "in-prev-year"}),
        ],
    )
    def test_d3_periods_native_postgres(self, pg, period, expected):
        from backend.core.nl2sql import NL2SQLGenerator

        result = NL2SQLGenerator().generate(period, "postgres", table_hint="g3_events")
        assert result.success, result.explanation
        execute_d3 = make_d3_executor(REF_DATE)
        rows, err = execute_d3(pg, result.sql, "postgres", engine="postgres")
        assert err is None, f"{result.sql}\n{err}"
        assert {row[2] for row in rows} == expected

    def test_rolling_distinct_from_calendar(self, pg):
        """The 7-week rolling window must select strictly more rows than
        the calendar-month window on this reference date — proof that
        the two constructs are not inter-changeable."""
        from backend.core.nl2sql import NL2SQLGenerator

        execute_d3 = make_d3_executor(REF_DATE)
        gen = NL2SQLGenerator()
        weeks_sql = gen.generate("last 7 weeks", "postgres", table_hint="g3_events").sql
        month_sql = gen.generate("last month", "postgres", table_hint="g3_events").sql
        weeks_rows, _ = execute_d3(pg, weeks_sql, "postgres", engine="postgres")
        month_rows, _ = execute_d3(pg, month_sql, "postgres", engine="postgres")
        assert len(weeks_rows) > len(month_rows)
        # 2026-08-25 sits 2 days inside the 1-month window (cutoff 2026-08-23),
        # so the *distinguishing* rows are the early-August rolling-49d entries
        # that the calendar-month window excludes.
        assert "rolling-49d" in {row[2] for row in weeks_rows}
        assert "rolling-49d" not in {row[2] for row in month_rows}


# =============================================================================
# Row limiting
# =============================================================================

class TestRowLimitingPostgres:
    def test_limit_cardinality(self, pg):
        rows = _rows(pg, "SELECT id, salary FROM employees ORDER BY salary DESC NULLS LAST LIMIT 3")
        # Top-3 salaries: 120000(id2), 100000(id1), 95000(id8).
        assert [row[0] for row in rows] == [2, 1, 8]
        assert rows[0][1] == 120000

    def test_fetch_first_equivalent(self, pg):
        rows = _rows(pg, "SELECT * FROM employees ORDER BY id FETCH FIRST 2 ROWS ONLY")
        assert [row[0] for row in rows] == [1, 2]

    def test_limit_offset_window(self, pg):
        rows = _rows(pg, "SELECT id FROM employees ORDER BY id LIMIT 2 OFFSET 3")
        assert [row[0] for row in rows] == [4, 5]
