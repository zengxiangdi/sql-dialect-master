"""G3 — Deterministic D3 date-arithmetic runtime evidence.

Proves the D3 semantic contract (rolling day/week windows vs
calendar month/year windows) against actual database execution with
a fixed reference date. No wall-clock token survives into the
executed SQL: the helper substitutes the reference literal before
execution, so results are a pure function of the fixture data.

Engines:
  PostgreSQL 17  — Tier A (native runtime; CI `semantic-runtime` job)
  DuckDB         — Tier A for postgres/duckdb forms;
                   Tier B (compatible-engine surrogate) for the
                   rewritten oracle/tsql forms.
"""

import pytest

duckdb = pytest.importorskip("duckdb")

from backend.core.nl2sql import NL2SQLGenerator
from backend.tests.semantic.d3_runtime_helpers import make_d3_executor

# Fixed reference date for all D3 assertions in this module.
REF_DATE = "2026-09-23"

# Fixture rows: (id, date, category). The categories are the expected
# D3 selection groups for each period, computed against REF_DATE:
#   last 7 days  → 2026-09-16 .. 2026-09-23
#   last 7 weeks → 2026-08-05 .. 2026-09-23 (49-day rolling window)
#   last month   → 2026-08-23 .. 2026-09-23 (1 calendar month)
#   last year    → 2025-09-23 .. 2026-09-23 (12 calendar months)
EVENTS_ROWS = [
    ("u0", "2026-09-20", "in-window"),
    ("u1", "2026-09-22", "in-window"),
    ("u2", "2026-09-23", "in-window"),
    ("u3", "2026-08-13", "rolling-49d"),
    ("u4", "2026-08-14", "rolling-49d"),
    ("u5", "2026-08-25", "in-prev-month"),
    ("u6", "2025-09-25", "in-prev-year"),
    ("u7", "2025-01-01", "out"),
]

# Boundary probe rows: pinned to the exact cutoff day for each period.
# Kept in a separate table (g3_event_boundaries) so they never pollute
# the main fixture's expected category sets.
BOUNDARY_ROWS = [
    ("b1", "2026-09-16", "boundary-7d-in"),
    ("b2", "2026-09-15", "boundary-7d-out"),
    ("b3", "2026-08-05", "boundary-49d-in"),
    ("b4", "2026-08-04", "boundary-49d-out"),
    ("b5", "2026-08-23", "boundary-1mo-in"),
    ("b6", "2026-08-22", "boundary-1mo-out"),
    ("b7", "2025-09-23", "boundary-1yr-in"),
    ("b8", "2025-09-22", "boundary-1yr-out"),
]

# Expected selected categories per D3 period (the fixture rows only;
# boundary rows are handled separately by test_date_boundaries).
EXPECTED_BY_PERIOD = {
    "last 7 days": {"in-window"},
    "last 7 weeks": {"in-window", "rolling-49d", "in-prev-month"},
    "last month": {"in-window", "in-prev-month"},
    "last year": {"in-window", "rolling-49d", "in-prev-month", "in-prev-year"},
}

# Dialects whose generated forms are rewritten into PostgreSQL/DuckDB
# executable interval syntax (Tier B — compatible-engine evidence).
TIER_B_DIALECTS = ("mysql", "oracle", "tsql")
# Dialects whose forms are natively executable as-is (Tier A).
TIER_A_DIALECTS = ("postgres", "duckdb")
ALL_D3_DIALECTS = TIER_A_DIALECTS + TIER_B_DIALECTS


def _make_events_table(connection, engine: str):
    if engine == "postgres":
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
            cur.execute("DROP TABLE IF EXISTS g3_event_boundaries")
            cur.execute(
                """
                CREATE TABLE g3_event_boundaries (
                    id VARCHAR, date DATE, category VARCHAR
                )
                """
            )
            cur.executemany(
                "INSERT INTO g3_event_boundaries VALUES (%s, %s, %s)", BOUNDARY_ROWS
            )
        connection.commit()
    else:
        connection.execute("DROP TABLE IF EXISTS g3_events")
        connection.execute(
            """
            CREATE TABLE g3_events (
                id VARCHAR, date DATE, category VARCHAR
            )
            """
        )
        connection.executemany("INSERT INTO g3_events VALUES (?, ?, ?)", EVENTS_ROWS)
        connection.execute("DROP TABLE IF EXISTS g3_event_boundaries")
        connection.execute(
            """
            CREATE TABLE g3_event_boundaries (
                id VARCHAR, date DATE, category VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO g3_event_boundaries VALUES (?, ?, ?)", BOUNDARY_ROWS
        )


@pytest.fixture(scope="module")
def duckdb_events():
    conn = duckdb.connect(":memory:")
    _make_events_table(conn, "duckdb")
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def postgres_events():
    try:
        import psycopg

        from backend.tests.test_runtime_semantics import POSTGRES_DSN

        conn = psycopg.connect(POSTGRES_DSN)
    except psycopg.OperationalError as exc:
        # Service absence → explicit class-B skip (CI always provides
        # the service; only local runs skip).
        pytest.skip(f"PostgreSQL runtime database unavailable: {exc}")
    try:
        _make_events_table(conn, "postgres")
        yield conn
    finally:
        conn.close()


def _categories(rows):
    return {row[2] for row in rows}


class TestD3DeterministicDateArithmetic:
    """D3 rolling vs calendar-month semantics, executed against
    deterministic fixture data under a fixed reference date."""

    @pytest.mark.parametrize("period", list(EXPECTED_BY_PERIOD))
    @pytest.mark.parametrize("dialect", TIER_A_DIALECTS)
    def test_d3_native_forms_execute_correctly(
        self, period, dialect, duckdb_events
    ):
        """Tier A: the generated form, executed as-is, selects exactly
        the expected rows. Proves native postgres/duckdb date
        arithmetic, not just that a date function appears."""
        gen = NL2SQLGenerator()
        result = gen.generate(period, dialect, table_hint="g3_events")
        assert result.success, result.explanation
        execute_d3 = make_d3_executor(REF_DATE)
        rows, err = execute_d3(duckdb_events, result.sql, dialect)
        assert err is None, f"DuckDB could not execute {dialect} form: {err}\n{result.sql}"
        assert _categories(rows) == EXPECTED_BY_PERIOD[period], (
            f"{period} / {dialect}: selected {_categories(rows)}, "
            f"expected {EXPECTED_BY_PERIOD[period]}\n{result.sql}"
        )

    @pytest.mark.parametrize("period", list(EXPECTED_BY_PERIOD))
    @pytest.mark.parametrize("dialect", TIER_A_DIALECTS)
    def test_d3_native_postgres_runtime(
        self, period, dialect, postgres_events
    ):
        """Tier A on PostgreSQL: the same execution against the native
        engine. Proves PostgreSQL-native date arithmetic for the
        postgres/duckdb forms."""
        gen = NL2SQLGenerator()
        result = gen.generate(period, dialect, table_hint="g3_events")
        assert result.success, result.explanation
        execute_d3 = make_d3_executor(REF_DATE)
        rows, err = execute_d3(postgres_events, result.sql, dialect, engine="postgres")
        assert err is None, f"PostgreSQL could not execute {dialect} form: {err}\n{result.sql}"
        assert _categories(rows) == EXPECTED_BY_PERIOD[period]

    @pytest.mark.parametrize("period", list(EXPECTED_BY_PERIOD))
    @pytest.mark.parametrize("dialect", TIER_B_DIALECTS)
    def test_d3_compatible_engine_surrogate(
        self, period, dialect, duckdb_events
    ):
        """Tier B: mysql/oracle/tsql generated forms are rewritten into
        an interval form a compatible engine can execute. This proves
        the *semantic shape* (correct boundary values) of the
        arithmetic under a surrogate engine — it does NOT prove the
        target engine's own native execution, and must not be cited
        as such."""
        gen = NL2SQLGenerator()
        result = gen.generate(period, dialect, table_hint="g3_events")
        assert result.success, result.explanation
        execute_d3 = make_d3_executor(REF_DATE)
        rows, err = execute_d3(duckdb_events, result.sql, dialect)
        assert err is None, (
            f"DuckDB surrogate could not execute {dialect} form: {err}\n{result.sql}"
        )
        assert _categories(rows) == EXPECTED_BY_PERIOD[period]

    def test_rolling_window_is_wider_than_calendar_month(self, duckdb_events):
        """The core D3 distinction: 7 weeks (49 days) is a rolling window
        that reaches further back than one calendar month. On the
        reference date the 49-day window includes the previous month,
        while the calendar-month window ends at the same day of the
        previous month. This asserts the two selections differ in
        exactly the way the D3 contract requires."""
        gen = NL2SQLGenerator()
        execute_d3 = make_d3_executor(REF_DATE)
        weeks_sql = gen.generate("last 7 weeks", "postgres", table_hint="g3_events").sql
        month_sql = gen.generate("last month", "postgres", table_hint="g3_events").sql
        weeks_rows, _ = execute_d3(duckdb_events, weeks_sql, "postgres")
        month_rows, _ = execute_d3(duckdb_events, month_sql, "postgres")
        weeks_set, month_set = _categories(weeks_rows), _categories(month_rows)
        # 49-day window reaches into the previous month; calendar month does not.
        assert "in-prev-month" in weeks_set
        # 2026-08-25 is 2 days inside the 1-month window (cutoff 2026-08-23),
        # so the calendar-month window DOES include it — but only because the
        # reference date is near month-end. The distinguishing proof is that
        # the 49-day window ALSO includes rows from early August that the
        # calendar window excludes:
        early_august = "rolling-49d"
        assert early_august in weeks_set
        assert early_august not in month_set
        # Both windows contain the current-month rows.
        assert "in-window" in weeks_set and "in-window" in month_set

    def test_rolling_window_is_wider_than_calendar_year(self, duckdb_events):
        """Same distinction at the year scale: the calendar-year window
        reaches back past the 49-day rolling window; conversely the
        49-day window does not reach back into the previous year."""
        gen = NL2SQLGenerator()
        execute_d3 = make_d3_executor(REF_DATE)
        year_sql = gen.generate("last year", "postgres", table_hint="g3_events").sql
        weeks_sql = gen.generate("last 7 weeks", "postgres", table_hint="g3_events").sql
        year_rows, year_err = execute_d3(duckdb_events, year_sql, "postgres")
        weeks_rows, weeks_err = execute_d3(duckdb_events, weeks_sql, "postgres")
        assert year_err is None and weeks_err is None
        year_set, weeks_set = _categories(year_rows), _categories(weeks_rows)
        assert "in-prev-year" in year_set
        assert "in-prev-year" not in weeks_set
        # The 49-day window ends inside the current month; it cannot
        # reach back to 2025-09-25.
        assert "in-prev-month" in weeks_set

    def test_date_boundaries_exact(self, duckdb_events):
        """Boundary rows pin the exact cutoff for each period on the
        reference date: day-before-window is excluded, first-day-of-
        window is included, for all four periods."""
        gen = NL2SQLGenerator()
        execute_d3 = make_d3_executor(REF_DATE)

        def selected(period_text, table="g3_events"):
            sql = gen.generate(period_text, "postgres", table_hint=table).sql
            rows, err = execute_d3(duckdb_events, sql, "postgres")
            assert err is None
            # normalise to ISO strings so comparisons work across engines
            return {str(row[1]) for row in rows}

        last_7d = selected("last 7 days", "g3_event_boundaries")
        last_7w = selected("last 7 weeks", "g3_event_boundaries")
        last_month = selected("last month", "g3_event_boundaries")
        last_year = selected("last year", "g3_event_boundaries")

        # 7-day window: REF - 7 days = 2026-09-16
        assert "2026-09-16" in last_7d
        assert "2026-09-15" not in last_7d
        # 49-day window: REF - 49 days = 2026-08-05
        assert "2026-08-05" in last_7w
        assert "2026-08-04" not in last_7w
        # 1 calendar month: REF - 1 month = 2026-08-23
        assert "2026-08-23" in last_month
        assert "2026-08-22" not in last_month
        # 12 calendar months: REF - 12 months = 2025-09-23
        assert "2025-09-23" in last_year
        assert "2025-09-22" not in last_year
