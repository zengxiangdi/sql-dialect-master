# Release 1.16.0 Readiness

Date: 2026-11-28

## Included in this release

1. Schema-aware association counts with composite subject identity.
2. Completed INNER physical multi-hop JOIN ownership.
3. Uniform LEFT physical multi-hop JOIN chains with ON/WHERE separation.
4. Dependency upgrades: sqlglot 30.33.0, FastAPI 0.165.0, Starlette 1.10.0,
   Pydantic 2.14.4, pydantic-settings 2.16.3, certifi 2026.11.20, and
   CodeQL actions 4.39.4.

## Verification evidence

The release branch is based on main commit `e9740f4`.

| Check | Release-candidate result |
| --- | --- |
| Full Python test suite | 5299 passed, 38 skipped |
| Backend coverage, minimum 91% | 92.71%, gate passed |
| Per-module coverage, minimum 90% | 8 of 8 guarded modules passed |
| Full-backend Ruff | Clean |
| Full-backend mypy | 0 errors in 268 source files |
| Deprecation-warning strict pytest | Passed |
| Semantic Tier A skip gate | Enforced in CI |
| Bandit and git diff --check | Passed |
| Frontend tests/lint/typecheck/build | Previously 133 tests; CI verifies version-only change |
| Release metadata / README consistency | Verified for v1.16.0 |

## Association count contracts

- One-hop direct relationship, reverse traversal, and composite pairs.
- Subject identity from the subject primary key; data rows counted with
  `COUNT(*)`.
- Subject filters and subject identity ordering use association JOIN.
- Single-PK data-only filters, count ordering, and LIMIT stay on the existing
  group-label path.
- Zero association counts, multi-hop association counts, physical chains,
  EXISTS, unique counts, and non-COUNT aggregates fail closed.

## Physical-chain contracts

- INNER: joined projection/filter/group/aggregate/order, scalar IN/BETWEEN/LIKE.
- LEFT: uniform 2/3-edge chain with joined filters in the corresponding ON and
  base filters in WHERE; null extension preserved.
- Projection isolation: filter columns do not leak into SELECT.
- GROUP BY and non-aggregate projection consistency enforced.
- `ORDER BY count` renders `COUNT(*)`.
- Mixed outer joins and multi-hop RIGHT fail closed.

## Dependency upgrades

- sqlglot `30.18.0` -> `30.33.0`; Scope union handling adapted to
  `set_operation_scopes`.
- FastAPI `0.141.1` -> `0.165.0`.
- Starlette `1.7.0` -> `1.10.0`.
- Pydantic `2.13.5` -> `2.14.4`.
- pydantic-settings `2.15.0` -> `2.16.3`.
- certifi `2026.10.19` -> `2026.11.20`.
- CodeQL action pins `4.37.9` -> `4.39.4`.

## Known boundaries

- Multi-hop RIGHT and mixed outer chains remain fail closed.
- Aliases and multi-hop `SELECT *` remain unsupported.
- OR precedence and complex subquery/expression predicates remain unsupported.
- Native PostgreSQL/MySQL/Oracle/ClickHouse external execution, Redis
  multi-process behavior, GitHub repository required-check settings, and
  production SPA/API smoke tests remain external verification items.

## Release gate

The release branch is based on `e9740f4`. The release PR must pass CI,
Quality, Benchmark, CodeQL, README Consistency, Frontend, semantic runtime,
and 3.11/3.12 tests before merge. After merge, tag `v1.16.0` on the release
commit; the tag-triggered Release workflow builds, verifies, and publishes the
GitHub release, followed by PyPI publication.
