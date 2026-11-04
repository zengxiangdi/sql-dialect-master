# Release 1.7.0 Readiness

Date: 2026-11-04

## Included in this release

1. Schema-aware diagnostics suggestions for high-confidence unmapped
   references on successful deterministic generation.
2. Diagnostics for `with <token>`, explicit projection conjunctions, and
   `by <token>` contexts, excluding schema tables and columns, known values,
   SQL keywords, quoted text, and ordinary prose.
3. Accessible display of non-empty suggestions on successful React NL2SQL
   results.
4. Stable diagnostic ordering, deduplication, and a maximum of three messages.

## Verification evidence

All release-candidate checks passed on `release/1.7.0` after the version
bump. The distribution artifacts were rebuilt from a clean `dist/`.

| Check | Release-candidate result |
| --- | --- |
| Full Python test suite | 3706 passed, 39 skipped |
| Backend coverage, minimum 91% | 92.37%, gate passed |
| Mypy, Ruff, and Bandit | Passed |
| Project `pip check` | No broken requirements found |
| README consistency and release metadata | Passed for v1.7.0 |
| Isolated locked-environment pip-audit | 76 packages, 0 known vulnerabilities; msgpack 1.2.3 |
| React lint, typecheck, tests, and production build | Passed; 12 test files, 128 tests |
| Clean wheel and sdist build | Passed |
| Release artifact validation and `twine check` | Both artifacts passed |
| `git diff --check` and allowed-file scope | Passed; only the 8 authorized release files |

## Diagnostics B1 contracts and exclusions

- Diagnostics are emitted only for successful schema-aware deterministic results.
- Existing SQL, `success`, `schema_used`, `explanation`, failure suggestions,
  and no-schema output remain unchanged.
- High-confidence contexts include `with <token>`, explicit projection
  conjunctions, and `by <token>` identifiers.
- Schema tables, canonical columns, mapped aliases already resolved, known
  values, SQL keywords, quoted text, comments, and ordinary prose are excluded.
- Chinese free-word scanning is not enabled. Structured diagnostics API fields
  and metrics-only diagnostics are not included.
- Suggestions are deduplicated, ordered by text position, capped at three, and
  carried through the existing `suggestions` field.

## No-schema compatibility

All B1 diagnostics are gated to successful schema-aware results. The no-schema
path and its existing suggestions remain unchanged. Existing P0/P1 predicate,
projection, grouping, label, join, and whose behavior remains covered by the
regression suite.

## Known limitations

- Structured diagnostics API fields remain outside this release.
- Chinese free-word scanning remains outside this release.
- Metrics-only diagnostics remain outside this release.
- Multi-column ORDER BY remains unsupported and fails closed where enforced.
- Fuzzy matching and broader natural-language column inference remain outside
  this release.

## Release gate

The B1 merge commit is `7bb0d2b789d81b704f46965ba6c252b5ed2b1e8e`. CI, Quality,
Benchmark, CodeQL, README Consistency, and React Frontend succeeded on this
main commit.

After all release-candidate checks pass, push the release branch and create a
release PR for review. Do not merge that release PR in this preparation stage.
Tagging, GitHub Release creation, and PyPI publication are separate later
steps and are not run here.

## No dependency changes

The release-preparation commit changes only version metadata, CHANGELOG, and
this readiness document. The frontend lockfile changes only its top-level
version and `packages[""].version`; dependency entries remain unchanged.

## Tagging/GitHub Release/PyPI not run

Tag creation, GitHub Release creation, and PyPI publication have not been run
for v1.7.0.
