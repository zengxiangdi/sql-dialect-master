# Release 1.4.1 Readiness

Date: 2026-10-27

## Included in this release

1. Deterministic NL2SQL status negation safety for English and Chinese forms.
2. Preservation of signed numeric thresholds and quoted string/date literals.
3. Isolation of text values from status predicate extraction.
4. Read-only handling of deleted-state phrases.
5. Linear quoted-predicate scanning to remove the CodeQL high-severity ReDoS
   risk.

## Verification evidence

The following checks are run before the release commit is pushed:

- Full Python test suite and backend coverage.
- Mypy, Ruff, Bandit, pip check, README consistency, and release metadata.
- React lint, typecheck, tests, and production build.
- Clean wheel and sdist build, release artifact validation, and `twine check`.
- `git diff --check`.

Results are recorded in the release execution report. The release commit is
not considered ready until every required check passes.

## Predicate safety and ReDoS fix

- Status negation supports `not`, `except`, `excluding`, `不是`, and `非`.
- Signed thresholds and quoted literals are preserved without truncation.
- Text values are excluded from status scanning.
- Deleted-state phrases remain SELECT predicates; explicit delete requests
  remain DELETE operations.
- Quoted predicate parsing uses linear scanning with escaped and doubled quote
  handling, avoiding nested regular-expression backtracking.

## Release gate

After pushing the release branch and merging it into `main`, wait for all
required CI workflows to pass. Only after CI is green should an annotated tag
`v1.4.1` be created.

Tagging, GitHub Release creation, and PyPI publication have not been run.
There are no dependency changes or lockfile dependency changes, and there are
no breaking API or schema format changes.
