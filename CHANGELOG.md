# Changelog

All notable changes to SQL Dialect Master are documented here.

## [Unreleased]

### Engineering

- Added repository-level Dependabot configuration for Python and GitHub Actions dependencies.
- Added CodeQL security analysis for Python on pushes, pull requests, and a weekly schedule.
- Added CODEOWNERS, pull request templates, and issue templates.
- Added tag-driven GitHub Release automation.
- Added a PyPI publishing workflow using GitHub Actions trusted publishing (OIDC).
- Refreshed the immutable GitHub Actions SHA lockfile after Dependabot action upgrades.
- Added a generic SQL parser fallback when target-dialect parsing is unavailable, with an explicit compatibility warning.
- Added an AST-based semantic diff detector for structural conversion regressions.
- Added PostgreSQL + DuckDB runtime semantic regression coverage and a dedicated CI gate.
- Added locked semantic-test dependencies for DuckDB and Psycopg.

### Fixed

- Release automation now rejects Git tags that do not exactly match `pyproject.toml` project version.
- Dependabot now ignores `websockets>=17`, which conflicts with the currently locked Streamlit dependency.

## [1.0.1] - 2026-09-08

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
