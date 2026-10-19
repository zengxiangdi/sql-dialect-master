# Release 1.1.8 readiness

Date: 2026-10-19

## Scope

This release packages three groups of changes merged on `main`:

- Protected Prometheus metrics: the opt-in `GET /metrics` endpoint requires
  a dedicated token and reports HTTP traffic, latency, rate-limit rejections,
  worker capacity/rejections/timeouts, conversion results, and cache statistics.
- Coverage reporting and SDK contract tests: backend line coverage is reported
  in CI, validators/parser/type-mapping/function-lookup contracts have additional
  tests, and the measured coverage floor is `fail_under = 93`.
- Runtime dependency: `prometheus-client>=0.20.0,<1.0.0`, pinned to `0.26.0`
  in `requirements-lock.txt`.

Metrics are per-process. Multiprocess aggregation is not included in this
release. Existing public API/SDK signatures, error codes, response fields,
and cache-key semantics are unchanged.

## Verification evidence

The following commands passed on 2026-10-19:

- `.venv/bin/python scripts/verify_readme_consistency.py` — version 1.1.8,
  12 dialects, frontend versions, and benchmark references verified.
- `.venv/bin/python scripts/verify_release.py --tag v1.1.8` — release metadata
  verified; the CHANGELOG heading is exactly `## [1.1.8] - 2026-10-19`.
- `.venv/bin/python -m pytest -q` — 2748 passed, 39 skipped, 2 warnings.
- `.venv/bin/python -m pytest --cov=backend --cov-report=term-missing -q` —
  2748 passed, 39 skipped, 2 warnings; coverage 93.90% (5621 statements,
  343 missing), exceeding the unchanged 93% floor.
- `cd frontend-react && npm run lint` — passed.
- `cd frontend-react && npm run typecheck` — passed.
- `cd frontend-react && npm test` — 7 files, 31 tests passed.
- `cd frontend-react && npm run build` — Vite transformed 1946 modules and
  completed successfully.
- `.venv/bin/python -m pip check` — no broken requirements found.
- `.venv/bin/python -m pip_audit --timeout 30` — no known vulnerabilities found.
- `.venv/bin/python -m build` — built one 1.1.8 wheel and one 1.1.8 sdist.
- `.venv/bin/python scripts/verify_release.py --tag v1.1.8 --dist dist` —
  distribution metadata and package contents verified.
- `.venv/bin/python -m twine check dist/*` — both distributions passed.
- `git diff --check` — passed before release staging.

An additional wheel inspection confirmed that:

- `dist/` contained exactly `sql_dialect_master-1.1.8-py3-none-any.whl` and
  `sql_dialect_master-1.1.8.tar.gz`.
- The wheel includes `backend/core/functions_db.json` and
  `backend/core/type_mapping.json`, and excludes tests and benchmarks.
- Wheel METADATA has `Version: 1.1.8` and an unconditional runtime dependency
  on `prometheus-client<1.0.0,>=0.20.0`.

Frontend package and lock changes are limited to release version fields;
no dependency was upgraded. The frontend version-display test and metrics
build-info test have matching 1.1.8 expectations. Business code is unchanged
by this release commit. `docs/release-1.1.7-readiness.md` is retained unchanged.

## Release gate

Push the release commit to `main`, then wait for README Consistency, React
Frontend, Quality, Benchmark, CI, and CodeQL to complete successfully at that
commit. Only after that gate passes, and with separate authorization, should
the release operator create the annotated tag `v1.1.8` and proceed to the
GitHub Release and PyPI workflows.

This readiness document does not claim that tagging, GitHub Release creation,
or PyPI publication has been performed.
