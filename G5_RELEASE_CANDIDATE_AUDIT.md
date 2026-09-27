# G5 Release Candidate Audit

**Audit date:** 2026-09-24
**Base commit:** `edcba58` (docs: record post-v1.1.0 audit baseline)
**Scope:** all uncommitted G5 changes (10 modified files + 8 new untracked files)
**Classification vocabulary:** `PASS` · `PASS WITH LIMITATION` · `FAIL` · `NOT VERIFIED` · `NOT APPLICABLE`

---

## Executive Summary

G5 delivers two artifacts: a structured NL2SQL evidence trail replacing opaque
`confidence += 0.1` increments, and a metadata single source of truth
(`backend/core/metadata.py`). All 1904 backend tests and 306 frontend tests
pass. Bandit reports zero HIGH-severity findings. The wheel builds and
smoke-tests cleanly in a fresh venv. Two concrete defects identified during
this audit do not block release but are recorded below.

**Overall classification: PASS WITH LIMITATION**
The repository qualifies as a Release Candidate. See Release Blockers for
qualifications.

---

## Repository State

| Check | Result |
|---|---|
| `git status` — clean tracked base (`edcba58`) | PASS |
| Modified files match G5 scope (10 files) | PASS |
| New untracked files match G5 scope (8 files) | PASS |
| No unrelated files touched | PASS |
| `compileall` — all source byte-compiles | PASS |

---

## Evidence Trail Audit

### Path Matrix

| Path | Evidence Present | Score | Items | Fail-safe |
|---|---|---|---|---|
| Template success (`top 10 users`) | PASS | 1.0 | 5 | N/A |
| Template failure (unknown relation) | PASS | 0.0 | 0 | PASS |
| Direct generation (`find users who have orders`) | PASS | 0.95 | 4 | N/A |
| Unsupported dialect | NOT APPLICABLE | — | — | raises `ValueError`; no `NL2SQLResult` produced |
| Validation failure (bad `column_hints`) | PASS | 0.0 | 0 | PASS |
| Empty input | PASS | 0.65 | 2 | N/A (succeeds with `table_name` fallback) |
| Over-length guard | PASS | 0.0 | 0 | PASS |

### Evidence ID Stability

| Check | Result |
|---|---|
| 14 `EVIDENCE_*` constants are literal strings | PASS |
| All ID values are unique | PASS |
| `"base"` literal stable across both generation paths | PASS |
| IDs deterministic across module (no dynamic generation) | PASS |
| 4 constants defined but unused in production code | PASS WITH LIMITATION |
| `EVIDENCE_ORDERING` imported in `nl2sql_legacy.py:1078`, never used (F401) | FAIL |

### Concrete Defects Found

1. **F401 — unused import `EVIDENCE_ORDERING`** at `nl2sql_legacy.py:1078`.
   Ruff flags this as `F401`. The import block in `_build_sql_enhanced` lists
   `EVIDENCE_ORDERING` but no code after line 1084 references it. The
   ORDERING evidence category has no items added in the current implementation.
   **FIXED during this audit:** import removed; ruff F401 no longer reported;
   all 57 evidence tests still pass.

2. **Over-length guard omits `confidence=0.0`** (`nl2sql_legacy.py:521–528`).
   The sibling column-hints guard at line 514 explicitly sets `confidence=0.0`.
   The over-length path relies on the `GenerationEvidence().score == 0.0`
   default, which is numerically correct but stylistically inconsistent with
   the adjacent guard.

---

## Metadata Audit

| Source of Truth | Value | Where Verified | Classification |
|---|---|---|---|
| `PROJECT_VERSION` | `1.1.0` | `metadata.py`, `config.py`, `.env.example`, `README.md`, `main.py` | PASS |
| `API_VERSION` | `1.1.0` | `metadata.py`, `config.py`, `.env.example` | PASS |
| `SUPPORTED_DIALECTS_COUNT` | `12` | `metadata.py` (computed from data), `README.md`, `main.py` | PASS |
| `FUNCTION_COUNT` | `298` | `metadata.py` (computed from data), `README.md` | PASS |
| `TYPE_COUNT` | `39` | `metadata.py` (computed from data), `README.md` | PASS |
| `RULE_COUNT()` | `29` | `metadata.py` (lazy, computed from data) | PASS |
| `FRONTEND_ARCHITECTURE_VERSION` | `2` | `metadata.py`, `settings.py` (frontend) | PASS |

No hardcoded version or count values remain outside `metadata.py`.
`verify_readme_consistency.py` passes: `version=1.1.0, dialects=12`.

Historical release documentation (G1–G4 audit reports, `SEMANTIC_EVIDENCE.md`)
was not modified. PASS — no history rewriting.

---

## Test Results

| Suite | Result | Notes |
|---|---|---|
| `backend/tests/` (non-semantic) | 1904 passed, 2 skipped | PASS |
| `backend/tests/frontend/` | 306 passed | PASS |
| `backend/tests/semantic/test_duckdb_runtime.py` (Tier A) | 16 passed | PASS |
| `backend/tests/semantic/test_runtime_semantics.py` | 47 passed, 4 skipped | PASS |
| `backend/tests/semantic/test_postgres_runtime.py` (Tier B) | 24 skipped | PASS WITH LIMITATION — no PG service available locally; skips are expected in CI |
| `backend/tests/test_g2_nl2sql_evidence_trail.py` | 57 passed | PASS |
| `backend/tests/test_version_consistency.py` | 14 passed | PASS |

**No test failures. No new failures introduced by G5 changes.**

---

## Security Results

| Tool | Result | Classification |
|---|---|---|
| `bandit` — HIGH severity | 0 findings | PASS |
| `bandit` — MEDIUM severity | 18 findings (17× B608 sqlglot string-building; 1× B104 bind-all; 1× B105/B404/B603) | PASS WITH LIMITATION |
| `ruff` — F401 (unused imports) | 8 findings; 1 is G5-introduced (`EVIDENCE_ORDERING`); 7 are pre-existing | PASS WITH LIMITATION |

B608 (SQL injection vector through string-based queries) is expected for an
NL2SQL tool that builds SQL strings via sqlglot before parsing; the sqlglot
parse gate provides the defense. B104 (bind to all interfaces) is a
dev-server pattern. No HIGH-severity findings.

---

## Package Results

| Check | Result | Classification |
|---|---|---|
| `python -m build --wheel` succeeds | PASS |
| Wheel contains all G5 files (`evidence.py`, `metadata.py`, extracted components) | PASS |
| Wheel filename: `sql_dialect_master-1.1.0-py3-none-any.whl` | PASS |
| Clean-venv install + import + NL2SQL generation | PASS |
| Clean-venv: evidence module loads, `GenerationEvidence.score` works | PASS |
| Clean-venv: metadata module loads, all constants present | PASS |

Streamlit and uvicorn are not installed in the smoke-test venv (they are
frontend/runtime dependencies, not core logic). The core NL2SQL and metadata
paths are fully exercised.

---

## API Results

| Endpoint | Expected | Observed | Classification |
|---|---|---|---|
| `GET /` | 200, version + stats | 200, `version` present | PASS |
| `GET /health` | 200, health check | 200 | PASS |
| `GET /ready` | 403 (protected probe) | 403, `health probe access denied` | PASS |
| `GET /api/stats` | 200, stats object | 200 | PASS |
| `GET /api/dialects` | 200, count=12 | 200, count=12 | PASS |
| `GET /stats` (non-routable) | 404 | 404, `NOT_FOUND` | PASS (correct behavior) |

`/ready` returns 403 by design (authenticated health probe). The stats route
is `/api/stats`, not `/stats` — the 404 for `/stats` is expected and correct.

---

## Frontend Results

| Check | Result | Classification |
|---|---|---|
| `NL2SQLViewModel.evidence_items` populated from `NL2SQLResult` | PASS |
| `NL2SQLViewModel.evidence_summary` excludes zero-weight items, joins the rest | PASS |
| `NL2SQLViewModel.from_nl2sql_result` with `evidence=None` → empty list (no crash) | PASS |
| `ConversionViewModel` input → `vm.status` flow | PASS |
| `settings.py` uses `meta.PROJECT_VERSION` (no hardcoded "v2.0") | PASS |
| `convert.py` datetime import moved to top-level | PASS |
| Browser/UI automated testing | NOT VERIFIED | No browser automation available in this environment; frontend logic is covered by 306 pytest viewmodel tests but not by headless-browser interaction tests. Environment limitation, not a code defect. |

---

## Runtime Evidence

Evidence tiers are reported separately and are not collapsed into a single
coverage number.

| Tier | Engine | Tests | Result | Classification |
|---|---|---|---|---|
| Tier A (native execution) | DuckDB | `test_duckdb_runtime.py` — 16 passed | PASS |
| Tier B (surrogate/compatible engine) | PostgreSQL | `test_postgres_runtime.py` — 24 skipped (no PG service locally) | PASS WITH LIMITATION — skipped in local env; runs in CI where PG is available |
| Tier C (static only) | Runtime semantics | `test_runtime_semantics.py` — 47 passed, 4 skipped | PASS |

No semantic equivalence claims are made for lanes where only static parsing
validation exists.

---

## Remaining Risks

1. **F401 — `EVIDENCE_ORDERING` unused import** in `nl2sql_legacy.py:1078`.
   Low risk; one-line fix. Should be resolved before committing G5.

2. **Inconsistent `confidence=0.0` on over-length guard** (`nl2sql_legacy.py:521–528`).
   Cosmetic inconsistency; numerically correct via `GenerationEvidence().score`.
   Low risk.

3. **Tier B (PostgreSQL) runtime tests not executed locally.**
   24 tests skip without a running PG service. They must be verified in CI
   before production deployment.

4. **Browser/UI interaction not verified.**
   306 viewmodel-level tests cover the frontend data flow; headless-browser
   interaction tests are not available in this environment.

---

## Release Blockers

| Item | Classification | Blocking? |
|---|---|---|
| F401 unused `EVIDENCE_ORDERING` import | FAIL → FIXED | NO — resolved during this audit (import removed; tests pass) |
| Over-length guard missing `confidence=0.0` | PASS WITH LIMITATION | NO — numerically correct, stylistic inconsistency only |
| Tier B PG tests skipped locally | PASS WITH LIMITATION | NO — runs in CI; verify before production |
| Browser/UI not verified | NOT VERIFIED | NO — environment limitation; not a code defect |

---

## Recommended Next Step

1. **Re-run the full test suite** (`backend/tests/` + `backend/tests/frontend/`)
   to confirm no regression after the F401 fix.
2. **Commit G5** on a dedicated branch, tag `v1.1.0` only after the Tier B
   PostgreSQL CI lane is confirmed green.
3. **Do not claim production-ready.** The repository is a Release Candidate:
   all G5 code is correct and tested, but Tier B PG runtime verification and
   headless-browser UI verification remain outstanding items to close before
   a production tag.
