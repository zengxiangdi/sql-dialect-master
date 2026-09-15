# Release Baseline — v1.0.1

**Created:** 2026-09-15  
**Purpose:** Reference baseline for subsequent 1.0.2 / 1.1.0 comparisons

---

## Release Metadata

| Field | Value |
|-------|-------|
| Version | 1.0.1 |
| Commit SHA | `0db57f10be818a2e6d78aafccebf1731bcf6408e` |
| Tag | `v1.0.1` |
| Branch | `main` |
| GitHub Release | https://github.com/zengxiangdi/sql-dialect-master/releases/tag/v1.0.1 |
| Working Tree | clean (no uncommitted changes) |

---

## CI Status (commit 0db57f1)

| Check | Status | Run ID |
|-------|--------|--------|
| CI (Python 3.11/3.12) | ✅ success | 34921619910 |
| CodeQL (Python) | ✅ success | 34921619823 |
| Quality (Ruff/Bandit) | ✅ success | 34921619825 |
| Benchmark | ✅ success | 34921619877 |
| README Consistency | ✅ success | 34921619860 |

All 5/5 CI checks passing on the release commit.

---

## Test Results

### Full Pytest Suite

```
python -m pytest backend/tests/ -q
→ 1143 passed, 6 skipped, 0 failed
```

Skipped tests are for DuckDB runtime cases where duckdb is not installed or syntax is not executable in DuckDB.

### Semantic Regression Tests

| Suite | Cases | Passed | Skipped | Notes |
|-------|-------|--------|---------|-------|
| Static semantic regression | 51 | 51 | 0 | GROUP_CONCAT/STRING_AGG/LISTAGG/ARRAY_AGG/Date-Time/IN/NL2SQL/TypeMapper/lexical boundary/false notes |
| Runtime semantics (DuckDB) | 47 | 47 | 0 | Predicate/Aggregation/GroupBy/DateTime/IN/semantic diff |
| NL2SQL semantic tests | 77 | 77 | 0 | IR extraction, predicate classification, ordering stability |
| PostgreSQL native runtime | 2 | 2 | 0 | CI service postgres:17, native query equivalence |
| **Total** | **177** | **177** | **0** | |

### Dialect Matrix Coverage

| Level | Description | Status |
|-------|-------------|--------|
| 0 — Parse | sqlglot round-trip parseable | ✅ All 144 dialect pairs |
| 1 — AST | canonical SQL equivalence via AST diff | ✅ diff_sql_ast returns classification |
| 2 — Golden | known-good output comparisons | ✅ 1045 static tests |
| 3 — Semantic Diff | static classification with explicit uncertainty | ✅ Context-sensitive functions flagged |
| 4 — Runtime | DuckDB execution comparison | ✅ 47 passed |

---

## Architecture Invariants (Verified)

```
SQLTranspiler.transpile:              backend.core.transpiler     ✓
SQLTranspiler.batch_transpile:         backend.core.transpiler     ✓
SQLTranspiler.batch_transpile_async:   backend.core.transpiler     ✓
NL2SQLGenerator._extract_conditions_enhanced: backend.core.nl2sql_legacy  ✓
TransformRule.apply:                   backend.core.rules          ✓
Runtime monkey patches:               0                           ✓
backend.core.batch_validation:        Deleted                     ✓
backend.core.input_validation:        Deleted                     ✓
```

No `*_hardening.py`, `*_patch.py`, `*_fix.py` files in production code.
No second conversion pipeline exists outside `SQLTranspiler.transpile()`.

---

## Security Evidence

| Tool | Status | Details |
|------|--------|---------|
| Bandit (`-ll`) | ✅ Clean | 0 high, 0 medium, 13 low (pre-existing, expected) |
| pip-audit | ✅ No vulns | All dependencies clean |
| CodeQL | ✅ Clean | No findings on 0db57f1 |
| XSS (frontend) | ✅ Fixed | All `_esc()` applied; `st.copy_button()` used |
| Input validation | ✅ Native | `SQLTranspiler.transpile()` validates in-place |

---

## Packaging

```
Wheel:   sql_dialect_master-1.0.1-py3-none-any.whl
Version: 1.0.1 (pyproject.toml + frontend/components.py + config.py)
Data:    backend/core/functions_db.json ✓
         backend/core/type_mapping.json ✓
Excluded: backend/tests/ ✓
          backend/benchmarks/ ✓
```

---

## Known Limitations (Documented, Not Fixed)

### 1. Parameterized Types
- `VARCHAR(255)`, `DECIMAL(18,2)` → TypeMapper returns unsupported error
- Category: input-shape issue, not semantic bug
- Priority: P1 for 1.1.0

### 2. NL2SQL IN Subquery Support
- Literal-list IN supported: `WHERE id IN (1, 2, 3)` ✓
- Subquery IN not supported: `WHERE id IN (SELECT id FROM ...)` ✗
- Falls through to base extractor without IN clause
- Priority: P1 for 1.1.0

### 3. CONCAT NULL Semantics
- PostgreSQL: `CONCAT(a, b)` ignores NULL args, returns non-NULL
- MySQL: `CONCAT(a, b)` propagates NULL, returns NULL if any arg is NULL
- Classification: `potentially_different`
- Compatibility note documented in config.py
- **Must not be silently claimed as equivalent**

### 4. Dialect-Specific Aggregate Behavior
- LISTAGG (Oracle), GROUP_CONCAT (MySQL), STRING_AGG (PostgreSQL/TSQL)
- DISTINCT ordering in aggregation may vary between dialects
- Runtime comparison uses set-based normalization for known differences
- Classified as `KNOWN_DIFFERENCE` in semantic diff

### 5. Runtime Coverage
- PostgreSQL native runtime currently covers only 2 test cases
- DuckDB runtime covers 47 cases, 4 skipped (known syntax limitations)
- Future expansion planned for 1.1.0

---

## Test Philosophy (Enforced)

New tests must be based on:
- Real bug (reproduced before fix)
- Real semantic risk (dialect incompatibility discovered)
- Real customer scenario (production-observed case)
- Real dialect incompatibility (empirical finding)

**Not acceptable:** Adding tests for numerical coverage improvement alone.

---

## Version Strategy

### 1.0.2 — Bug Fix Only
- Bug fixes
- Security patches
- Semantic regression fixes
- Documentation corrections
- **No new features**

### 1.1.0 — Improvements
- TypeMapper parameterized type resolution
- Larger semantic matrix
- NL2SQL architecture improvements
- Performance/observability improvements

---

## Production Maintenance Mode

Every bug fix follows this process:

```
Issue
  ↓
minimal reproducer
  ↓
regression test
  ↓
minimal fix
  ↓
focused tests
  ↓
full tests
  ↓
semantic/runtime verification
  ↓
release note
```

Direct production code modifications without a reproducer and regression test are prohibited.

---

## Commit History (Release Window)

| Commit | Description |
|--------|-------------|
| `0db57f1` | docs: update RELEASE_READINESS.md with PostgreSQL native runtime evidence |
| `dca7e40` | docs: update CHANGELOG for 1.0.1 release with semantic fixes and architecture convergence |
| `8734a7f` | fix: skip DuckDB runtime tests when duckdb not installed in CI |
| `1194060` | fix: add CONCAT NULL semantics documentation and expand runtime tests |
| `acea6dc` | docs: update RELEASE_READINESS.md with final commit SHA and full evidence |
| `dcb919d` | fix: RC语义回归 — 修复IN谓词丢失、重复条件、错误兼容性注释和DATETIME类型映射 |
| `aac1364` | refactor: eliminate runtime monkey patches and fix frontend XSS |

---

## v1.0.1 Status

```
# READY FOR RELEASE ✓
```

All gates passing. Working tree clean. Tag v1.0.1 at HEAD.

---

*This document serves as the authoritative baseline for comparing subsequent releases against v1.0.1.*
