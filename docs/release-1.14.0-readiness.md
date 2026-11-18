# Release 1.14.0 Readiness

Date: 2026-11-18

## Included in this release

1. Zero-count semantics for schema-aware unique target counts.
2. Target/intermediate filter ownership for distinct target counts.
3. Count/group ordering for path counts and grouped single-table unique counts.
4. Multiple `whose` predicates with optional repeated `whose` and canonical
   duplicate rejection.
5. Three-hop schema-aware unique target paths.
6. Explicit physical multi-hop INNER JOIN chains with base-owned projection and
   conditions.

## Verification evidence

The release branch is based on main commit `837a210`.

| Check | Release-candidate result |
| --- | --- |
| Full Python test suite | 4905 passed, 39 skipped |
| Backend coverage, minimum 91% | 91.82%, gate passed |
| Mypy, Ruff, and Bandit | Passed |
| Project `pip check` | No broken requirements found |
| README consistency and release metadata | Passed for v1.14.0 |
| Clean wheel and sdist build | Passed |
| Release artifact validation and `twine check` | Both artifacts passed |
| `git diff --check` | Passed |

## Unique-count contracts

- Zero-count path counts use a subject identity baseline, a LEFT JOIN to the
  aggregated target counts, and `COALESCE` for missing targets.
- Zero baselines contain subject conditions only; intermediate and target
  conditions constrain the count input.
- Path conditions preserve source order; subject conditions are rendered first.
- Count and group ordering is supported for path counts, grouped flat/single
  counts, and zero-count `COALESCE` output.
- Multiple predicates support `and`, English commas, and Chinese commas; the
  repeated `whose` keyword is optional.
- Canonical duplicate rejection normalizes operators and numeric literals
  while preserving string-literal case.
- Three-hop unique target paths require a unique shortest path and validate
  every composite relationship endpoint.
- One-hop and two-hop output remains compatible outside the deliberate new
  zero/filter/ordering/predicate capabilities.

## Physical-chain contracts

- `joined with` chains support two or three INNER relationship edges.
- The chain base is the single table mention before the chain or the table
  hint; conflicts fail closed.
- Every consecutive pair requires one unique relationship; reverse traversal
  and composite PK completeness are supported.
- Projection, WHERE/whose, GROUP BY, aggregate arguments, ORDER BY, and LIMIT
  are base-owned.
- Fan-out follows normal SQL row semantics; no implicit DISTINCT or entity
  count inference is added.
- Physical chains cannot be mixed with unique/path counts or relational
  EXISTS.

## Fail-closed rules

Ambiguous paths, missing or multiple relationships, cycles, repeated tables,
four-plus hops, incomplete composite relationships, joined-table
projection/filter ownership, unqualified shared columns, multi-hop `SELECT *`,
unsupported join kinds, and physical-chain/EXISTS/unique/path mixing fail
closed. No-schema behavior is unchanged.

## Known limitations

- Association counts for composite subject identities are unsupported.
- Multi-hop LEFT/RIGHT joins are unsupported.
- Joined-table projection/filter ownership is deferred.
- Physical-chain `IN`, `BETWEEN`, and `LIKE` filters fail closed.
- Other unsupported physical-chain forms fail closed rather than emitting
  ambiguous SQL.
- No API or dependency changes are included; the frontend package version is
  aligned with the release.

## Release gate

The release branch is based on `837a2107b27401325d35023eca5612d7c4665dab`.
The release PR must pass CI, Quality, Benchmark, CodeQL, README Consistency,
and Frontend checks before merge. After merge, tag `v1.14.0` on the release
commit and let the tag-triggered Release workflow build, verify, and publish
the GitHub release distributions. PyPI publication remains a separate
post-release workflow step.
