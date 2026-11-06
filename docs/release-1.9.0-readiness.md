# Release 1.9.0 Readiness

Date: 2026-11-06

## Included in this release

1. Composite schema relationships with mutually exclusive legacy and
   `columns` formats, normalized column pairs, complete AND join conditions,
   and reverse traversal.
2. Two-hop unique shortest simple path resolution for schema-aware EXISTS and
   NOT EXISTS, with direct relationship preference and cycle/ambiguity bounds.
3. Nested EXISTS rendering where NOT EXISTS negates only the outer path.
4. Frontend legacy/composite schema relationship types and JSON support.

## Verification evidence

All local release-candidate checks passed on `release/1.9.0` after the version
bump. The distribution artifacts were rebuilt from a clean `dist/`.

| Check | Release-candidate result |
| --- | --- |
| Full Python test suite | 3798 passed, 39 skipped |
| Backend coverage, minimum 91% | 92.42%, gate passed |
| Mypy, Ruff, and Bandit | Passed |
| Project `pip check` | No broken requirements found |
| README consistency and release metadata | Passed for v1.9.0 |
| Isolated locked-environment pip-audit | 76 packages, 0 known vulnerabilities; msgpack 1.2.3 |
| React lint, typecheck, tests, and production build | Passed; 13 test files, 131 tests |
| Clean wheel and sdist build | Passed |
| Release artifact validation and `twine check` | Both artifacts passed |
| `git diff --check` and allowed-file scope | Passed; only the 8 authorized release files |

## Composite relationship contracts

- Legacy `{from_table, from_column, to_table, to_column}` relationships remain
  valid.
- Composite relationships use mutually exclusive `columns` pairs, preserving
  declaration order. Empty, duplicate, partial, unknown, or over-budget pairs
  fail closed at API/core boundaries.
- Composite relationships are one logical edge. Direct JOIN/EXISTS and
  joined-with conditions render every pair with AND; reverse traversal swaps
  every pair in order.
- Parallel relationships remain ambiguous and are not merged into a composite
  relationship. Partial joined-on matches against a composite relationship
  fail closed.
- Existing no-schema static relationship behavior remains unchanged.

## Two-hop EXISTS contracts and fail-closed rules

- Direct relationships are preferred over paths.
- Without a direct edge, a unique shortest simple path of at most two edges is
  resolved from raw schema relationships.
- Multiple shortest paths, cycles requiring repeated tables, missing endpoints,
  paths over two edges, and exhausted search budgets fail closed.
- Nested EXISTS preserves outer subject cardinality. NOT EXISTS negates only
  the outer path; inner path steps remain EXISTS.
- Multi-hop filters, GROUP/COUNT/labels, DISTINCT, physical JOIN chains, and
  joined-with multi-hop requests remain fail closed.

## API/frontend schema compatibility

The API accepts both legacy and composite relationship shapes while rejecting
mixed shapes through the existing validation envelope. Frontend TypeScript
uses a legacy/composite union and keeps the JSON textarea interface; no schema
editor redesign is included.

## No-schema compatibility

All new path and composite logic is gated to schema-aware generation. The
no-schema extractor, static relationship mappings, SQL, success status, and
suggestions remain unchanged. Existing P0/P1/P1.3/B1/multi-order regressions
remain covered.

## SQLite runtime evidence

In-memory SQLite tests verify that nested EXISTS returns each matching user
once, excludes users without a matching path, and that composite tenant pairs
prevent cross-tenant matches. SQLGlot parsing covers the supported dialect set.

## Known limitations / Batch 3 prerequisites

- Multi-hop COUNT/GROUP semantics remain outside this release.
- Filter ownership inside intermediate path steps is unsupported.
- Multi-hop physical JOIN chains remain unsupported.
- PK/unique identity metadata required for safe multi-hop entity counts is not
  included.
- Multi-hop group labels and target-table ordering remain unsupported.

## Release gate

The composite/multi-hop merge commit is `6bbbe61ed246380f4efbff116405a369bbe318bc`. CI,
Quality, Benchmark, CodeQL, README Consistency, and React Frontend succeeded on
this main commit.

After all release-candidate checks pass, push the release branch and create a
release PR for review. Do not merge that release PR in this preparation stage.
Release-candidate local frontend lint, typecheck, 131 tests, and build passed.
The release PR must also pass its React Frontend check. Tagging, GitHub Release
creation, and PyPI publication are separate later steps and are not run here.

## No dependency changes

The release-preparation commit changes only version metadata, CHANGELOG, and
this readiness document. The frontend lockfile changes only its top-level
version and `packages[""].version`; dependency entries remain unchanged.

## Tagging/GitHub Release/PyPI not run

Built artifacts:

- `sql_dialect_master-1.9.0-py3-none-any.whl`
- `sql_dialect_master-1.9.0.tar.gz`

Tag creation, GitHub Release creation, and PyPI publication have not been run
for v1.9.0.
