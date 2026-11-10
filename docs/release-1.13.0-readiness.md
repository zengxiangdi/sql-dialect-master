# Release 1.13.0 Readiness

Date: 2026-11-10

## Included in this release

1. One-hop unique target counts when the subject table has a composite primary
   key and a direct relationship to the target.
2. Subject primary-key group identity and target primary-key identity through a
   `PathDistinctCountPlan`.
3. Derived DISTINCT rendering over one INNER JOIN, with NULL identity filtering
   and outer COUNT/GROUP BY.
4. Subject-side `whose` predicates and outer LIMIT.

## Verification evidence

The release branch is based on the squash merge of PR #281. Main required
workflows succeeded on the merge commit. The main push did not trigger React
Frontend because frontend paths were unchanged; the PR #281 Frontend check
passed.

| Check | Release-candidate result |
| --- | --- |
| Full Python test suite | 3961 passed, 39 skipped |
| Backend coverage, minimum 91% | 92.33%, gate passed |
| Mypy, Ruff, and Bandit | Passed |
| Project `pip check` | No broken requirements found |
| README consistency and release metadata | Passed for v1.13.0 |
| Isolated locked-environment pip-audit | 0 known vulnerabilities |
| React lint, typecheck, tests, and production build | Passed; 13 test files, 132 tests |
| Clean wheel and sdist build | Passed |
| Release artifact validation and `twine check` | Both artifacts passed |
| `git diff --check` | Passed |

## One-hop composite PathDistinctCountPlan contracts

- The path plan handles a single direct relationship when the subject has a
  composite primary key.
- The subject primary-key columns form the group identity; the target
  primary-key columns form the counted identity.
- A one-hop path uses an INNER JOIN and returns only subjects with a matching
  target.
- Subject-side `whose` predicates are placed inside the derived query; LIMIT is
  applied outside the grouped result.
- The single-column subject path continues to use the existing
  `COUNT(DISTINCT pk)` renderer.
- The existing two-hop plan and renderer remain supported.

## Relationship completeness rule

For every composite endpoint, the relationship column pairs must cover all
primary-key components on that endpoint. Partial relationships fail closed to
prevent cross-tenant matches. Identity components are filtered with `IS NOT
NULL`, consistent with the single-column unique-count path.

## Fail-closed rules

Incomplete or multiple direct relationships, missing subject or target primary
keys, ordinary WHERE conditions, target/intermediate filters, ORDER BY,
zero-count semantics, and physical joins fail closed. No association-count,
LEFT JOIN, or outer ordering semantics are added.

## SQLite runtime and dialect evidence

SQLite runtime tests verify duplicate target deduplication and separation of
same numeric IDs across tenants. SQLGlot parseability covers all 12 supported
dialects. Deterministic repeated calls and single-column/two-hop regressions
remain covered.

## No-schema compatibility

The new path plan is only created in schema-aware unique-count resolution. The
no-schema extractor, renderer, SQL output, success status, and suggestions
remain unchanged.

## Known limitations

- Association counts for composite subject identities are unsupported.
- Zero-count and LEFT JOIN behavior are unsupported.
- Ordinary WHERE and target/intermediate filter ownership are unsupported.
- Outer ORDER BY is unsupported.
- Multi-hop physical JOIN chains and three-hop paths are unsupported.
- No API, frontend, dependency, or lockfile changes are included.

## Release gate

The merged main commit is `de76185ddaedbefc6381b012234b7c39bb5dd67c`.
CI, Quality, Benchmark, CodeQL, and README Consistency succeeded on this
commit. PR #281's Frontend check passed; main did not trigger Frontend because
frontend paths did not change.

After release-candidate checks pass, push this branch and create a release PR
for review. Do not merge the release PR in this preparation stage.

## No dependency changes

Only the authorized version metadata, CHANGELOG, and readiness documentation
files are changed. The frontend lockfile changes only its top-level version and
`packages[""].version`; dependency entries remain unchanged.

## Tagging/GitHub Release/PyPI not run

Tag creation, GitHub Release creation, and PyPI publication are separate later
steps and are not run in this preparation stage.
