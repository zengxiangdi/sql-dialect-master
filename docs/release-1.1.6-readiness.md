# Release 1.1.6 readiness

Date: 2026-10-18

## Scope

This release packages the three changes merged on `main`:

- Transpiler performance: per-call compatibility evidence reuse, MySQL AST
  fast paths, GROUP_CONCAT lexical prefiltering, and security parse reuse.
- Frontend robustness: guarded storage access, bounded/truncated history with
  safe copy behavior, full active-draft persistence up to the backend's
  100,000-character limit, and build-time frontend version injection.
- Dependency and catalog maintenance: a runtime/dev/qa lock with unused
  Streamlit-era transitive dependencies removed, plus catalog docstrings that
  reference their canonical JSON data files.

No public API, SDK signature, error code, response field, or cache-key
semantics changed.

## Verification evidence

The following commands passed on 2026-10-18:

- `.venv/bin/python scripts/verify_readme_consistency.py` — version 1.1.6,
  12 dialects, frontend and benchmark paths verified.
- `.venv/bin/python scripts/verify_release.py --tag v1.1.6` — release metadata
  verified.
- `.venv/bin/python -m pytest -q` — 2625 passed, 39 skipped, 2 warnings.
- `cd frontend-react && npm run lint` — passed.
- `cd frontend-react && npm run typecheck` — passed.
- `cd frontend-react && npm test` — 5 files, 19 tests passed.
- `cd frontend-react && npm run build` — Vite transformed 1945 modules and
  completed successfully.
- `.venv/bin/python -m build` — built one 1.1.6 wheel and one 1.1.6 sdist.
- `.venv/bin/python scripts/verify_release.py --tag v1.1.6 --dist dist` —
  artifacts and package contents verified.
- `.venv/bin/python -m twine check dist/*` — both artifacts passed.
- `git diff --check` — passed before release staging.

The release build contains `backend/core/functions_db.json` and
`backend/core/type_mapping.json`, and excludes tests and benchmarks.

## Release gate

The release commit must be pushed to `main`, then all required CI checks must
be green. Only after that gate passes should the release operator create the
annotated tag `v1.1.6` and continue with the separately authorized GitHub
Release/PyPI steps. This readiness document does not claim that tag or publish
steps have been executed.
