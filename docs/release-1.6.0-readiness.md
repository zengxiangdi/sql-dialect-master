# Release 1.6.0 Readiness

Date: 2026-11-03

## Included in this release

1. Schema-aware `whose` predicates for quoted strings, signed numbers, NULL,
   date literals, and single-token CJK values.
2. Explicit `joined on` clauses for one qualified equality with INNER, LEFT,
   and RIGHT joins, relationship consistency checks, and a controlled
   no-relationship path.
3. Relationship-backed `joined with` physical joins with INNER, LEFT, and
   RIGHT support while bare `with` remains EXISTS.
4. Projection and predicate masking for explicit whose and join clauses.

## Verification evidence

All release-candidate checks passed on `release/1.6.0` after the version
bump. The distribution artifacts were rebuilt from a clean `dist/`.

| Check | Release-candidate result |
| --- | --- |
| Full Python test suite | 3694 passed, 39 skipped |
| Backend coverage, minimum 91% | 92.31%, gate passed |
| Mypy, Ruff, and Bandit | Passed |
| Project `pip check` | No broken requirements found |
| README consistency and release metadata | Passed for v1.6.0 |
| Isolated locked-environment pip-audit | 76 packages, 0 known vulnerabilities; msgpack 1.2.3 |
| React lint, typecheck, tests, and production build | Passed; 12 test files, 127 tests |
| Clean wheel and sdist build | Passed |
| Release artifact validation and `twine check` | Both artifacts passed |
| `git diff --check` and allowed-file scope | Passed; only the 8 authorized release files |

## Whose / joined on / joined with contracts

- `whose` accepts schema columns with quoted strings, signed numeric literals,
  NULL checks, date literals, single-token ASCII values, and single-token CJK
  values. Multi-token unquoted values, reserved words, functions, unknown
  columns, and complex OR/multiple-whose forms fail closed.
- The complete whose clause is masked from projection and shared predicate
  extraction. Explicit projections remain available, while an implicit query
  uses `SELECT *` with the whose predicate in WHERE.
- `joined on` accepts one qualified `table.column = table.column` equality and
  preserves its endpoint order. INNER/LEFT/RIGHT are supported. Unknown or
  ambiguous endpoints, aliases, non-equality expressions, multiple conditions,
  self-joins, extra tables, and group-plus-join combinations fail closed.
- An explicit joined-on condition may prove a relationship when both endpoints
  are valid schema columns. If a relationship is declared for the table pair,
  the endpoints must match exactly.
- `joined with` requires exactly one raw schema relationship and emits a
  physical join. It supports INNER/LEFT/RIGHT and consumes its target span.
  Bare `with` continues to use EXISTS.
- Without a schema, existing deterministic behavior remains unchanged.

## Security and compatibility

No dependency or lockfile changes are included in this release. The release
candidate must be checked in an isolated environment installed from the locked
requirements, including pip-audit. The project `.venv`, local `.env`, and
semantic lockfile are not modified for release checks.

No API shape changes or frontend source changes are included. Existing P0,
projection, grouping, label, and predicate-safety regressions remain covered.

## Known limitations

- Diagnostics for unmapped natural-language columns remain outside this
  release.
- Multi-column ORDER BY remains unsupported and fails closed where enforced.
- Table aliases and complex boolean ON/whose expressions are unsupported.
- Grouping combined with explicit joins fails closed.
- Multi-hop relationships and composite-primary-key support remain outside this
  release.

## Release gate

The P1.3 merge commit is `f83a3d0485de0b3b29d07151f09d5e232280daa5`. CI,
Quality, Benchmark, CodeQL, and README Consistency succeeded on this main
commit. The Frontend workflow did not trigger because the change set contains
no frontend paths; the existing approved local lint, typecheck, test, and build
verification remains the frontend gate record.

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
for v1.6.0.
