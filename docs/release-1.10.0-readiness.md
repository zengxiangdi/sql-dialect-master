# Release 1.10.0 Readiness

Date: 2026-11-09

## Included in this release

1. Optional schema-table `primary_key` metadata supporting single-column and
   composite identities.
2. API, core, and frontend validation for primary-key identifiers, lengths,
   duplicates, and declared column membership.
3. Schema-aware single-table unique entity counts for explicit English and
   Chinese distinct/unique wording, rendered as `COUNT(DISTINCT primary_key)`.
4. Distinct counts with and without GROUP BY, plus selected-table WHERE and
   `whose` conditions.

## Verification evidence

The release branch is based on the squash merge of PR #275. Local release
checks cover the merged identity metadata and unique-count implementation.

| Check | Release-candidate result |
| --- | --- |
| Full Python test suite | 3855 passed, 39 skipped |
| Backend coverage, minimum 91% | 92.51%, gate passed |
| Mypy, Ruff, and Bandit | Passed |
| Project `pip check` | Pending release-candidate run |
| README consistency and release metadata | Pending release-candidate run |
| Isolated locked-environment pip-audit | Pending release-candidate run |
| React lint, typecheck, tests, and production build | Passed; 13 test files, 132 tests |
| Clean wheel and sdist build | Pending release-candidate run |
| Release artifact validation and `twine check` | Pending release-candidate run |
| `git diff --check` | Passed |

## Primary-key metadata contracts

- `primary_key` is optional on each schema table and supports one to eight
  identifiers.
- Empty lists, duplicate identifiers, invalid identifiers, and unknown columns
  fail validation when column metadata is present.
- Legacy schema JSON remains valid and omits `primary_key` when it was not
  supplied.
- Core normalization is case-insensitive, preserves canonical column spelling,
  and keeps unverified keys when column metadata is absent.
- No primary key is inferred from a column named `id`.

## Distinct entity count contracts

- Explicit English `count distinct`, `count unique`, and `number of distinct`
  wording, plus Chinese 不同/去重/唯一计数 wording, produces
  `COUNT(DISTINCT <single-column-primary-key>) AS count`.
- Both aggregate-only and existing single-column GROUP BY forms are supported.
- WHERE and `whose` predicates remain attached to the selected data table.
- Missing or composite primary keys, joins, relationship paths, non-COUNT
  aggregates, and DISTINCT projection plus unique-count combinations fail
  closed.
- Ordinary `COUNT(*)`, plain DISTINCT projection, and all no-schema behavior
  remain unchanged.

## No-schema compatibility

Identity metadata and unique-count handling are gated to schema-aware
generation. The no-schema extractor, SQL output, success status, and
suggestions remain unchanged.

## Known limitations / Batch 3 prerequisites

- Derived DISTINCT counts for composite primary keys remain unsupported.
- Relationship-target and multi-hop unique counts remain unsupported.
- Multi-hop COUNT/GROUP/group-label semantics remain unsupported.
- Zero-count and LEFT JOIN semantics remain unsupported.
- Multi-hop physical JOIN chains remain unsupported.
- Identity metadata is not yet used for multi-hop or relationship counts.

## Release gate

The merged main commit is `5db1313be93a64d56f4a842936da7be78048e64d`.
Required main workflows succeeded: CI, Quality, Benchmark, CodeQL, README
Consistency, and React Frontend.

After all release-candidate checks pass, push this release branch and create a
release PR for review. Do not merge the release PR in this preparation stage.

## No dependency changes

Only the authorized version metadata, CHANGELOG, and readiness documentation
files are changed. The frontend lockfile changes only its top-level version and
`packages[""].version`; dependency entries remain unchanged.

## Tagging/GitHub Release/PyPI not run

Tag creation, GitHub Release creation, and PyPI publication are separate later
steps and are not run in this preparation stage.
