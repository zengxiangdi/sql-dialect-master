# Frontend v2 Convergence Audit

**Date:** 2026-09-16
**Branch:** main
**Goal:** Make `sdm_local_v2.py` the sole canonical frontend; remove/compact dead v1 code.

---

## 1. Import Dependency Map

### v1 modules still imported by runtime code
```
sdm_local.py
  ├── frontend.app_context (load_data, convert, batch_convert, format_sql, _esc, get_dialect_label)
  ├── frontend.components  (render_history_card, render_main_header, render_sidebar_branding)
  ├── frontend.tabs.convert   (render_convert_tab)
  ├── frontend.tabs.explain   (render_explain_tab)
  ├── frontend.tabs.functions (render_functions_tab)
  ├── frontend.tabs.lineage   (render_lineage_tab)
  ├── frontend.tabs.nl2sql    (render_nl2sql_tab)
  ├── frontend.tabs.types     (render_types_tab)
  └── frontend.themes         (THEMES, export_theme_to_json, generate_keyboard_shortcuts_js,
                               generate_theme_css, import_theme_from_json)
```

**Critical finding:** `sdm_local.py` is the ONLY file importing any v1 module.

### v2 modules — zero v1 dependencies
```
sdm_local_v2.py
  ├── frontend.app_context_v2
  ├── frontend.core.design_tokens / themes / styles / navigation / viewmodels / escaping / state
  ├── frontend.pages.*
  └── frontend.ui.*
```

### Test dependencies
```
No test imports any v1 module.
```

### Documentation/CI dependencies
```
README.md:66      → streamlit run sdm_local.py
README.md:170     → docs entry point as sdm_local.py
.github/workflows/ci.yml:42  → compileall includes sdm_local.py
```

---

## 2. Duplicate Logic Inventory

| Concern | v1 Location | v2 Location | Status |
|---------|-------------|-------------|--------|
| SQL conversion | `app_context.py:convert()` | `app_context_v2.py:convert_sql()` | v1 unused by v2 |
| Batch conversion | `app_context.py:batch_convert()` | `app_context_v2.py:batch_convert_sql()` | v1 unused by v2 |
| Format SQL | `app_context.py:format_sql()` | `app_context_v2.py:format_sql_local()` | v1 unused by v2 |
| NL2SQL | `tabs/nl2sql.py` | `pages/nl2sql.py` | v1 unused by v2 |
| Convert tab | `tabs/convert.py` | `pages/convert.py` | v1 unused by v2 |
| Lineage tab | `tabs/lineage.py` | `pages/lineage.py` | v1 unused by v2 |
| Explain tab | `tabs/explain.py` | `pages/query_analysis.py` | v1 unused by v2 |
| Functions tab | `tabs/functions.py` | `pages/functions.py` | v1 unused by v2 |
| Types tab | `tabs/types.py` | `pages/types.py` | v1 unused by v2 |
| Themes (5+custom) | `themes.py` | `core/design_tokens.py` + `core/themes.py` | v1 unused by v2 |
| Components | `components.py` | scattered in `ui/` and `pages/` | v1 unused by v2 |
| Templates | `templates.py` (emoji-heavy) | `templates_v2.py` (clean) | both exist |
| State | flat `st.session_state` | `core/state.py` | v1 unused by v2 |
| Navigation | none | `core/navigation.py` | v1 has none |
| ViewModels | none | `core/viewmodels.py` | v1 has none |

---

## 3. Session State Key Audit

### v2 keys (active, in `sdm_local_v2.py` defaults)
```
sdm_theme, sdm_history, sdm_favorites
convert_last_vm, batch_last_vm, nl_last_vm, lineage_last_vm
qa_last_result, diff_last_vm
sdm_navigation_intent, sdm_selected_finding_index
diff_src_sql, diff_tgt_sql, diff_src_dialect, diff_tgt_dialect
convert_src_sql, convert_src, convert_target_sql
nl_input_text, nl_dialect, nl_table_hint, nl_last_vm, nl_generation_error
lineage_sql, lineage_dialect, lineage_last_vm
qa_sql, qa_dialect, qa_last_result
```

### v1 keys (only in `sdm_local.py`)
```
theme, dark_mode, history, favorites, load_sql, last_conversion
custom_theme, show_welcome
src, tgt, in, last_sql, formatted_src, batch_sql, batch_src, batch_tgt
tpl, nl_ex, nl, nld, nl_table
exp_sql, exp_d1, exp_d2
lin_dialect, lin_sql
fsearch, fcat, type_src, type_tgt, type_cat, tsel
```

**Zero overlap.** No v2 page reads a v1 key.

---

## 4. unsafe_allow_html=True Inventory

### v2 sites (all with proper escaping)
All v2 `unsafe_allow_html=True` calls use `esc()` on every user/backend-controlled value.
This is acceptable per the security model (F7 principle: controlled boundary, not zero).

### v1 sites (mix of safe and unsafe)
- `sdm_local.py:75,79` — theme CSS + JS (trusted, generated from theme data)
- `sdm_local.py:88` — sidebar branding (static HTML, no user data)
- `sdm_local.py:145` — **UNSAFE**: `render_history_card(h, current_theme)` with unescaped SQL preview
- `sdm_local.py:196` — header HTML (static, safe)
- `sdm_local.py:242` — footer HTML (static, safe)
- `tabs/*` — various unsafe sites (only reachable via `sdm_local.py`)

---

## 5. Convergence Plan

### Step 1: Update documentation and CI
- `README.md`: change `streamlit run sdm_local.py` → `sdm_local_v2.py`
- `.github/workflows/ci.yml`: add `sdm_local_v2.py` to compileall
- Do NOT delete `sdm_local.py` yet

### Step 2: Remove unused v1 files (no runtime dependents)
Safe to delete after step 1:
- `frontend/tabs/` (6 files) — only imported by `sdm_local.py`
- `frontend/themes.py` — only imported by `sdm_local.py`
- `frontend/components.py` — only imported by `sdm_local.py`
- `frontend/app_context.py` — only imported by `sdm_local.py` and `frontend/tabs/*`
- `frontend/templates.py` — superseded by `frontend/templates_v2.py`

### Step 3: Update `frontend/__init__.py`
Remove v1 exports, keep minimal or remove entirely.

### Step 4: Rename `sdm_local_v2.py` → `sdm_local.py`
The v2 implementation becomes the canonical entry point.

### Step 5: Final verification
- `pytest` passes
- `ruff` clean
- `compileall` passes
- Smoke test complete

---

## 6. Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| `sdm_local_v2.py` has missing feature vs `sdm_local.py` | Low | Audit shows v2 covers all features |
| CI breaks on rename | Low | Update both paths in CI |
| Users following README | Medium | Must update README before rename |
| `templates.py` still referenced | Low | Verified: only v1 uses it |
| Old session state leaked across restarts | None | v1/v2 keys are disjoint |

---

## 7. Decision Matrix

| File | Delete? | Reason |
|------|---------|--------|
| `frontend/tabs/*.py` | ✅ Delete | Only imported by `sdm_local.py` |
| `frontend/themes.py` | ✅ Delete | Only imported by `sdm_local.py` |
| `frontend/components.py` | ✅ Delete | Only imported by `sdm_local.py` |
| `frontend/app_context.py` | ✅ Delete | Only imported by `sdm_local.py` + `tabs/*` |
| `frontend/templates.py` | ✅ Delete | Superseded by `templates_v2.py`, only used by v1 |
| `sdm_local.py` | ✅ Delete | Replaced by `sdm_local_v2.py` |
| `sdm_local_v2.py` | ✅ Keep | Canonical entry point |
| `frontend/__init__.py` | ⚠️ Rewrite | Remove v1 exports |
| `README.md` | ⚠️ Update | Point to v2 |
| `.github/workflows/ci.yml` | ⚠️ Update | Compile v2 |
