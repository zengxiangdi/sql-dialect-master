# Release 1.11.0 Readiness

Date: 2026-11-10

## Included in this release

1. `DistinctCountPlan` support in the query IR for schema-aware composite
   primary-key entity counts.
2. Derived `SELECT DISTINCT` rendering over group and identity columns,
   followed by outer `COUNT(*)`, GROUP BY, ORDER BY, and LIMIT clauses.
3. NULL identity-component filtering inside the derived query.
4. WHERE and `whose` predicates scoped to the derived input table.

## Verification evidence

The release branch is based on the squash merge of PR #277. Required main
workflows for the merge commit succeeded. The frontend workflow was skipped on
the main push by its frontend path filter; PR #277's frontend check passed.

| Check | Release-candidate result |
| --- | --- |
| Full Python test suite | Pending release-candidate run |
| Backend coverage, minimum 91% | Pending release-candidate run |
| Mypy, Ruff, and Bandit | Pending release-candidate run |
| Project `pip check` | Pending release-candidate run |
| README consistency and release metadata | Pending release-candidate run |
| Isolated locked-environment pip-audit | Pending release-candidate run |
| React lint, typecheck, tests, and production build | PR #277 passed; 132 tests |
| Clean wheel and sdist build | Pending release-candidate run |
| Release artifact validation and `twine check` | Pending release-candidate run |
| `git diff --check` | Pending release-candidate run |

## DistinctCountPlan and renderer contracts

- `DistinctCountPlan` stores canonical identity columns and the NULL policy.
- `QueryIR` keeps the plan optional, preserving existing positional fields and
  the legacy ordering tuple.
- A plan renders an inner `SELECT DISTINCT` over group columns followed by
  identity columns, with case-insensitive duplicate projection removal.
- The inner query applies source conditions and `IS NOT NULL` predicates for
  each identity component.
- The outer query renders `COUNT(*) AS count`, GROUP BY, subject-column ORDER
  BY, and LIMIT.
- Joins, relationship paths, DISTINCT projection, non-COUNT aggregates, and
  aggregate-alias ordering fail closed.

## Composite primary-key SQL shape

For `primary_key = ["tenant_id", "id"]`:

```sql
SELECT user_id, COUNT(*) AS count
FROM (
    SELECT DISTINCT user_id, tenant_id, id
    FROM orders
    WHERE tenant_id IS NOT NULL AND id IS NOT NULL
) AS _distinct_targets
GROUP BY user_id
```

NULL identity components are excluded to match the existing single-column
`COUNT(DISTINCT pk)` behavior. If a group column overlaps an identity column,
the inner projection emits it once.

## Runtime evidence

SQLite and DuckDB tests verify duplicate-row deduplication, distinct tenant
identity handling, NULL identity exclusion, WHERE/whose predicates, and outer
group/order/limit behavior. SQLGlot parseability covers all 12 supported
dialects, and repeated generation is deterministic.

## No-schema compatibility

The no-schema path does not create a `DistinctCountPlan`. Existing extraction,
renderer behavior, SQL output, success status, and suggestions remain
unchanged.

## Known limitations / future prerequisites

- Relationship-target unique counts remain unsupported.
- Multi-hop COUNT/GROUP/group-label semantics remain unsupported.
- Zero-count and LEFT JOIN behavior remain unsupported.
- Multi-hop physical JOIN chains remain unsupported.
- Aggregate-alias ordering remains unsupported.
- No API, frontend, dependency, or lockfile changes are included.

## Release gate

The merged main commit is `d7f81faefbf58faffb0b00955db0898cc1b6dfc3`.
CI, Quality, Benchmark, CodeQL, and README Consistency succeeded on this
commit. PR #277 Frontend also passed; the main push did not trigger Frontend
because no frontend paths changed.

After all release-candidate checks pass, push this release branch and create a
release PR for review. Do not merge the release PR in this preparation stage.

## No dependency changes

Only the authorized version metadata, CHANGELOG, and readiness documentation
files are changed. The frontend lockfile changes only its top-level version and
`packages[""].version`; dependency entries remain unchanged.

## Tagging/GitHub Release/PyPI not run

Tag creation, GitHub Release creation, and PyPI publication are separate later
steps and are not run in this preparation stage.
