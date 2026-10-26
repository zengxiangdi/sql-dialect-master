# Release 1.4.0 Readiness

Date: 2026-10-26

## Included in this release

1. Schema-aware deterministic NL2SQL with optional tables, columns, hints,
   and explicit relationships.
2. Schema-driven EXISTS/NOT EXISTS and INNER/LEFT/RIGHT join generation,
   including reverse relationship traversal.
3. Shared SQLGlot table, alias, CTE, and column validation for deterministic
   and LLM generation.
4. Fail-closed handling for unknown mapped tables, ambiguous columns, missing
   relationships, unsupported join forms, and invalid schema shapes.
5. Relationship endpoint validation and a 200-relationship API limit.

## Verification evidence

The following checks are run before the release commit is pushed:

- Full Python test suite and backend coverage.
- Mypy, Ruff, Bandit, pip check, README consistency, and release metadata.
- React lint, typecheck, tests, and production build.
- Clean wheel and sdist build, release artifact validation, and `twine check`.
- `git diff --check`.

Results are recorded in the release execution report. The release commit is
not considered ready until every required check passes.

## Schema safety

- Without a schema, deterministic behavior is unchanged.
- Empty schema objects fail closed for physical table references.
- Empty `columns` metadata means the table's columns are unrestricted.
- Relationship endpoints are validated at the API boundary and relationships
  are limited to 200 entries.
- Unknown mapped tables, ambiguous columns, missing relationships, and
  unsupported join forms fail closed without producing SQL.
- Natural-language column names outside the deterministic mapping may be
  ignored; use `column_hints` or the LLM path.
- LLM generation remains disabled by default; the server-side key is never
  stored in frontend code, browser storage, logs, or committed files.

## Release gate

After pushing the release branch and merging it into `main`, wait for all
required CI workflows to pass. Only after CI is green should an annotated tag
`v1.4.0` be created.

Tagging, GitHub Release creation, and PyPI publication have not been run.
There are no dependency changes or lockfile dependency changes, and there are
no breaking API changes; all schema fields remain optional.
