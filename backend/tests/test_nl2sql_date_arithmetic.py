"""D3: Regression tests for NL2SQL date arithmetic across dialects.

Semantic contract:
  today       → = CURRENT_DATE
  yesterday   → = CURRENT_DATE - 1 day
  tomorrow    → = CURRENT_DATE + 1 day
  last N days → >= CURRENT_DATE - N days (rolling)
  last N weeks → >= CURRENT_DATE - N×7 days (rolling)
  last N months → ADD_MONTHS(CURRENT_DATE, -N) (calendar-relative)
  last N years  → ADD_MONTHS(CURRENT_DATE, -N×12) (calendar-relative)
  last week   → >= DATE_SUB(CURRENT_DATE, 7) (rolling 7-day window)
  last month  → ADD_MONTHS(CURRENT_DATE, -1) (previous calendar month)
  last year   → ADD_MONTHS(CURRENT_DATE, -12) (previous calendar year)
"""
from __future__ import annotations

import pytest

from backend.core.nl2sql import NL2SQLGenerator


@pytest.fixture
def gen():
    return NL2SQLGenerator()


DIALECTS = ["postgres", "mysql", "oracle", "tsql", "duckdb"]


# ── today ──────────────────────────────────────────────────────────────────

class TestToday:
    def test_today_generates_current_date(self, gen):
        r = gen.generate("today", "postgres")
        assert r.success
        assert "CURRENT_DATE" in r.sql

    @pytest.mark.parametrize("dialect", DIALECTS)
    def test_today_dialect_adjustment(self, gen, dialect):
        r = gen.generate("today", dialect)
        assert r.success
        # Each dialect has its own canonical form
        if dialect == "oracle":
            assert "TRUNC(SYSDATE)" in r.sql
        elif dialect == "tsql":
            assert "GETDATE()" in r.sql
        else:
            assert "CURRENT_DATE" in r.sql


# ── yesterday ──────────────────────────────────────────────────────────────

class TestYesterday:
    def test_yesterday_generates_date_clause(self, gen):
        r = gen.generate("yesterday", "postgres")
        assert r.success
        assert "CURRENT_DATE" in r.sql
        assert "INTERVAL" in r.sql or "DATE_SUB" in r.sql or "DATEADD" in r.sql or "TRUNC" in r.sql

    @pytest.mark.parametrize("dialect", DIALECTS)
    def test_yesterday_dialect(self, gen, dialect):
        r = gen.generate("yesterday", dialect)
        assert r.success
        assert "WHERE" in r.sql.upper()


# ── tomorrow (NEW — was missing) ──────────────────────────────────────────

class TestTomorrow:
    def test_tomorrow_postgres(self, gen):
        r = gen.generate("tomorrow", "postgres")
        assert r.success
        assert "CURRENT_DATE" in r.sql
        assert "+" in r.sql  # future direction

    def test_tomorrow_mysql(self, gen):
        r = gen.generate("tomorrow", "mysql")
        assert r.success
        assert "CURRENT_DATE" in r.sql

    def test_tomorrow_oracle(self, gen):
        r = gen.generate("tomorrow", "oracle")
        assert r.success
        assert "TRUNC(SYSDATE)" in r.sql or "SYSDATE" in r.sql


# ── last N days ────────────────────────────────────────────────────────────

class TestLastNDays:
    @pytest.mark.parametrize("dialect", DIALECTS)
    def test_last_7_days(self, gen, dialect):
        r = gen.generate("last 7 days", dialect)
        assert r.success
        assert "CURRENT_DATE" in r.sql or "SYSDATE" in r.sql or "GETDATE()" in r.sql

    @pytest.mark.parametrize("dialect", DIALECTS)
    def test_last_30_days(self, gen, dialect):
        r = gen.generate("last 30 days", dialect)
        assert r.success
        assert "CURRENT_DATE" in r.sql or "SYSDATE" in r.sql or "GETDATE()" in r.sql

    def test_last_7_days_postgres_syntax(self, gen):
        r = gen.generate("last 7 days", "postgres")
        assert r.success
        assert "INTERVAL" in r.sql

    def test_last_7_days_mysql_syntax(self, gen):
        r = gen.generate("last 7 days", "mysql")
        assert r.success
        assert "INTERVAL" in r.sql or "DATE_SUB" in r.sql

    def test_last_7_days_oracle_syntax(self, gen):
        r = gen.generate("last 7 days", "oracle")
        assert r.success
        assert "TRUNC(SYSDATE)" in r.sql


# ── last week (REGRESSION: previously produced no date clause) ────────────

class TestLastWeek:
    def test_last_week_generates_date_clause(self, gen):
        """Regression: 'last week' must produce a WHERE clause."""
        r = gen.generate("last week", "postgres")
        assert r.success
        assert "WHERE" in r.sql.upper()

    def test_last_week_has_current_date(self, gen):
        r = gen.generate("last week", "postgres")
        assert r.success
        assert "CURRENT_DATE" in r.sql

    @pytest.mark.parametrize("dialect", DIALECTS)
    def test_last_week_dialect(self, gen, dialect):
        r = gen.generate("last week", dialect)
        assert r.success
        assert "WHERE" in r.sql.upper()
        assert "CURRENT_DATE" in r.sql or "SYSDATE" in r.sql or "GETDATE()" in r.sql


# ── last month (REGRESSION: previously produced no date clause) ────────────

class TestLastMonth:
    def test_last_month_generates_date_clause(self, gen):
        r = gen.generate("last month", "postgres")
        assert r.success
        assert "WHERE" in r.sql.upper()

    def test_last_month_postgres(self, gen):
        r = gen.generate("last month", "postgres")
        assert r.success
        assert "CURRENT_DATE" in r.sql

    def test_last_month_oracle(self, gen):
        r = gen.generate("last month", "oracle")
        assert r.success
        assert "ADD_MONTHS" in r.sql or "TRUNC(SYSDATE)" in r.sql


# ── last year (REGRESSION: previously produced no date clause) ─────────────

class TestLastYear:
    def test_last_year_generates_date_clause(self, gen):
        r = gen.generate("last year", "postgres")
        assert r.success
        assert "WHERE" in r.sql.upper()

    def test_last_year_postgres(self, gen):
        r = gen.generate("last year", "postgres")
        assert r.success
        assert "CURRENT_DATE" in r.sql


# ── with table hint ────────────────────────────────────────────────────────

class TestDateWithTable:
    def test_last_7_days_with_table_hint(self, gen):
        r = gen.generate("find users from last 7 days", "postgres", table_hint="users")
        assert r.success
        assert "FROM users" in r.sql
        assert "CURRENT_DATE" in r.sql

    def test_last_week_with_table_hint(self, gen):
        """Regression: 'find users from last week' must include WHERE clause."""
        r = gen.generate("find users from last week", "postgres", table_hint="users")
        assert r.success
        assert "FROM users" in r.sql
        assert "WHERE" in r.sql.upper()

    def test_today_with_table_hint(self, gen):
        r = gen.generate("show users from today", "postgres", table_hint="users")
        assert r.success
        assert "FROM users" in r.sql
        assert "CURRENT_DATE" in r.sql


# ── edge cases ─────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_last_1_day(self, gen):
        r = gen.generate("last 1 day", "postgres")
        assert r.success
        assert "CURRENT_DATE" in r.sql

    def test_last_90_days(self, gen):
        r = gen.generate("last 90 days", "postgres")
        assert r.success
        assert "CURRENT_DATE" in r.sql

    def test_last_365_days(self, gen):
        r = gen.generate("last 365 days", "postgres")
        assert r.success
        assert "CURRENT_DATE" in r.sql
