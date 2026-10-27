# Release 1.5.0 Readiness

Date: 2026-10-28

## Included in this release

1. Schema-aware projection and DISTINCT resolution with columns in text order,
   case-insensitive and qualified names, safe simple plurals, and deduplication.
2. Single-column ORDER BY resolution for explicit order-by and sort-by phrases,
   without incidental ordering from table words such as `order amounts`.
3. Schema-aware single-column GROUP BY and COUNT while preserving AVG, SUM,
   MAX, and MIN aggregates and avoiding implicit grouping for aggregate-only
   requests.
4. Entity-count versus quantity-measure resolution, including inventory and
   purchase quantities, with data words excluded from entity counters.
5. English `per`/`each` and Chinese `每个`/`各个`/`每位` group labels, with subject
   table selection, explicit column aliases, forward relationships, and
   label-matching foreign keys.
6. A msgpack 1.2.3 security pin for CVE-2026-114613.

## Verification evidence

All local release-candidate checks passed on `release/1.5.0` after the
version bump. The distribution artifacts were rebuilt from a clean `dist/`.

| Check | Release-candidate result |
| --- | --- |
| Full Python test suite | 3545 passed, 39 skipped |
| Backend coverage, minimum 91% | 92.38%, gate passed |
| Mypy, Ruff, and Bandit | Passed |
| Project `pip check` | No broken requirements found |
| README consistency and release metadata | Passed for v1.5.0 |
| Isolated locked-environment pip-audit | 76 packages, 0 known vulnerabilities; msgpack 1.2.3 |
| React lint, typecheck, tests, and build | Passed; 12 test files, 127 tests |
| Clean wheel and sdist build | Passed |
| Release artifact validation and `twine check` | Both artifacts passed |
| `git diff --check` and allowed-file scope | Passed; only the 8 authorized release files |

Built artifacts:

- `sql_dialect_master-1.5.0-py3-none-any.whl`
- `sql_dialect_master-1.5.0.tar.gz`

## Schema-aware behavior and fail-closed contracts

- Single-table projections use schema canonical column names, preserve text
  order, and remove repeated columns. Quoted values are not projection
  candidates. Existing column-hint precedence is preserved.
- DISTINCT applies to the resolved projection, including `SELECT DISTINCT *`
  when there is no explicit projection.
- Explicit single-column ordering resolves the requested target against the
  selected table. Unknown targets and unsupported multi-column ordering fail
  closed. Requests without sorting intent do not gain an ORDER BY clause.
- Explicit group columns appear in SELECT alongside aggregates. COUNT-only
  and other aggregate-only requests do not gain an implicit GROUP BY clause.
- Entity phrases such as `订单数` and `员工数` express COUNT. Data words such as
  `数据`, `数据库`, `数字`, and `数组` do not become entity counters. Explicit
  inventory and purchase quantity measures require the matching subject table
  and its quantity column.
- Property labels such as `部门` resolve a unique subject-table column before
  considering a label table. Entity labels such as `用户` require a unique
  schema label table and a unique subject table.
- Relationship-based label grouping accepts only original forward
  subject-to-label declarations with label-matching foreign-key names. A
  reverse-only declaration does not justify grouping by the subject primary
  key. Where permitted, a unique matching subject-table foreign key can still
  resolve the label independently of a reverse declaration.
- Missing label tables, missing foreign keys, multiple candidate tables or
  relationships, non-matching relationship foreign keys, and unsupported
  multiple group columns fail closed. Resolved label tables are not emitted
  as extra JOINs.
- Without a schema, existing deterministic behavior is unchanged. Existing
  predicate-safety behavior remains covered by the regression suite.

## Security update (msgpack CVE)

msgpack is pinned to 1.2.3 in the shared constraints and locked dependencies
for CVE-2026-114613. It is a transitive dependency used by cachecontrol and
pip-audit. The release candidate must be audited in a newly isolated virtual
environment installed from `requirements-lock.txt`; the project `.venv`, local
`.env`, and semantic lockfile are not modified for this check.

## Known limitations

- Multi-column ORDER BY remains unsupported and fails closed in the
  schema-aware path.
- `whose` predicate syntax and explicit `joined on/with` conditions are outside
  this release; their existing behavior is unchanged.
- Diagnostics for unmapped natural-language columns are not included. Schema
  validation still covers the references that deterministic parsing recognizes;
  it does not establish that every natural-language word was mapped.
- Fuzzy matching, multi-hop relationships, and composite-primary-key support
  are outside this release.

## Release gate

The P1 merge commit is `acfa9293d48ff0510035107160eaf79fa8d06203`. CI, Quality,
Benchmark, CodeQL, and README Consistency succeeded on this main commit.
React Frontend was excluded by its path filter because frontend files were
unchanged. With user approval, local main-commit lint, typecheck, 127 tests,
and build results satisfy that preparation gate. The release PR must also
pass the React Frontend workflow before this release can proceed.

After all release-candidate checks pass, push the release branch and create a
release PR for review. Do not merge that release PR in this preparation stage.
Any later release-PR merge must be followed by successful required main CI
before an annotated `v1.5.0` tag can be considered in a separately authorized
publication stage.

## No dependency changes beyond the msgpack security pin

The msgpack 1.2.3 security pin is the only dependency change included since
1.4.1. The release-preparation commit changes version metadata, the CHANGELOG,
and this readiness document only. Frontend package-lock changes are limited to
its top-level version and `packages[""].version`; dependency entries remain
unchanged. There are no API shape changes or frontend source-code changes.

## Tagging/GitHub Release/PyPI not run

Tag creation, GitHub Release creation, and PyPI publication have not been run
for v1.5.0. This preparation stage does not perform those actions.
