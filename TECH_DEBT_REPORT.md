# Technical Debt Report

**Baseline commit:** `3f0bbd87e7c7d8ede8c72eb8b1604593c2f0c162`  
**Audit branch:** `audit/architecture-baseline`  
**Scope:** maintainability, architecture, dependency/build, testing organization, performance and release readiness.

## Priority model

- **P0:** blocks semantic confidence or can silently invalidate results.
- **P1:** should be retired during the 1.1 engineering cycle.
- **P2:** useful cleanup after correctness and reliability are established.

## P1 maintainability debt

### T-001 — Monkey-patch based compatibility architecture

`audit_hardening.py` and `final_hardening.py` modify class methods after their classes are defined. This is difficult to reason about, especially when several compatibility modules target the same method.

**Action:** move stable logic into `NL2SQLGenerator`, `PostProcessor`, `TransformRule` and `SQLTranspiler`; retain a compatibility wrapper only when external callers require a stable symbol.

### T-002 — Duplicate scanner implementation

`audit_hardening.py` contains `_scan_segments`, while `p1_sql_scanner.py` is a reusable scanner module.

**Action:** establish `p1_sql_scanner.py` as the sole lexical boundary implementation and delete the duplicate after migration tests pass.

### T-003 — Regex-heavy semantic transformations

`rules.py` contains numerous regex transformations, including patterns whose captures stop at the first closing parenthesis.

**Action:** classify rules into lexical-only versus expression-aware. Migrate expression-aware rules to scanner/AST transformations.

### T-004 — Import topology

The API entry point mutates `sys.path` and imports `core.*`, while the same application also imports `backend.*` modules.

**Action:** standardize absolute package imports and add an import-topology regression test that imports every supported entrypoint under normal package execution.

### T-005 — Fragmented semantic tests

Semantic tests are currently spread across top-level files. This makes feature coverage difficult to inventory and allows related regressions to live in separate, implicit conventions.

**Action:** introduce a dedicated semantic test package and corpus without deleting the historical regression cases until coverage is migrated.

## P1 data-model debt

### T-006 — Type mapping ambiguity

The type mapper currently performs exact lookup and then partial substring matching. This is convenient but unsafe for parameterized or similarly named types.

**Action:** exact → canonical alias → normalized alias → ambiguous result → unknown result. Never select the first partial match.

### T-007 — Function alias model is implicit

The encyclopedia has exact-name lookup and fuzzy search but no explicit alias/normalized-name model for semantic conversion.

**Action:** add canonical function identity, aliases, supported/unsupported dialect metadata and explicit ambiguity handling.

### T-008 — Semantic diff result model is underspecified

`SemanticDiff` currently contains a Boolean `equivalent`, normalized SQL, free-form differences and parse error.

**Action:** introduce structured difference records and equivalence classifications while preserving the existing facade for compatibility.

## P2 maintainability debt

### T-009 — Hard-coded counts in documentation/API metadata

The project contains documentation and API descriptions that state counts such as 298 functions and 36 data types. These are vulnerable to drift when data files change.

**Action:** source published metrics from loaded data or a verified generated metadata artifact.

### T-010 — Test filename/layout drift

Some semantic regressions use highly specific filenames while the project now needs a stable corpus-oriented taxonomy. `test_mysql_postgres.py` is currently an empty test module and should either become a real fixture family or be removed during intentional cleanup.

### T-011 — Compatibility modules with unclear ownership

Files named `p1_hardening.py`, `audit_hardening.py`, `production_hardening.py`, `final_hardening.py`, and related fixes indicate historical remediation layers rather than a single coherent architecture.

**Action:** document ownership and dependencies first, then consolidate in incremental PRs. Do not perform a single large deletion/refactor.

### T-012 — Warning policy is not fully structured

Warnings are largely strings. Consumers cannot reliably distinguish semantic risk, unsupported feature, syntax compatibility fallback, precision loss and optimization advice.

**Action:** define stable warning codes/severity/categories while retaining human-readable messages.

## P2 performance/observability debt

### T-013 — Benchmark data is not yet a semantic-quality metric

A performance benchmark alone does not tell whether a fast conversion is correct.

**Action:** benchmark per feature family and pair with semantic evidence counts.

### T-014 — Timing is mostly request-level

The API exposes process timing, but compiler-stage timings are not yet a clear observability contract.

**Action:** later measure parser, transpile, rule processing, validation, semantic diff and cache stages independently.

### T-015 — Runtime equivalence is database-limited

Only engines actually available in CI can supply execution evidence.

**Action:** keep runtime tests optional per engine, but make unsupported runtime coverage explicit in CI reports rather than silently treating it as equivalent.

## P2 release debt

### T-016 — Version remains 1.0.1

`pyproject.toml` still declares version `1.0.1`. The 1.1.0 release must remain a later milestone after P0/P1 correctness work.

### T-017 — Release gate needs semantic evidence

The existing build/release path has strong package validation, but 1.1.0 should require the semantic corpus/matrix gates before publication.

## Debt retirement order

```text
P0 semantic correctness
  -> semantic corpus + matrix
  -> safe RuleEngine
  -> import architecture
  -> semantic diff model
  -> mapping/function data model
  -> API production cleanup
  -> performance/observability
  -> release 1.1.0
```

## Anti-patterns explicitly prohibited

- Adding another monkey-patch compatibility file for a new bug.
- Adding another global `str.replace()` for SQL semantics.
- Expanding partial-match lookup behavior to make a test pass.
- Treating parser acceptance as proof of result equivalence.
- Removing a failing regression test because the implementation is difficult to fix.
