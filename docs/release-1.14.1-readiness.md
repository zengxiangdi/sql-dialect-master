# Release 1.14.1 Readiness

Date: 2026-11-22

## Included in this release

1. NL2SQL executable-text masking for quoted literals and comments.
2. Correct TOP-N/date clause ordering and structural TOP number selection.
3. Schema table/aggregate literal isolation.
4. Deterministic intent table/column ordering.
5. No-schema `DISTINCT` / `UNIQUE` restoration.
6. Strict SQL scanner behavior with NL2SQL possessive handling scoped to a
   dedicated wrapper.
7. API request length contracts and normalized 422/413 boundaries.
8. Semantic Tier A skip gates and explicit semantic test dependencies.
9. TestClient/AnyIO deprecation warning resolution.
10. Full-backend mypy/Ruff gates and low-coverage module tests.

## Verification evidence

The release branch is based on main commit `2d31052`.

| Check | Release-candidate result |
| --- | --- |
| Full Python test suite | 5068 passed, 38 skipped |
| Backend coverage, minimum 91% | 93.58%, gate passed |
| Per-module coverage, minimum 90% | 8 of 8 guarded modules passed |
| Full-backend Ruff | Clean |
| Full-backend mypy | 0 errors in 266 source files |
| Deprecation-warning strict pytest | Passed |
| Semantic Tier A skip gate | Enforced in CI |
| API TestClient/async suite | Passed |
| pip check / pip-audit | Passed / no known vulnerabilities |
| Bandit and git diff --check | Passed |
| Clean wheel and sdist build | Previous release candidate build passed |
| Release metadata / README consistency | Verified for v1.14.1 |

## NL2SQL correctness contracts

- Structural detection uses executable text; literals and comments are not
  reinterpreted as SQL clauses.
- TOP-N and date conditions preserve `WHERE -> ORDER BY -> LIMIT`.
- Schema table mentions and aggregate intent ignore literal/comment content.
- Intent ordering is first-occurrence deterministic across hash seeds.
- No-schema and schema-aware `DISTINCT` behavior are aligned.
- SQL scanner defaults remain strict; NL2SQL possessives are handled only in
  the NL2SQL-specific wrapper.

## API contract

- Convert, Batch, Parse, Diff, and NL2SQL fields have explicit maximum lengths.
- Over-limit fields return 422 `VALIDATION_FAILED` through the normalized
  error envelope.
- Oversized request bodies continue to return 413 `PAYLOAD_TOO_LARGE`.
- Syntactically invalid SQL within the allowed length retains the existing
  analysis/`parse_error` response contract.

## Semantic and dependency evidence

- Semantic Tier A skips fail CI in the PostgreSQL/DuckDB runtime job.
- `pytz` is an explicit semantic-test dependency.
- `httpx2` is a test-only dependency for the current Starlette TestClient.
- Runtime LLM requests continue to use `httpx`.
- Starlette 1.7 resolves the BlockingPortal compatibility warning.

## Known limitations

- Physical-chain `IN`, `BETWEEN`, and `LIKE` filters remain fail-closed.
- Joined-table projection/filter ownership and multi-hop LEFT/RIGHT remain
  outside the physical-chain first batch.
- No production server, firewall, database, or deployment configuration is
  changed by this release.

## Release gate

The release branch is based on `2d31052`. The release PR must pass CI, Quality,
Benchmark, CodeQL, README Consistency, Frontend, semantic runtime, and
3.11/3.12 tests before merge. After merge, tag `v1.14.1` on the release commit;
the tag-triggered Release workflow builds, verifies, and publishes the GitHub
release distributions. PyPI publication follows the Release workflow success.
