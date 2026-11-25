# Release 1.15.0 Readiness

Date: 2026-11-26

## Included in this release

1. SQL semantic correctness fixes for Semantic Diff, ROWNUM, ARRAY JOIN,
   integer division, CONCAT NULL propagation, and validation state.
2. NL2SQL predicate, EXISTS ownership, path literal, schema projection and
   rule-cache correctness.
3. Parser scope-aware table/column extraction and `JOIN USING` metadata.
4. API response models, CORS/error/metrics contracts, and bounded LLM paths.
5. React stale-result, handoff, API response, settings and focus fixes.
6. Release/CI quality gates across tags and required workflows.

## Verification evidence

The release branch is based on main commit `e951e29`.

| Check | Release-candidate result |
| --- | --- |
| Full Python test suite | 5181 passed, 38 skipped |
| Backend coverage, minimum 91% | 93.63%, gate passed |
| Per-module coverage, minimum 90% | 8 of 8 guarded modules passed |
| Full-backend Ruff | Clean |
| Full-backend mypy | 0 errors in 267 source files |
| Deprecation-warning strict pytest | Passed |
| Bandit, pip check, git diff --check | Passed |
| Semantic Tier A skip gate | Enforced in CI |
| Tag-triggered and required-workflow release gates | Enforced |
| Frontend tests/lint/typecheck/build | 133 tests; passed in audit environment |
| Release metadata / README consistency | Verified for v1.15.0 |

## Correctness contracts

- Semantic Diff preserves precedence/associativity and only reports NULL
  semantics when the NULL predicate itself changes.
- Oracle row limiting is scoped to the correct query block and fails closed
  for unsupported aggregate/window/existing-limit combinations.
- Unsupported ClickHouse ARRAY JOIN shapes fail closed.
- PostgreSQL integer division remains integer-valued when converted to DuckDB.
- NL2SQL ordinary boolean expressions preserve quoted `AND`/`OR`, parentheses
  and comments; subject predicates remain outside EXISTS subqueries.
- Path-count literals preserve exact string and multiline values.
- Parser and frontend boundaries preserve scope and reject stale results.

## API and UI contracts

- Parse/diff/catalog/type endpoints have explicit response models.
- Early CORS/error/metrics paths preserve request IDs and observable status.
- LLM requests have a bounded deadline and response-size limit.
- Frontend requests use snapshots and do not apply stale results to new input.
- Settings save is atomic and reports failures; handoff preserves dialect.

## Known external verification gaps

- Native PostgreSQL/MySQL/Oracle/ClickHouse execution evidence.
- Redis multi-process rate limiting.
- GitHub required-check enforcement in the real repository settings.
- Production SPA fallback and API smoke tests.

These are environment-specific verification items, not local correctness
changes.

## Release gate

The release branch is based on `e951e29`. The release PR must pass CI,
Quality, Benchmark, CodeQL, README Consistency, Frontend, semantic runtime,
and 3.11/3.12 tests before merge. After merge, tag `v1.15.0` on the release
commit; the tag-triggered Release workflow builds, verifies, and publishes
GitHub release distributions, then PyPI publication follows on workflow
success.
