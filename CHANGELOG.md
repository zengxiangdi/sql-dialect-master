# Changelog

All notable changes to SQL Dialect Master are documented here.

## [Unreleased]

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
