# Release 1.12.0 Readiness

Date: 2026-11-10

## Included in this release

1. Bounded two-hop schema-aware unique target counts through `PathStep` and
   `PathDistinctCountPlan`.
2. Subject primary-key group identity and terminal target primary-key identity.
3. Complete composite relationship validation for every path endpoint.
4. Derived DISTINCT rendering with INNER path joins, NULL identity filtering,
   outer COUNT/GROUP BY, and outer LIMIT.
5. Subject-side `whose` predicates inside the derived query.

## Verification evidence

This release branch is based on the squash merge of PR #279. Required main
workflows for the merge commit succeeded. The React Frontend workflow was not
triggered on main because no frontend paths changed; PR #279's Frontend check
passed.

| Check | Release-candidate result |
| --- | --- |
| Full Python test suite | Pending release-candidate run |
| Backend coverage, minimum 91% | Pending release-candidate run |
| Mypy, Ruff, and Bandit | Pending release-candidate run |
| Project `pip check` | Pending release-candidate run |
| README consistency and release metadata | Pending release-candidate run |
| Isolated locked-environment pip-audit | Pending release-candidate run |
| React lint, typecheck, tests, and production build | PR #279 passed; 132 tests |
| Clean wheel and sdist build | Pending release-candidate run |
| Release artifact validation and `twine check` | Pending release-candidate run |
| `git diff --check` | Pending release-candidate run |

## PathDistinctCountPlan contracts

- A plan contains canonical subject/table path steps, subject group identity,
  terminal target identity, and a NULL identity policy.
- Only a unique shortest simple path of exactly two edges is supported.
- Direct one-hop unique counts continue using the existing single-table path.
- Each relationship must cover every primary-key component for composite
  endpoints; partial tenant relationships fail closed.
- The inner query joins the subject, intermediate, and target tables and
  selects distinct group/target identity aliases.
- The outer query counts rows, groups by subject identity aliases, and applies
  LIMIT after aggregation.

## INNER/non-zero semantics

Batch A uses INNER path joins. Subjects without a matching terminal target do
not appear in the result. Identity components are filtered with `IS NOT NULL`.
Zero-count and LEFT JOIN semantics remain outside this release.

## Subject whose and fail-closed rules

- Subject-side `whose` predicates are placed inside the derived query.
- Ordinary WHERE predicates, target/intermediate filters, and qualified filters
  owned by another path step fail closed.
- ORDER BY, aggregate-alias ordering, physical multi-hop JOINs, ambiguous or
  missing paths, cycles, paths longer than two hops, and missing identities fail
  closed.

## Runtime evidence

SQLite and DuckDB tests verify duplicate target deduplication, tenant-aware
composite identity separation, NULL identity exclusion, subject `whose`, and
outer LIMIT behavior. SQLGlot parseability covers all 12 supported dialects;
repeated calls are deterministic.

## No-schema compatibility

The no-schema path never creates a `PathDistinctCountPlan`. Existing
single-table counts, EXISTS/NOT EXISTS generation, SQL output, success status,
and suggestions remain unchanged.

## Known limitations

- One-hop target unique counts with composite subject identity remain outside
  this release.
- Zero-count/LEFT JOIN semantics remain unsupported.
- Target/intermediate filter ownership remains unsupported.
- Outer ORDER BY remains unsupported for path counts.
- Multi-hop physical JOIN chains and three-hop paths remain unsupported.
- No API, frontend, dependency, or lockfile changes are included.

## Release gate

The merged main commit is `cb5ac637c2466c0c3304d31256a29e8a918666da`.
CI, Quality, Benchmark, CodeQL, and README Consistency succeeded. PR #279's
React Frontend check passed; main did not trigger Frontend because no frontend
paths changed.

After release-candidate checks pass, push this branch and create a release PR
for review. Do not merge the release PR in this preparation stage.

## No dependency changes

Only the authorized version metadata, CHANGELOG, and readiness documentation
files are changed. The frontend lockfile changes only its top-level version and
`packages[""].version`; dependency entries remain unchanged.

## Tagging/GitHub Release/PyPI not run

Tag creation, GitHub Release creation, and PyPI publication are separate later
steps and are not run in this preparation stage.
