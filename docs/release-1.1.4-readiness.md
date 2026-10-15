# v1.1.4 release preparation

Reviewed on 2026-10-13. Release metadata is aligned to **1.1.4**, and
CHANGELOG.md records the intentional behavior changes under **[1.1.4]**.
This document records preparation evidence; GitHub Actions and the release
pages provide the publication status after the release commit is pushed.

## Implemented

- NL2SQL rejects empty/unknown input and unsupported DDL, matches English
  entities by word boundaries, bounds every date window, applies the configured
  confidence threshold, and returns parameter styles/markers plus evidence.
- Cached and lookup results are isolated from caller mutation.
- Parser, Diff, and static workspaces share single-statement validation. MySQL
  comment/subtraction handling is consistent across supported sqlglot versions.
- NL2SQL edits invalidate results. History normalizes fields and records failed
  conversions. Navigation validates widget payloads; statuses and colors share
  one vocabulary.
- Optional API-key authentication, bounded workers/queues, timeout correlation,
  and application-lifecycle cleanup are implemented.
- CI and release jobs validate metadata, Changelog, package data, and installed
  frontend startup. PyPI publishes the exact verified GitHub Release artifacts,
  with the release tag resolved to its commit.

## Local verification

All checks use the project `.venv` and require no external database.

| Check | Result |
|---|---|
| Full suite with locked runtime/semantic dependencies | 2935 passed, 39 skipped |
| SQL parser compatibility | sqlglot 30.18.0 and the preceding 30.22.0 review |
| Ruff E9/F, Bandit, compilation, diff whitespace | Passed |
| Dependency audit of requirements-lock.txt | No known vulnerabilities found |
| README and current-release metadata checks | Passed |
| Wheel/sdist build and Twine checks | Passed |
| Installed wheel SDK and React production build | Passed |
| Independent review of reported boundary failures | Resolved |

The skipped tests include PostgreSQL runtime cases and explicitly unsupported
runtime translations. DuckDB runs in-process. No native MySQL, Oracle, or SQL
Server execution is claimed. Existing CI owns the PostgreSQL service; local
release preparation does not require a running database.

## Publication gates

1. Validate pyproject.toml, backend/core/metadata.py (PROJECT_VERSION/API_VERSION),
   README.md, .env.example, and the dated `[1.1.4]` Changelog entry together.
2. Review and commit the fixes plus workflow changes. Push main so the updated
   workflow_run publisher definition is on the default branch before tagging.
3. Verify Python 3.11/3.12 CI, its semantic-runtime job, Quality, CodeQL,
   Benchmark, and README consistency at that exact commit.
4. Build/check the 1.1.4 artifacts and run:
   `.venv/bin/python scripts/verify_release.py --tag v1.1.4 --dist dist`.
5. Push the annotated v1.1.4 tag. Release waits for CI before uploading assets;
   PyPI then consumes those same assets. Verify both release pages and a fresh
   installation. Keep the existing PyPI trusted publisher for pypi.yml and the
   pypi environment.

## Intentional behavior changes to document

- Invalid function categories return 400; unsupported/low-confidence NL2SQL
  requests return failed generation rather than guessed successful SQL.
- History now includes failures. Input edits invalidate previous NL2SQL output.
- `SDM_NL2SQL_MAX_DATE_INTERVAL_DAYS` defaults to 36525. Optional `SDM_API_KEY`
  protects `/api/*`; `SDM_API_WORKERS` and `SDM_API_QUEUE_SIZE` both default to 4.
- A timed-out thread cannot be forcibly terminated: it retains a bounded slot
  until completion. Queue saturation returns 503, and request timeout returns
  504; readiness diagnostics keep their existing 503 schema.
- DML parameters are templates; bind values using the dialect/driver contract.
  Bare date requests can still produce schema placeholders, preserving the SDK's
  existing template behavior.
