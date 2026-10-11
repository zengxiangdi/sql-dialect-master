# Changelog

All notable changes to SQL Dialect Master are documented here.

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
