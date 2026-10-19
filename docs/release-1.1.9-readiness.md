# Release 1.1.9 readiness

Date: 2026-10-20

## Scope

This release packages three groups of changes merged on `main`:

- Function detail drawer: on-demand details include parameters, notes,
  examples, and syntax across all 12 dialects, with loading/error/retry
  states, keyboard dismissal, and focus management.
- Lineage column relationships: columns are grouped by exact table keys,
  unqualified or ambiguous columns have a separate bucket, and join types,
  conditions, and counts are displayed as accessible text.
- REST batch conversion and metrics: `POST /api/convert/batch` preserves
  input order and exposes batch request, item, and size metrics.

Existing public API contracts, SDK batch methods, error-code taxonomy, and
cache-key semantics are unchanged. The batch endpoint is an additive API.
There are no new dependencies. Metrics remain per-process; multiprocess
aggregation is not included.

## Batch semantics

- HTTP 200 includes ordinary partial-failure and all-failed results.
  Top-level `success` is true only when every item succeeds, and each item
  retains its own error information and zero-based input index.
- HTTP 422 covers empty/oversized arrays and invalid request fields,
  including non-string items. Unsupported dialects return HTTP 400.
- HTTP 503/504 use the existing request-level error envelope and return no
  partial results. Capacity rejection preserves `Retry-After`.
- One batch occupies one worker slot and runs sequentially. The default
  100-item limit and 30-second queue-plus-execution budget apply to the
  whole batch, while the request body remains limited to 512 KiB.
- A 504 ends the HTTP wait but does not cancel the background batch. Its
  slot remains occupied until the worker finishes, and cache activity can
  continue. Such background completion does not increment the batch item
  counter because the handler never received the complete result list.

## Verification evidence

The following commands passed on 2026-10-20:

- `.venv/bin/python scripts/verify_readme_consistency.py` — version 1.1.9,
  frontend version fields, 12 dialects, and benchmark references verified.
- `.venv/bin/python scripts/verify_release.py --tag v1.1.9` — release metadata
  verified; the CHANGELOG heading is exactly `## [1.1.9] - 2026-10-20`.
- `.venv/bin/python -m pytest -q` — 2788 passed, 39 skipped, 2 warnings.
- `.venv/bin/python -m pytest --cov=backend --cov-report=term-missing -q` —
  2788 passed, 39 skipped, 2 warnings; coverage 93.95% (5669 statements,
  343 missing), exceeding the unchanged `fail_under = 93` floor.
- `.venv/bin/python -m pytest backend/tests/test_api_batch_convert.py -q` —
  40 passed, 2 warnings.
- `cd frontend-react && npm run lint` — passed.
- `cd frontend-react && npm run typecheck` — passed.
- `cd frontend-react && npm test` — 9 files, 59 tests passed.
- `cd frontend-react && npm run build` — passed; Vite transformed 1947 modules.
  These generated frontend files are for validation, not deployment.
- `.venv/bin/python -m pip check` — no broken requirements found.
- `.venv/bin/python -m pip_audit` — no known vulnerabilities found.
- `.venv/bin/python -m build` — built one 1.1.9 wheel and one 1.1.9 sdist
  after clearing stale distribution artifacts.
- `.venv/bin/python scripts/verify_release.py --tag v1.1.9 --dist dist` —
  distribution metadata and package contents verified.
- `.venv/bin/python -m twine check dist/*` — both distributions passed.
- `git diff --check` — passed before release staging.

Additional artifact and dependency checks confirmed that:

- `dist/` contains exactly `sql_dialect_master-1.1.9-py3-none-any.whl` and
  `sql_dialect_master-1.1.9.tar.gz`.
- Required `backend/core/functions_db.json` and `backend/core/type_mapping.json`
  are included; tests and benchmarks are excluded.
- Wheel METADATA has `Version: 1.1.9`. All 21 `Requires-Dist` entries
  (6 runtime and 15 optional-extra entries, including markers) match the
  pre-release `pyproject.toml` requirements. The existing `prometheus-client`
  requirement is unchanged.
- Frontend package and lock files differ only in their three release version
  fields; no dependency was upgraded.

The release-preparation changes are limited to version metadata, the
CHANGELOG, this readiness document, and matching version expectations in the
metrics and frontend shell tests. Business logic is unchanged.
`docs/release-1.1.8-readiness.md` is retained unchanged. Distribution files,
egg-info, caches, and build outputs are not part of the release commit.

## Release gate

Push the release-preparation commit to `main`, then wait for README
Consistency, React Frontend, Quality, Benchmark, CI, and CodeQL to complete
successfully at that commit. Only after that gate passes, and with separate
authorization, should the release operator create the annotated tag `v1.1.9`
and proceed through the existing GitHub Release and PyPI workflows.

This document records local verification. Tagging, GitHub Release creation,
and PyPI publication have not been performed by this preparation step.
