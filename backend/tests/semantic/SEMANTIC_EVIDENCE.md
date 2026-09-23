# Semantic Evidence Boundary (G3)

Auditable mapping of which semantic claims are proven by *native execution*
and which remain static-only. A construct is **runtime-verified** only when
the target SQL was executed on a real database engine and result values were
asserted. Parse/transpile/AST agreement alone is **not** runtime evidence.

## Evidence tiers

| Tier | Meaning |
|------|---------|
| A | Target SQL executed on the native target engine; result values asserted. |
| B | A compatible engine executed the semantic construct, but is not the exact target engine. Cited only as compatible-engine evidence. |
| C | Static only: sqlglot parse + transpile + structural/AST-diff assertions. No execution. |

## Dialect coverage matrix

The project supports 12 dialects: `postgres mysql oracle tsql hive spark
trino snowflake redshift clickhouse duckdb databricks`.

| Dialect | Static evidence | Native runtime | Tier | Notes |
|---------|:---:|:---:|:---:|-------|
| PostgreSQL | 12×12 matrix, D1–D3, function semantics | PostgreSQL 17 CI service (`semantic-runtime` job) | **A** | `test_postgres_runtime.py` + `test_runtime_semantics.py` |
| DuckDB | 12×12 matrix | in-process DuckDB 1.5.5 | **A** | `test_duckdb_runtime.py` + `test_runtime_semantics.py` |
| MySQL | 12×12 matrix | none in CI | **B** | Constructs exercised on DuckDB/PostgreSQL only; never claimed as native MySQL execution |
| T-SQL | 12×12 matrix | none in CI | **B** | DATEADD/ADD_MONTHS forms exercised via Tier B rewriting on DuckDB |
| Oracle | 12×12 matrix | none in CI | **C** | ADD_MONTHS/TRUNC(SYSDATE) forms are not executable in CI; static evidence only |
| Hive / Spark / Databricks | 12×12 matrix | none in CI | **C** | No engine in CI; static evidence only |
| Trino / Snowflake / Redshift / ClickHouse | 12×12 matrix | none in CI | **C** | No engine in CI; static evidence only |

The above makes explicit that **12×12 does not imply 12×12 runtime
coverage**. The native-runtime boundary is exactly: PostgreSQL + DuckDB.

## Expected-value oracle

PostgreSQL suite expected values are derived **independently by hand**
from the documented fixture (`_prepare_postgres` + `_prepare_extended`):
deterministic, explicitly-known rows and values. A DuckDB mirror of
the same fixture may be used as an optional secondary cross-check
during test development, but PostgreSQL's own execution is the
authoritative lane — DuckDB output is **never** the expected result
for the PostgreSQL suite.

## Evidence lane separation (local vs CI)

| Lane | Engine | Evidence status |
|------|--------|-----------------|
| local | DuckDB | full Tier A execution (in-process; all DuckDB-native suites pass locally) |
| local | PostgreSQL | explicitly skipped when no service is available (class B) — **not** evidence |
| CI | PostgreSQL 17 | `semantic-runtime` job — the authoritative Tier A lane for PostgreSQL |

Local PostgreSQL absence is not equivalent to successful PostgreSQL
CI execution. The acceptance evidence for PostgreSQL Tier A claims
must cite the CI `semantic-runtime` run, not a local skip.

## Construct → engine → tier map

| Construct | PostgreSQL native | DuckDB native | Other dialects |
|-----------|:---:|:---:|----------------|
| Predicates (=, !=, >, <, >=, <=, AND, OR, IS [NOT] NULL, IN, NOT IN, BETWEEN, LIKE) | A | A | B / C |
| NULL semantics (COUNT(col), LEFT JOIN null-fill, NULL-foreign-key grouping) | A | A | B / C |
| Aggregates (COUNT/SUM/AVG/MIN/MAX, GROUP BY, HAVING) | A | A | B / C |
| JOIN (INNER, LEFT) | A | A | B / C |
| EXISTS / NOT EXISTS (D2 correlated-subquery semantics) | A | A | B / C |
| D3 date arithmetic (7-day / 49-day / 1-month / 12-month windows, fixed reference date) | A (postgres/duckdb forms) | A | B (mysql/tsql rewrites), C (oracle ADD_MONTHS not executable in CI) |
| Row limiting (LIMIT/OFFSET, FETCH FIRST) | A | A | B / C |

## Failure classification

Every runtime failure must be classified:

* A — test/fixture defect
* B — environment/service defect (e.g. PostgreSQL service not up locally)
* C — expected unsupported-dialect limitation (Oracle ADD_MONTHS not in DuckDB)
* D — actual product semantic defect

The PostgreSQL fixture skip when no service is available is class **B**
environment behaviour, not a product defect; CI's `semantic-runtime`
job always provides the service, so the primary lane never silently
skips the suite.
