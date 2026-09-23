"""Runtime semantic evidence helpers for G3.

Tier A / Tier B evidence boundary:

  Tier A — Native runtime verified
    PostgreSQL 17 (CI `semantic-runtime` job) and DuckDB (in-process)
    are the two engines where target SQL is actually executed and
    result values asserted.

  Tier B — Runtime-equivalent verification
    DuckDB is also used as a compatible execution surrogate for
    constructs whose target engine is unavailable in CI (e.g. T-SQL
    DATEADD rendered to PostgreSQL interval syntax). The surrogate
    must NOT be presented as proof of the target engine's own
    behaviour — it proves the semantic shape of the construct under
    a compatible engine.

  Tier C — Static-only
    The remaining ten supported dialects (hive, spark, trino, snowflake,
    redshift, clickhouse, databricks, oracle, tsql native) have no
    executable CI engine. For these, evidence is limited to sqlglot
    parse + transpile + structural-diff assertions.

Date determinism:
  All D3 (NL2SQL date-arithmetic) runtime tests substitute the
  wall-clock token (CURRENT_DATE / SYSDATE / GETDATE()) with a
  fixed reference literal (D3_FIXED_REFERENCE in the test module)
  BEFORE execution, so results depend only on the fixture data and
  the reference date, never on the calendar day the test runs.
"""

import re

from backend.tests.semantic.runtime_helpers import execute_or_skip

# Wall-clock tokens that D3 generation inserts and that must be
# replaced with a fixed reference literal for deterministic execution.
_D3_WALL_CLOCK_TOKENS = (
    r"\bCURRENT_DATE\b",
    r"\bSYSDATE\b",
    r"\bGETDATE\(\)",
)


def make_d3_executor(fixed_reference: str):
    """Return a function that executes D3-generated SQL deterministically.

    The returned callable takes (connection, sql, source_dialect) and
    returns (rows, error) like execute_or_skip, but with all wall-clock
    tokens replaced by `fixed_reference` first, and dialect-specific
    date functions rewritten into a PostgreSQL-compatible form when
    the execution engine is DuckDB.
    """
    import sqlglot
    from sqlglot.errors import ParseError, TokenError

    def _to_executable(sql: str, dialect: str) -> str:
        sql = sql.replace("-- Generated for " + dialect.upper(), "").lstrip()
        # 1. Replace wall-clock tokens with the fixed reference literal.
        for token in _D3_WALL_CLOCK_TOKENS:
            sql = re.sub(token, f"CAST('{fixed_reference}' AS DATE)", sql)
        # 2. Unwrap Oracle TRUNC(CAST(...)) wrapper.
        sql = re.sub(
            r"TRUNC\(\s*CAST\('([0-9-]{10})' AS DATE\)\s*\)",
            lambda m: f"CAST('{m.group(1)}' AS DATE)",
            sql,
            flags=re.IGNORECASE,
        )
        # 3. Render to PostgreSQL via sqlglot, then rewrite Oracle/T-SQL
        #    function forms that PostgreSQL/DuckDB do not recognise.
        out = sqlglot.parse_one(sql, read=dialect).sql(dialect="postgres")
        out = re.sub(r"(?i)DATEADD\(\s*DAY\s*,\s*(-?\d+)\s*,\s*(\S+)\s*\)",
                     lambda m: f"({m.group(2)} + INTERVAL '{m.group(1)} day')", out)
        out = re.sub(r"(?i)DATEADD\(\s*MONTH\s*,\s*(-?\d+)\s*,\s*(\S+)\s*\)",
                     lambda m: f"({m.group(2)} + INTERVAL '{m.group(1)} month')", out)
        out = re.sub(r"(?i)ADD_MONTHS\(\s*(.+?)\s*,\s*(-?\d+)\s*\)",
                     lambda m: f"({m.group(1)} + INTERVAL '{m.group(2)} month')", out)
        # 4. Normalise "+ INTERVAL '-N unit'" to "- INTERVAL 'N unit'" —
        #    both engines compute the same value, but the minus form is
        #    the canonical PostgreSQL idiom.
        out = re.sub(
            r"\+\s*INTERVAL\s+'(-\d+) (\w+)'",
            lambda m: f"- INTERVAL '{abs(int(m.group(1)))} {m.group(2)}'",
            out,
        )
        # 5. Fix bare date-shaped integers leaked by Oracle TRUNC rendering.
        out = re.sub(r"(?<!['\d-])(\d{4})\s*-\s*(\d{2})\s*-\s*(\d{2})(?!['\d-])",
                     r"CAST('\1-\2-\3' AS DATE)", out)
        return out

    def execute(connection, sql: str, source_dialect: str,
                engine: str = "duckdb"):
        try:
            executable = _to_executable(sql, source_dialect)
            # Execution itself never raises: execute_or_skip returns
            # (None, error) for engine-level failures (both drivers
            # verified: psycopg and duckdb). The only raising step is
            # the sqlglot rewrite, which fails only on malformed input
            # (a generation bug, not an engine difference).
            return execute_or_skip(connection, executable)
        except (ParseError, TokenError) as e:
            return None, f"D3 rewrite failed: {e}"

    return execute
