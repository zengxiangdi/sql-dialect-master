# Release 1.2.0 readiness

Date: 2026-10-21

## Scope

- Redesigned the Function encyclopedia with a search/category toolbar,
  result summary, responsive cards, and dialect coverage. The full catalog
  of 298 functions is fetched with `limit=500` and revealed in client-side
  batches of 60 with Load more.
- Removed the Types page's silent 80-row cap. Every matching type is
  rendered, with an explicit shown/total result summary.
- Added an optional OpenRouter-compatible NL2SQL LLM path, disabled by
  default, with provider metadata, validation, fallback, and metrics.
- Unified the visual design of NL2SQL and shared controls, filled in missing
  CSS classes, and omitted the empty Function Parameters section.

There are no breaking API changes. NL2SQL response additions (`provider`,
`model`, and `fallback_reason`) are optional fields. The deterministic
generator's output, existing request fields, error envelope, error-code
taxonomy, and cache-key semantics are unchanged.

Release preparation changes only version metadata, CHANGELOG, this document,
and version assertions in tests. The frontend assertion derives from the
injected `__APP_VERSION__`; the metrics assertion derives from canonical
`PROJECT_VERSION`. Neither test hardcodes a release string. Business logic
is unchanged, and `docs/release-1.1.9-readiness.md` is retained.

## LLM safety and privacy

- LLM generation is disabled by default.
- The provider key belongs only on the server. It is not printed or included
  in the release commit, frontend, responses, or build artifacts. Release
  preparation does not read the local key or `.env` contents.
- Enabling this option sends natural-language text and table/column hints
  to OpenRouter. Sensitive content requires an appropriate provider policy.
- Only a single target-dialect SELECT/UNION is accepted. DDL, DML, multiple
  statements, SELECT INTO, nested writes, and locking statements are
  rejected. No generated SQL is executed.
- Failures fall back to the deterministic generator by default and expose
  only a fixed `fallback_reason`. Validation checks syntax and structure,
  not semantic correctness; generated SQL still needs human review.

## Verification evidence

The following commands passed locally on 2026-10-21 with Python 3.12.14:

- `.venv/bin/python -m pytest -q` — 2926 passed, 39 skipped, 2 warnings
  in 11.80 seconds.
- `.venv/bin/python -m pytest --cov=backend --cov-report=term-missing -q` —
  2926 passed, 39 skipped, 2 warnings in 59.71 seconds; total coverage
  94.13% (5828 statements, 342 missing), above the unchanged 93% gate.
- `.venv/bin/python -m pytest backend/tests/test_nl2sql_llm.py -q` —
  94 passed in 0.28 seconds.
- `.venv/bin/python -m pytest backend/tests/test_api_nl2sql_llm.py -q` —
  44 passed, 2 warnings in 0.52 seconds.
- `cd frontend-react && npm run lint` — passed.
- `cd frontend-react && npm run typecheck` — passed.
- `cd frontend-react && npm test` — 10 test files and 78 tests passed
  in 4.36 seconds.
- `cd frontend-react && npm run build` — passed; Vite transformed 1947
  modules. Local output is for verification, not deployment.
- `.venv/bin/python -m pip check` — no broken requirements found.
- `.venv/bin/python -m pip_audit` — no known vulnerabilities found. The
  installed Python module is named `pip_audit` (the CLI is `pip-audit`).
- `.venv/bin/python scripts/verify_readme_consistency.py` — version 1.2.0,
  frontend version fields, Python requirement, 12 dialects, and benchmark
  references verified.
- `.venv/bin/python scripts/verify_release.py --tag v1.2.0` — release
  metadata verified. The CHANGELOG heading is exactly
  `## [1.2.0] - 2026-10-21`.
- `.venv/bin/python -m build` — built one 1.2.0 wheel and one 1.2.0 sdist
  after safely removing only the two old distribution archives.
- `.venv/bin/python scripts/verify_release.py --tag v1.2.0 --dist dist` —
  release metadata and distribution contents verified.
- `.venv/bin/python -m twine check dist/*` — both distributions passed.
- `git diff --check` — passed before release staging.

The two warnings are existing FastAPI/Starlette deprecations concerning
HTTPX TestClient support and the AnyIO BlockingPortal alias. No dependency
was changed to suppress them. LLM tests use fake clients/MockTransport;
this release preparation makes no real provider calls.

Additional archive, privacy, and scope checks passed:

- `dist/` contains exactly `sql_dialect_master-1.2.0-py3-none-any.whl` and
  `sql_dialect_master-1.2.0.tar.gz`.
- Both archives contain `backend/core/functions_db.json` and
  `backend/core/type_mapping.json`, and exclude tests, benchmarks, `.env`,
  and caches.
- Wheel METADATA has `Version: 1.2.0` and the runtime dependency
  `httpx<1.0.0,>=0.27.0`.
- `.env` is untracked and ignored. The example LLM key is empty.
- Credential-signature scans of the worktree/staged/branch diffs, this
  document, frontend source/build output, and distribution contents found
  no OpenRouter credential. The scan uses credential format patterns
  without reading a real key or environment secret value.
- Frontend package/lock changes affect only the three release version
  fields; dependencies are unchanged.
- Current-version assertions in backend/frontend tests and scripts were
  audited. Historical fixtures and the Prometheus exposition format
  version were preserved.

## Release gate

Push the release-preparation commit to `main`, then wait for README
Consistency, React Frontend, Quality, Benchmark, CI, and CodeQL to complete
successfully for that exact commit. Only after that gate passes, and with
separate authorization, should the release operator create the annotated
tag `v1.2.0` and proceed through GitHub Release and PyPI publication.

This preparation step stops before tagging. No tag, GitHub Release, or PyPI
publication is recorded as completed here. Distribution files, egg-info,
caches, and build artifacts must not be included in the release commit.
