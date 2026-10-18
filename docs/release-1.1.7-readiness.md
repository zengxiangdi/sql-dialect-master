# Release 1.1.7 readiness

Date: 2026-10-19

## Scope

This release packages three groups of changes merged on `main`:

- React workspace handoff and dialect selection: History entries can reopen
  Convert or Diff, NL2SQL output can be sent to Diff, successful conversions
  can open Diff, and workspace dialects persist through URL parameters.
- Production deployment hardening: trusted-proxy client identity, monotonic
  in-memory rate limiting, response cache policy, the deprecated
  `X-XSS-Protection: 0` value, and the production deployment guide.
- Benchmark observability: sync and async per-statement latency in the
  transpiler benchmark and CI summary.

No public API, SDK signature, error code, response field, or cache-key
semantics changed.

## Verification evidence

The following commands passed on 2026-10-19:

- `.venv/bin/python scripts/verify_readme_consistency.py` — version 1.1.7,
  12 dialects, frontend and benchmark paths verified.
- `.venv/bin/python scripts/verify_release.py --tag v1.1.7` — release metadata
  verified.
- `.venv/bin/python -m pytest -q` — 2660 passed, 39 skipped, 2 warnings.
- `cd frontend-react && npm run lint` — passed.
- `cd frontend-react && npm run typecheck` — passed.
- `cd frontend-react && npm test` — 7 files, 31 tests passed.
- `cd frontend-react && npm run build` — Vite transformed 1946 modules and
  completed successfully.
- `.venv/bin/python -m build` — built one 1.1.7 wheel and one 1.1.7 sdist.
- `.venv/bin/python scripts/verify_release.py --tag v1.1.7 --dist dist` —
  artifacts and package contents verified.
- `.venv/bin/python -m twine check dist/*` — both artifacts passed.
- `git diff --check` — passed before release staging.

The release wheel contains `backend/core/functions_db.json` and
`backend/core/type_mapping.json`, and excludes tests and benchmarks.

## Release gate

After the release commit is pushed to `main`, all required CI checks must be
completed successfully. Only after that gate passes should the release
operator create the annotated tag `v1.1.7` and continue with the separately
authorized GitHub Release/PyPI steps. This readiness document does not claim
that tag or publish steps have been executed.

## Deferred work

Strict cross-platform lockfile regeneration and Docker/containerization are
not included in this release.
