# Release 1.8.0 Readiness

Date: 2026-11-05

## Included in this release

1. Schema-aware multi-column ORDER BY with comma and `and` separators,
   per-column directions, qualified subject columns, and a five-column limit.
2. Optional `QueryIR.orderings` while retaining the legacy `ordering` tuple.
3. Composition with whose and explicit joined-on/joined-with subject-table
   requests, plus DISTINCT when all ordering columns are projected.
4. Fail-closed validation for unsupported ordering forms and combinations.

## Verification evidence

All local release-candidate checks passed on `release/1.8.0` after the version
bump. The distribution artifacts were rebuilt from a clean `dist/`.

| Check | Release-candidate result |
| --- | --- |
| Full Python test suite | 3749 passed, 39 skipped |
| Backend coverage, minimum 91% | 92.51%, gate passed |
| Mypy, Ruff, and Bandit | Passed |
| Project `pip check` | No broken requirements found |
| README consistency and release metadata | Passed for v1.8.0 |
| Isolated locked-environment pip-audit | 76 packages, 0 known vulnerabilities; msgpack 1.2.3 |
| React lint, typecheck, tests, and production build | Passed; 12 test files, 128 tests |
| Clean wheel and sdist build | Passed |
| Release artifact validation and `twine check` | Both artifacts passed |
| `git diff --check` and allowed-file scope | Passed; only the 8 authorized release files |

## Multi-column ORDER BY contracts

- English order-by, ordered-by, sort-by, and sorted-by clauses accept commas,
  `and`, and mixed separators.
- Each ordering column has its own ASC/DESC direction; omitted direction is ASC.
- Columns resolve to canonical schema spelling on the selected subject table.
- At most five unique columns are accepted. Unknown, duplicate, empty,
  target-table, alias, function, expression, and constant terms fail closed.
- Chinese ordering words, aggregate aliases, GROUP/COUNT/aggregate, and group
  label combinations remain unsupported.

## IR compatibility and composition rules

`QueryIR.ordering` remains the legacy optional single-column tuple. The new
optional `orderings` list is used only by the schema-aware multi-column path.
The renderer prefers a non-empty list and otherwise preserves tuple behavior,
with ORDER BY after JOIN/WHERE/GROUP BY and before LIMIT.

Multi-column ordering composes with whose and explicit joined on/with only
when the ordering columns belong to the subject table. Target-table ordering
remains fail closed. DISTINCT requires an explicit projection containing every
ordering column; DISTINCT * and unprojected ordering columns fail closed.

## No-schema compatibility

The no-schema extractor, ordering tuple, and all no-schema output remain
unchanged. Existing P0/P1/P1.3/B1 behavior is covered by the regression suite.

## Known limitations

- Ordering by target-table columns is outside this release.
- Ordering by aggregate aliases is outside this release.
- GROUP BY and aggregate combinations with multi-column ordering fail closed.
- Chinese ordering words remain outside this release.
- Expressions, aliases, repeated columns, and more than five ordering columns
  are not accepted.

## Release gate

The multi-order merge commit is `44a508c94ee25c154904704c12c86a7a0770269d`. CI,
Quality, Benchmark, CodeQL, and README Consistency succeeded on this main
commit. Frontend did not trigger because the change set has no frontend paths;
release-candidate local frontend lint, typecheck, 128 tests, and build
verification passed. The release PR must also pass its React Frontend check.

After all release-candidate checks pass, push the release branch and create a
release PR for review. Do not merge that release PR in this preparation stage.
Tagging, GitHub Release creation, and PyPI publication are separate later
steps and are not run here.

## No dependency changes

The release-preparation commit changes only version metadata, CHANGELOG, and
this readiness document. The frontend lockfile changes only its top-level
version and `packages[""].version`; dependency entries remain unchanged.

## Tagging/GitHub Release/PyPI not run

Built artifacts:

- `sql_dialect_master-1.8.0-py3-none-any.whl`
- `sql_dialect_master-1.8.0.tar.gz`

Tag creation, GitHub Release creation, and PyPI publication have not been run
for v1.8.0.
