# Changelog

All notable changes to SQL Dialect Master are documented here.

## [1.1.4] - 2026-10-13

### Correctness and behavior changes

- NL2SQL rejects empty, unrecognized, and unsupported DDL requests. DROP is
  never mapped to DELETE; English operation words no longer imply column
  names (`update` no longer introduces a `date` assignment).
- All natural-language date windows are checked against
  `SDM_NL2SQL_MAX_DATE_INTERVAL_DAYS` (default 36525). The configured
  `SDM_NL2SQL_CONFIDENCE_THRESHOLD` (default 0.6) now controls whether
  generation succeeds; below-threshold requests return `success=False` and
  `sql=null`.
- NL2SQL responses add `parameter_style`, ordered `parameters`, and
  `evidence`; `parameters` contains placeholder markers, not bound values
  (for example `['$1', '$2']`). DML output is still a template requiring
  caller-supplied values.
- Parser, semantic Diff, and static workspaces require one bounded statement;
  a trailing delimiter followed by a comment is accepted consistently.
- Cached conversion results and lookup results no longer share mutable lists
  or dictionaries with subsequent callers.
- Function categories are validated with HTTP 400 for unknown values;
  explicit SDK search `limit=0` returns no results. Type comparison accepts
  the same aliases as type mapping.
- NL2SQL edits invalidate displayed results; Diff defaults to PostgreSQL →
  MySQL. Invalid history fields and navigation payloads are normalized or
  rejected. History now includes failed conversions and their error reasons.
- Frontend statuses and colors use one vocabulary. SQL editors preserve
  edits across reruns without competing widget defaults.

### Operations and release validation

- `SDM_API_KEY` is disabled by default. When configured, `/api/*` requests
  require `X-API-Key` or `Authorization: Bearer <key>`; missing or invalid
  credentials receive 401. Health probes retain their separate access policy.
- Bounded CPU workers and queues (`SDM_API_WORKERS=4`,
  `SDM_API_QUEUE_SIZE=4` by default) prevent timed-out requests from releasing
  capacity prematurely. Busy calls receive 503 with `Retry-After: 1`; timeouts
  receive 504 with request correlation. Timeout stops waiting, while the
  running thread retains its slot until completion.
- Public SQL safety validation delegates to the canonical implementation;
  dialect-aware rewrites preserve MySQL `#` comments.
- Release metadata, Changelog, package data, and installed Streamlit startup
  are checked before publishing. GitHub Release waits for CI at the tagged
  commit; PyPI consumes the exact same verified GitHub artifacts.
- Developer tooling uses the project `.venv`; build and Twine are included
  in the QA extra. CodeGraph indexes are ignored by Git.

## [1.1.3] - 2026-10-12

### API and security hardening

- API parsing now rejects empty, multi-statement, and empty-statement SQL
  inputs with a validation error instead of silently analyzing only the first
  statement.
- CPU-heavy conversion, parsing, and NL2SQL work runs outside the async event
  loop and observes the configured request timeout.
- Request-size, rate-limit, Redis timeout, readiness-token, cache cleanup, and
  SQL security boundary handling were hardened, including MySQL ``#`` comments.
- Configuration values are validated at startup; parser length limits fall
  back to the transpiler limit and logging settings are applied consistently.

### NL2SQL behavior changes

- DML templates now emit target-specific parameter markers: PostgreSQL and
  Redshift use ``$n``, Oracle uses ``:n``, T-SQL uses ``@pN``, and MySQL uses
  ``%s``. These statements remain parameterized templates; callers must bind
  values before execution.
- Generated SQL that fails target-dialect validation is now reported as
  ``success=False`` instead of being returned as a successful result.
- ``LIMIT 0`` is preserved. Negative and excessively large limits are
  rejected instead of being silently dropped or producing an unbounded query.

### Frontend behavior changes

- Convert, Diff, Batch, History, NL2SQL, Command Palette, Query Analysis, and
  Lineage state transitions now invalidate stale results and handle malformed
  session state safely.
- Streamlit widget callbacks prevent Swap, Format, and Clear from raising
  widget-state exceptions.
- Lineage preserves schema, aliases, and self-joins with unique Mermaid IDs;
  Query Analysis recognizes aggregate functions without GROUP BY.
- Runtime verification is clearly marked unavailable until a database
  connection is configured.

### Packaging and compatibility

- The supported sqlglot range is now ``>=30.18.0,<31.0.0``.
- The installed package includes the Streamlit entry module and exposes the
  ``sdm-streamlit`` console command for launching the UI from any directory.
- DML parameter markers and strict multi-statement parsing are intentional
  behavior changes for callers that previously relied on generic ``?``
  markers or first-statement-only parsing.

### Verification

- Full test suite: 2779 passed, 6 skipped (PostgreSQL-dependent locally).
- Ruff correctness checks, Python compilation, wheel/sdist build, installed
  wheel smoke test, and Streamlit page smoke tests passed.

## [1.1.2] - 2026-10-11

### NL2SQL correctness (B1)

- Aggregate columns now resolve to the user's named metric — "average price
  grouped by category" produces ``AVG(price)``, never ``AVG(age)``.
- Plural English time ranges (``last 3 weeks`` / ``last 2 months`` /
  ``last 1 year``) keep their unit in both the SQL and the explanation.
- Top-N + filter inputs emit WHERE → GROUP BY → ORDER BY → LIMIT in order,
  with the threshold bound to the operator word (``前10条金额大于100`` → ``> 100``).
- Multiple known relations compose into one WHERE via AND-ed EXISTS clauses.
- Chinese relational intent (``查询有订单的用户``) produces real
  EXISTS / NOT EXISTS end-to-end; unknown pairs (``查询有发票的用户``) fail
  closed with ``success=False`` and an explicit explanation.

### STRING_AGG / cache / compatibility evidence / configuration (B2)

- Dynamic ``STRING_AGG`` separators that MySQL cannot express fail closed
  instead of being quoted into malformed literals; the original SQL is
  preserved byte-for-byte and never silently rewritten.
- Rule-cache signatures cover every behavior-affecting rule field
  (``function_name``, ``structured_replacement``, ``structured_replacer``,
  ``full_sql_rewriter``), including callable identity — rule-set swaps
  invalidate the cache; unchanged rules keep a stable version.
- Compatibility notes split source-construct advisories (source SQL) from
  conversion-result claims (verified against the final SQL, through the
  executable mask with identifier boundaries, AST type/clause evidence, and
  per-SELECT-level TOP/LIMIT distinction).
- Redis rate-limit backend and URL now flow through ``AppSettings``
  (``rate_limit_backend`` Literal, ``redis_url`` SecretStr); no raw env
  reads, no silent downgrade to memory.

### API and core contracts (B3)

- ``TypeMapper.map_type`` reports ``mapping_status`` (``mapped`` /
  ``unsupported`` / ``source_unavailable`` / ``unknown_type`` /
  ``unknown_dialect``); ``N/A → N/A`` is never success.
- Parser ``args_count`` counts actual expression operands, not AST arg fields.
- Illegal ``table_hint`` values are 4xx validation errors at the API
  boundary (before any generation), while direct orchestrator calls keep
  their explicit ValueError.
- The statement splitter now honors T-SQL standalone ``GO`` batches and keeps
  Oracle PL/SQL blocks (including nested CASE / IF / LOOP / WHILE) as single
  statements with exact content preservation.

### Frontend correctness (B4)

- Semantic Diff receives the original source SQL and the real conversion
  result (never a self-comparison); the NL2SQL page no longer offers a
  meaningless self-diff.
- Type mapping status recognizes ``N/A`` before equality — both-missing
  cells are never labelled ``exact``.
- Template code blocks render raw SQL (no HTML-escaped entities).
- The SQL editor no longer passes unsupported widget parameters.
- ``export_theme`` serializes the frozen ``ColorTokens`` dataclass to stable,
  validated JSON.

### Testing and documentation (B5)

- Release-gate independent semantic expectations cover NL2SQL values,
  transpiler target structures, TypeMapper targets, splitter boundaries and
  frontend navigation payloads.
- CHANGELOG and CONTRIBUTING reflect the current repository structure.

### Verification boundary

Static SQL-structure verification (sqlglot parse/AST evidence) covers the
12-dialect conversion matrix.  Runtime evidence exists only where a real
engine executes in CI (DuckDB in-process; PostgreSQL when available);
native MySQL / Oracle / T-SQL execution is not claimed in this release.

## [1.1.0] - 2026-09-21

### Added

- **D1: Parameterized VARCHAR/VARCHAR2 precision support** — TypeMapper now parses `VARCHAR2(2000)`, `NVARCHAR(MAX)`, `CHAR(100)` etc. and returns `precision` field in results. Precision-aware warnings added for Oracle 4000/32767 limits, TSQL NVARCHAR 4000 limit, and MySQL row-size soft limits. `NVARCHAR` and `NCHAR` added as canonical types with full 12-dialect mappings.
- **D2: Relational NL2SQL queries** — `EXISTS` / `NOT EXISTS` generation for pattern phrases like "users who have orders", "customers with orders", "users without orders". Known relationships (users↔orders, customers↔orders, orders↔products, employees↔departments, users↔transactions, orders↔payments) use explicit join-key mappings. Unknown relationships fail safely with `success=False` and explicit explanation requiring user-provided join condition. Date conditions in combined queries (D2+D3) are scoped inside the EXISTS subquery.
- **D3: Date arithmetic semantic completion** — Added `tomorrow`/`明天` support. Added bare period expressions: `last week` (rolling 7 days), `last month` (calendar -1 month via `ADD_MONTHS`), `last year` (calendar -1 year). Fixed template path to inject date conditions into generated SQL. Calendar-relative semantics for month/year (`ADD_MONTHS`) vs rolling semantics for days/weeks (`DATE_SUB`) now documented and tested.

### Security & Architecture

- **Eliminated all runtime monkey patches** — `batch_validation.py`, `input_validation.py` deleted; validation now lives natively in `SQLTranspiler.transpile()`.
- **Removed hardening/patch/fix compatibility layers** — no hidden import-side-effects remain.
- **Frontend XSS remediation** — all user-supplied HTML escaped via `_esc()`; replaced raw `navigator.clipboard.writeText()` with native `st.copy_button()`.
- **Canonical conversion paths** — all 4 key methods verified to live in their canonical modules:
  - `SQLTranspiler.transpile/batch_transpile/batch_transpile_async` → `backend.core.transpiler`
  - `NL2SQLGenerator._extract_conditions_enhanced` → `backend.core.nl2sql_legacy`
  - `TransformRule.apply` → `backend.core.rules`

### Semantic Fixes

- **NL2SQL IN predicate lost** — fixed regex-based `IN`/`NOT IN` extraction in `_extract_conditions_enhanced`.
- **NL2SQL spurious ORDER BY** — changed substring `"order" in text` to `\b` word-boundary matching; "orders" table name no longer triggers false ORDER BY.
- **NL2SQL duplicate status conditions** — `in_matched_columns` set prevents redundant `status = 'active'` when `status IN (...)` was already matched.
- **False compatibility notes** — `LISTAGG → ARRAY_JOIN(COLLECT_LIST())` and `CONNECT BY → WITH RECURSIVE` notes now filtered when the transformation was not actually applied (sqlglot-native conversions).
- **CONCAT NULL semantics** — added `CONCAT` to `_CONTEXT_SENSITIVE_FUNCTIONS`; classified as `potentially_different` with explicit compatibility note documenting PostgreSQL vs MySQL NULL behavior difference.

### TypeMapper

- Added `DATETIME` type mapping (`mysql` → `TIMESTAMP` in postgres).

### Documentation

- Added `RELEASE_READINESS.md` with full engineering, semantic, runtime, and security gate evidence.

## [1.0.1] - 2026-09-15

### Added

- 12×12 SQL dialect conversion coverage matrix with target-dialect validation.
- Semantic regression coverage for NL2SQL and cross-dialect conversion.
- Deterministic rule ordering, selector normalization, pattern validation, and conflict detection.
- Statement-level security validation for stacked SQL statements.
- Rule-aware transpilation caching, async batch conversion, and benchmark coverage.
- Stable machine-readable `error_code` values across core transpiler and API responses.
- Runtime validation for packaged function/type JSON configuration.
- Wheel/package-data validation and installed-wheel smoke testing in CI.
- Python 3.11/3.12 CI coverage with compile and distribution checks.

### Fixed

- Cache LRU updates no longer evict unrelated entries when replacing an existing key.
- Cached `None` values are distinguished from cache misses.
- Explicitly supplied cache instances are preserved by `CachedFunction`.
- Rule dialect selectors now ignore surrounding whitespace and case.
- CI actions were upgraded to current major versions (`checkout@v5`, `setup-python@v6`).
- Cache configuration now requires a positive `cache_max_size`.

### Compatibility

- The default `security_block_dangerous` setting remains disabled for backward compatibility.
- API error responses retain existing HTTP status behavior while exposing the stable `error_code` field.
