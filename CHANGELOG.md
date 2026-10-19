# Changelog

All notable changes to SQL Dialect Master are documented here.

## [1.1.8] - 2026-10-19

### New

- Added a protected `GET /metrics` Prometheus endpoint. Metrics are
  disabled by default (`SDM_METRICS_ENABLED=false`) and require a
  dedicated `SDM_METRICS_TOKEN` when enabled.
- Exposed HTTP request counts and latency, rate-limit rejections, worker
  capacity/rejections/timeouts, transpile results, and transpiler cache
  statistics.
- Added `BoundedWorkerPool.stats()` with lock-protected counters.

### Changed

- Added CI coverage reporting with `pytest --cov=backend` and a
  `fail_under = 93` floor.
- Added contract tests for validators, parser, type mapping, and function
  lookup; total line coverage is now about 94%.
- Added `prometheus-client` as a runtime dependency.

### Notes

- Metrics are per-process in this release; multiprocess aggregation is a
  follow-up for multi-worker deployments.
- `/metrics` is outside `/api/*`, uses its own token, and never includes
  SQL, table/column names, client IPs, request IDs, query strings, or
  error text.
- No public API, SDK signature, error code, response field, or cache-key
  semantics changed.

## [1.1.7] - 2026-10-19

### New

- React workspace handoff: History entries can be reopened in Convert or
  Diff, NL2SQL output can be sent to Diff, and successful conversions can
  open Diff directly.
- Semantic Diff, Query Analysis, and Lineage now expose dialect selectors;
  selected dialects are mirrored in URL query parameters and restored on
  refresh.
- Added `docs/deployment.md` with reverse-proxy, trusted-proxy, auth/CORS,
  rate-limiting, health-probe, cache/security-header, and operational
  guidance.

### Changed

- Added `SDM_TRUSTED_PROXIES` (empty by default). `X-Forwarded-For` is only
  trusted when the direct peer is inside the configured networks; invalid
  or catch-all networks fail startup.
- Rate limiting and structured logs now share one resolved client identity.
- The in-memory rate-limit store uses a monotonic clock; Redis keeps
  server-side TTL semantics.
- Added response cache policy: SQL-bearing POST responses and health probes
  are `no-store`; public catalog GETs use `private, max-age=60`; stats and
  root use `private, max-age=15`.
- `X-XSS-Protection` is now `0`; CSP and HSTS remain the responsibility of
  the static frontend, reverse proxy, or TLS terminator.

### Performance / Observability

- The transpiler benchmark now reports per-statement latency for sync and
  async runs, and the CI benchmark summary prints those values.

### Notes

- No public API, SDK signature, error code, response field, or cache-key
  semantics changed.
- Docker/containerization and strict cross-platform lockfile regeneration
  remain deferred.

## [1.1.6] - 2026-10-18

### Performance

- Compatibility-note evidence now reuses a per-call AST context instead of
  reparsing the same SQL for each construct check. A representative
  mysql → postgres conversion drops from 7 to 2 `sqlglot.parse_one` calls,
  and the compatibility-notes stage share falls from 48.80% to 17.31%
  (no cache, security disabled, validation enabled).
- MySQL conversions skip the AST normalization pass when no candidate
  construct is present; target-mysql conversions skip it entirely.
- The GROUP_CONCAT dynamic-separator guard performs a lexical prefilter
  before parsing.
- Security validation caches raw and prepared parse results within one
  call while preserving every fail-closed default.

### Fixed

- Frontend localStorage reads, writes, and JSON parsing are guarded against
  quota and parse failures.
- Conversion history is bounded by serialized size; truncated entries are
  marked and cannot be copied as incomplete SQL.
- Active drafts preserve the full value up to the backend's 100,000-character
  limit instead of being silently truncated at 20,000 characters.
- The displayed frontend version is injected at build time from
  `frontend-react/package.json`, and README consistency checks now validate
  package.json and package-lock versions.

### Changed

- `requirements-lock.txt` is regenerated from the runtime, dev, and qa extras;
  unused Streamlit-era transitive dependencies are removed while the
  build/upload toolchain is pinned.
- Type and function catalog docstrings reference the canonical JSON data files
  instead of hardcoded counts.

### Notes

- No public API, SDK signature, error code, response field, or cache-key
  semantics changed.

## [1.1.5] - 2026-10-17

### New

- Added `POST /api/diff` semantic-equivalence checks for source and target SQL
  with both dialects; parse failures return `status="parse_error"` instead of
  a 4xx response. The React semantic diff page now uses the real classifications.
- React NL2SQL now accepts the existing `column_hints` field as comma-separated
  column hints.
- React function library categories load dynamically from
  `/api/functions/categories` with a built-in fallback.

### Changed

- 5xx capacity and timeout responses now expose string error codes
  (`SERVICE_UNAVAILABLE` / `REQUEST_TIMEOUT`) consistently with 4xx responses.
- `/api/types` always returns an array; the React type model no longer supports
  the old dictionary/array dual shape.
- Removed the retired Streamlit frontend; React is the sole product frontend.

### Fixed

- JSON rule rewrites no longer truncate nested arguments in `JSON_EXTRACT` and
  `PARSE_JSON`.
- Fail-closed `STRING_AGG` dynamic-separator conversions no longer retain
  contradictory success compatibility notes.
- `CONCAT` is no longer misclassified as context-sensitive; equivalent CONCAT
  queries remain `equivalent`.

### Performance

- Rule application now prefilters and caches applicable rules by dialect pair.
- MySQL `--` parser preprocessing now uses one linear scan instead of repeated
  O(n²) replacement.
- `/api/parse` uses an in-process LRU cache, and function search uses LRU/TTL
  caching.
- Worker-pool shutdown is idempotent, with explicit shutdown support outside
  ASGI, and readiness probes share one cache source.

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
- Release metadata, Changelog, package data, and the installed SDK are checked
  before publishing. React is the sole product frontend; the retired Python UI
  is excluded from runtime dependencies and wheel contents. GitHub Release
  waits for CI at the tagged commit; PyPI consumes the exact same verified
  GitHub artifacts.
- Developer tooling uses the project `.venv`; build and Twine are included
  in the QA extra. CodeGraph indexes are ignored by Git.

### Changed

- `BoundedWorkerPool.shutdown()` 现为幂等: 重复调用不再抛 RuntimeError, 而是一次性关闭后静默返回。依赖旧重复-shutdown 报错语义的调用方需改为单一 shutdown 点。经检索, 仓库内无调用方依赖旧报错语义。
- 退役的 Streamlit/Python `frontend/` 前端及其专属测试已移除，React workspace 现在是唯一产品前端。
- 新增 `POST /api/diff` 语义 SQL 比较端点，返回等价性状态、差异分类和结构化发现。
- `/api/parse` 增加有界请求级结果缓存；readiness 探针改用单一缓存来源，避免镜像状态漂移。

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
