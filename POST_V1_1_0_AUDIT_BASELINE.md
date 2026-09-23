# Post-v1.1.0 Audit Baseline (G5)

> **Status: POST-AUDIT BASELINE — NOT A RELEASE.**
> This document records the engineering state of the repository *after* the
> post-v1.1.0 audit phases G1–G4 were closed, on commit `89fab1c`. It is a
> reference record for any *future* release decision. It does not replace
> `RELEASE_BASELINE.md` (the historical v1.0.1 release baseline), does not
> bump the version, and is not a release artifact.

**Recorded:** 2026-09-24
**Branch:** `chore/g5-audit-closure`
**Commit:** `89fab1c` (`docs: close post-v1.1.0 documentation consistency audit`)
**Version (unchanged):** 1.1.0 (`pyproject.toml`) — no version bump performed in G5
**Tag:** `v1.1.0` (still at `0602d94`); no new tag created in G5

---

## 1. Audit Phases

| Phase | Scope | Status |
|-------|-------|--------|
| G1 | NL2SQL Semantic Path Convergence | CLOSED — fail-closed join composition, D3 rolling/calendar semantics, structured predicate merge |
| G2 | TypeMapper Precision Warning Convergence | CLOSED — `get_precision_warnings` widened to NVARCHAR; TSQL NVARCHAR 4000-limit rule now reachable |
| G3 | Runtime Semantic Evidence Convergence | CLOSED — Tier A/B/C evidence boundary, hand-derived PG oracle, D3 deterministic fixtures |
| G4 | Documentation / Release Consistency | CLOSED — README v2 frontend architecture, dark/light theme model, type-count correction, historical release-doc labels, verifier hardening |
| G5 | Post-audit closure (this baseline) | CLOSED — this document + fresh CI evidence + deferred-item adjudication |

---

## 2. Frontend Architecture (current)

Sole entrypoint: `sdm_local_v2.py`. Top-level `frontend/` layout:

```
frontend/
├── core/          design_tokens.py (THEMES = {dark, light} — 2 themes), navigation.py, state.py, themes.py, styles.py, escaping.py, viewmodels.py
├── pages/         convert, nl2sql, diff, lineage, runtime, functions, types, templates, history, settings, query_analysis
├── ui/            command_palette, diff, editor, status
├── app_context_v2.py
└── templates_v2.py
```

The v1 paths (`frontend/tabs/`, `frontend/app_context.py`, `frontend/components.py`,
`frontend/themes.py`, `frontend/templates.py`) were removed during the v2
convergence and **do not exist**. The obsolete `frontend/components.py` is
*historically referenced* in `RELEASE_BASELINE.md` / `RELEASE_READINESS.md`
only, with explicit HISTORICAL RECORD labels added in G4.

**Theme model:** `frontend/core/design_tokens.py` `THEMES` dict — exactly 2
canonical themes (`dark`, `light`). `frontend/core/themes.py` documents that
"Custom themes from the old system are no longer supported." The G4 "5 themes
+ Custom Theme Editor" README claim was a stale v1 assertion and was corrected.

---

## 3. Runtime Evidence Tiers (G3)

From `backend/tests/semantic/SEMANTIC_EVIDENCE.md` — unchanged and accurate
as of this baseline:

| Tier | Meaning | Engines |
|------|---------|---------|
| A | Target SQL executed on the native target engine; result values asserted | PostgreSQL 17 (CI `semantic-runtime`), DuckDB (in-process) |
| B | Compatible-engine surrogate; not the exact target engine | MySQL / TSQL constructs rewritten and executed on DuckDB |
| C | Static only: sqlglot parse + transpile + AST-diff assertions, no execution | Oracle, Hive, Spark, Trino, Snowflake, Redshift, ClickHouse, Databricks |

**The 12×12 conversion matrix is a static transpile/parse matrix only.**
It does **not** imply 12×12 native runtime coverage. The native-runtime
boundary is exactly: PostgreSQL + DuckDB. This is stated explicitly in
`SEMANTIC_EVIDENCE.md` and must not be inverted in any release material.

### Fresh CI Evidence (G5)

| Field | Value |
|-------|-------|
| CI run | `35898644125` (github.com/zengxiangdi/sql-dialect-master/actions/runs/35898644125) |
| Branch / commit | `chore/g5-audit-closure` @ `89fab1c` |
| Trigger | push |
| `semantic-runtime` job | ✅ success |
| PostgreSQL 17 CI service | present (service container `postgres:17`) |

Per-suite pass counts (from run `35898644125`, `semantic-runtime` job):

| Suite | Result |
|-------|--------|
| `backend/tests/test_runtime_semantics.py` | 2 passed |
| `backend/tests/semantic/test_runtime_semantics.py` | 46 passed, 5 skipped |
| `backend/tests/semantic/test_duckdb_runtime.py` | 16 passed |
| `backend/tests/semantic/test_d3_date_runtime.py` | 31 passed |
| `backend/tests/semantic/test_postgres_runtime.py` | 24 passed |

The 5 skips in `test_runtime_semantics.py` are known-dialect-difference cases
(SEPARATOR/COLLECT_LIST/TOP/DATE_SUB syntax unexecutable in the target
engine) — correctly classified, not failures. The prior G3 run
(`35810602355`) is superseded by this one and must not be cited as current
evidence.

Local runs (2026-09-24, no PostgreSQL service):
- `backend/tests/` full: **1916 passed, 38 skipped**
- `backend/tests/frontend/`: **303 passed**
- `compileall backend frontend sdm_local_v2.py`: clean
- `ruff check backend/core backend/api --select E9,F --ignore F401`: pass
- `bandit -q -r backend -x backend/tests -s B104,B110,B608`: clean
- `scripts/verify_readme_consistency.py`: pass (version=1.1.0, dialects=12, themes=['dark','light'])

---

## 4. Consistency Status (G4)

`scripts/verify_readme_consistency.py` (G4-hardened) enforces:

- version / requires-python / 12-dialect claims against `pyproject.toml` + `config.py`
- absence of stale v1 theme claims ("5 themes", "Custom Theme Editor")
- absence of obsolete v1 frontend paths in the README project-structure block
- presence of `frontend/core/`, `frontend/pages/`, `frontend/ui/`, `app_context_v2.py`, `templates_v2.py`, `sdm_local_v2.py`
- 39 data types claim against `type_mapping.json` (source has 39 canonical types)
- 298 SQL functions claim against `functions_db.json`

All checks pass at this baseline. The G4 negative-probe checks (stale theme
reintroduction, v1 path reintroduction, wrong type count) were verified to
fire correctly at commit `89fab1c`.

---

## 5. Documentation Truth Model

| Document | Role | Status at this baseline |
|----------|------|-------------------------|
| `README.md` | Current-state reference | Verified against source (G4) |
| `CHANGELOG.md` | Historical release log | No changes in G5; `[1.1.0]` is the current entry; no new version invented |
| `RELEASE_BASELINE.md` | Historical v1.0.1 reference baseline | Labeled HISTORICAL RECORD (G4); not a post-v1.1.0 record |
| `RELEASE_READINESS.md` | Historical v1.0.1 release-readiness report | Labeled HISTORICAL RECORD (G4); not a post-v1.1.0 record |
| `POST_V1_1_0_AUDIT_BASELINE.md` (this file) | Post-v1.1.0 audit baseline record | Created in G5; explicitly not a release artifact |

---

## 6. Deferred Items — Adjudicated

| # | Item | Classification | Rationale |
|---|------|----------------|-----------|
| 1 | NL2SQL benchmark in CI | **Future engineering work** | No NL2SQL entry in `benchmark.yml` or `ci.yml`; adding one is a new feature deliverable, not a release blocker. Must not be silently converted into G5 scope. |
| 2 | Runtime metrics endpoint | **Future engineering work** | No metrics module exists anywhere in `backend/`; this is a new API surface, not a gap in existing behaviour. Not a release blocker. |
| 3 | Distributed tracing | **Future engineering work** | No tracing setup in the codebase. Deferred by design; not a release blocker. |
| 4 | Full-repo `ruff check .` (~559 style findings) | **Pre-existing technical debt** | Concentrated in `backend/core/*` (UP006/UP035/I001/EXE001). The `quality.yml` CI gate is intentionally scoped to `ruff check backend/core backend/api --select E9,F --ignore F401` — correctness only. The G3/G4 ruff closures deliberately did not broaden this. Pre-existing, not a G5 blocker. |
| 5 | `RELEASE_READINESS.md` §144–146 duplicated "Parameterized types" limitation | **Pre-existing documentation defect** | Items 1 and 2 in the Known-Limitations section are identical text, carried over from the v1.0.1 era. This is a cosmetic duplication inside a HISTORICAL RECORD document. It does not affect release readiness; it should not be "fixed" by editing the historical document. Recorded here as accepted, not fixed. |

**No release blockers found in G5.** No genuine blocker with a reproducer was
discovered; no stop-and-report condition was triggered.

---

## 7. G1/G2 Semantic Integrity (re-probed at this baseline)

| Check | Result |
|-------|--------|
| G1: unknown relationship fails closed (`users who have invoices` → `success=False`) | ✅ confirmed |
| G1: D3 calendar vs rolling preserved (`last month` → `INTERVAL '-1 month'`; `last 7 weeks` → `INTERVAL '49 days'`) | ✅ confirmed |
| G1: composed WHERE has no duplicate clause | ✅ confirmed |
| G2: `NVARCHAR(4001)` tsql→postgres → TSQL NVARCHAR limit warning fires | ✅ confirmed |
| G2: `NVARCHAR(4000)` → no limit warning (at boundary) | ✅ confirmed |
| G2: `NVARCHAR(100)` → no limit warning | ✅ confirmed |
| G2: `precision` field present in result | ✅ confirmed |
| G2: single warning owner (`get_precision_warnings`) | ✅ confirmed |

---

## 8. What Future Release Material Must Not Claim

- 12×12 native runtime coverage (only PostgreSQL + DuckDB have native Tier A
  runtime evidence in CI; all other dialects are Tier B or C).
- More than 2 themes (dark + light only; the "5 themes + Custom Theme Editor"
  claim is obsolete and was removed in G4).
- v1.0.1 release state as current (it is a historical record only).
- `frontend/components.py` or any v1 frontend path as current architecture.
- G1/G2/G3/G4/G5 as released features in any CHANGELOG entry — G5 is a
  closure phase, not a release.

---

## 9. Version / Tag / Dependency State

- `pyproject.toml` version: **1.1.0** (unchanged by G5)
- Git tags: `v1.0.1`, `v1.0.1-release`, `v1.1.0` (no new tags created by G5)
- Dependencies: no changes introduced by G5
- New release: **none** (release decision is separate and explicitly out of scope)

---

*This baseline is the reference record for the post-v1.1.0 engineering state.
It does not replace `RELEASE_BASELINE.md` (v1.0.1 historical) and does not
bump the version. G6 and any future release decision are explicitly out of
scope for G5.*
