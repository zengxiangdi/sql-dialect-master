# Release 1.3.0 Readiness

Date: 2026-10-25

## Included in this release

1. Schema-aware NL2SQL with optional tables, columns, relationships, prompt grounding, and generated SQL reference validation.
2. NL2SQL LLM experience improvements: fixed fallback messages, Copy SQL, and Regenerate actions.
3. Conversion-history favorites, All/Favorites filtering, and ten-entry pagination.
4. `certifi` security update for GHSA-6q48-6c7w-9gw2.
5. Security updates for the QA/build toolchain: `filelock` 4.2.4 and `setuptools` 84.2.1.
6. Engineering baseline: branch coverage, progressive mypy, and cross-platform lockfiles.

## Verification evidence

The release preparation checks completed on 2026-10-25:

- `scripts/verify_readme_consistency.py`: passed.
- `scripts/verify_release.py --tag v1.3.0`: passed.
- Python tests: 3,071 passed, 39 skipped.
- Python coverage: 92.57% total with the configured 91% gate; branch coverage is enabled.
- Mypy: six configured modules, no issues.
- Ruff, Bandit, and `pip check`: passed.
- React lint, typecheck, tests (12 files / 127 tests), and production build: passed.
- Isolated lock verification in `/tmp/sdm-lock-verify-2`: installation, pip check,
  pytest, coverage, mypy, Ruff, and Bandit passed.
- Isolated `/tmp/sdm-lock-verify-2/bin/pip-audit`: no known vulnerabilities;
  the editable local project was skipped because it is not published on PyPI.
- Package build: passed; `dist/` contains exactly one 1.3.0 wheel and one 1.3.0
  sdist. Release verification with `--dist` and `twine check`: passed. The
  wheel contains both canonical JSON data files and no tests, benchmarks, or
  `.env` files.
- `git diff --check` and repository secret checks passed.

The two security pins were generated with uv while preserving all other lock
versions: `filelock==4.2.4` and `setuptools==84.2.1`.

## LLM and schema safety

- The optional NL2SQL LLM is disabled by default.
- The API key is server-side only and is never stored in frontend code,
  browser storage, logs, or committed files.
- When enabled, natural-language text, hints, and supplied schema content are
  sent to the configured provider.
- Generated output is accepted only as one read-only `SELECT`/`UNION`; DML
  continues through deterministic generation.
- Provider errors and rejected output use the existing fallback behavior.
- Schema validation rejects unknown table and column references when schema
  metadata is provided.

## Release gate

After pushing `main`, wait for all required CI workflows to pass, including
Quality (with mypy), React Frontend, Benchmark, CI, CodeQL, and README
Consistency. Only after CI is green should an annotated tag `v1.3.0` be
created.

Tagging, GitHub Release creation, and PyPI publication have not been run.
There are no breaking API changes; the NL2SQL schema and response additions
are optional.
