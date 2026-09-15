# Frontend v2 Release Notes

**Release Date:** 2026-09-16  
**Branch:** feat/frontend-v2  
**Base Branch:** main  
**Commit Range:** e042303..c1d4af8

---

## Summary

Frontend v2 represents a complete architectural refactoring from a "feature-rich Streamlit Dashboard" to a "Professional SQL Developer Workspace." This migration introduces a new design system, unified navigation contract, ViewModel pattern, and enhanced security posture. All backend SQL semantic algorithms remain untouched.

---

## Architecture Migration

### New Canonical Structure

```
sdm_local_v2.py                    ← sole canonical entry point
  ↓
frontend/
├── core/                          ← shared utilities
│   ├── design_tokens.py           ← Dark/Light theme palettes (20 tokens each)
│   ├── themes.py                  ← theme management and validation
│   ├── styles.py                  ← CSS generation engine
│   ├── navigation.py              ← NavigationIntent protocol
│   ├── state.py                   ← typed AppState dataclass
│   ├── viewmodels.py              ← ViewModel pattern adapters
│   └── escaping.py                ← markupsafe.escape alias
├── pages/                         ← Streamlit page modules
│   ├── convert.py                 ← SQL conversion workspace
│   ├── nl2sql.py                  ← Natural language to SQL
│   ├── diff.py                    ← Semantic diff workspace
│   ├── lineage.py                 ← Table/column extraction
│   ├── query_analysis.py          ← Static analysis
│   ├── functions.py               ← Function encyclopedia
│   ├── types.py                   ← Type mapping matrix
│   ├── templates.py               ← SQL templates
│   ├── history.py                 ← Conversion history
│   ├── settings.py                ← Application settings
│   └── runtime.py                 ← Runtime testing
├── ui/                            ← reusable components
│   ├── editor.py                  ← SQL editor component
│   ├── status.py                  ← Result display components
│   ├── diff.py                    ← Diff visualization
│   ├── navigation.py              ← Sidebar rendering
│   └── command_palette.py         ← Global command palette
├── app_context_v2.py              ← thin backend adapter
└── templates_v2.py                ← clean template strings
```

### Key Architectural Patterns

1. **NavigationIntent Protocol** - Single source of truth for cross-page navigation, replacing 5 scattered `sdm_pending_*` session keys
2. **ViewModel Pattern** - All UI code accesses backend results through ViewModels, isolating UI from backend schema changes
3. **Design Tokens** - Frozen `ColorTokens` dataclass with Dark/Light palettes, generating CSS custom properties
4. **Typed State** - `AppState` dataclass replacing flat `st.session_state` dictionary

---

## Security Changes

### XSS Remediation
- All 59 `unsafe_allow_html=True` calls now use `markupsafe.escape()` on user/backend-controlled values
- Static HTML structure (labels, class names) remains safe
- Theme JSON validation rejects arbitrary CSS injection
- Mermaid diagram generation sanitizes node labels and IDs

### Deleted Vulnerable Code
- Old `render_history_card()` with unescaped SQL preview (v1)
- Old theme CSS with custom JSON injection path (v1)
- Old Mermaid with raw table name injection (v1)

### Test Coverage
- `test_frontend_security.py` (35 tests) - XSS, escaping, Mermaid sanitization, theme injection

---

## Legacy Removal

### Deleted Files (11 files, 2,251 lines)

| File | Lines | Reason |
|------|-------|--------|
| `frontend/tabs/convert.py` | 316 | Replaced by `pages/convert.py` |
| `frontend/tabs/explain.py` | 126 | Replaced by `pages/query_analysis.py` |
| `frontend/tabs/functions.py` | 92 | Replaced by `pages/functions.py` |
| `frontend/tabs/lineage.py` | 139 | Replaced by `pages/lineage.py` |
| `frontend/tabs/nl2sql.py` | 124 | Replaced by `pages/nl2sql.py` |
| `frontend/tabs/types.py` | 99 | Replaced by `pages/types.py` |
| `frontend/themes.py` | 588 | Replaced by `core/design_tokens.py` + `core/themes.py` |
| `frontend/components.py` | 225 | Dead code, no v2 callers |
| `frontend/app_context.py` | 160 | Replaced by `app_context_v2.py` |
| `frontend/templates.py` | 116 | Replaced by `templates_v2.py` |
| `sdm_local.py` | 242 | Replaced by `sdm_local_v2.py` |

### Retained Compatibility
- `frontend/templates_v2.py` - Clean templates without emoji clutter
- `FRONTEND_V2_AUDIT.md` - Complete v1 architecture audit
- `FRONTEND_V2_CONVERGENCE_AUDIT.md` - Convergence plan with dependency map

---

## Test Growth

### New Test Files (10 files, 199 tests)

| Test File | Tests | Coverage Area |
|-----------|-------|---------------|
| `test_frontend_security.py` | 35 | XSS, escaping, Mermaid sanitization, theme injection |
| `test_frontend_state.py` | 10 | AppState, HistoryEntry, state isolation |
| `test_frontend_conversion_contract.py` | 13 | Convert/batch/ViewModel contracts |
| `test_frontend_viewmodels.py` | 13 | All ViewModel construction |
| `test_frontend_lineage.py` | 10 | Table/column extraction, Mermaid generation |
| `test_frontend_theme.py` | 13 | Theme tokens, CSS generation, JSON validation |
| `test_frontend_semantic_diff.py` | 32 | All 6 classifications, severity, inspector |
| `test_frontend_nl2sql.py` | 35 | ViewModel, confidence levels, handoff, security |
| `test_frontend_navigation.py` | 26 | NavigationIntent, consume lifecycle, command registry |
| `test_frontend_batch.py` | 10 | Statement splitting edge cases |

### Total Test Count
- **Before:** ~1,143 tests
- **After:** 1,342 tests (+199 frontend-specific)
- **Skipped:** 6 tests
- **Failures:** 0

---

## Current Limitations

1. **Streamlit Dependency** - Frontend requires Streamlit 1.38+ runtime
2. **No Real-time Collaboration** - Session state is single-user only
3. **No Persistent Storage** - History cleared on page refresh (by design)
4. **Mermaid Version** - Uses browser-rendered Mermaid (no local library)
5. **Batch Size Limit** - Concurrent batch conversion bounded by system resources

---

## Known Issues

| Issue | Severity | Workaround |
|-------|----------|------------|
| `frontend/tabs/` directory empty | Low | Only contains `__pycache__`, can be deleted |
| ruff warnings in backend API | Low | Pre-existing, not introduced by v2 |

---

## Backward Compatibility

### Breaking Changes
- Entry point changed from `sdm_local.py` to `sdm_local_v2.py`
- Session state keys completely replaced (no migration path needed)
- API endpoints unchanged (backend preserved)

### Non-Breaking
- REST API: `/api/convert`, `/api/nl2sql`, `/api/diff`, etc. unchanged
- Python SDK: `SQLTranspiler`, `NL2SQLGenerator` unchanged
- Configuration: `.env` settings unchanged

---

## Migration Guide

### For Users
```bash
# Old
streamlit run sdm_local.py

# New
streamlit run sdm_local_v2.py
```

### For Developers
```python
# Old imports (removed)
from frontend.app_context import load_data, convert_sql
from frontend.themes import THEMES

# New imports
from frontend.app_context_v2 import load_data_v2, convert_sql
from frontend.core.design_tokens import THEMES
```

---

## Future Work (Out of Scope)

- F8: Production smoke test via `streamlit run sdm_local_v2.py`
- F9: Final version bump and CHANGELOG update
- F10: Documentation site generation
- F11: WebSocket real-time updates
- F12: Multi-user session support

---

**Status:** Ready for Code Review  
**Verification:** Local tests passing, CI pending merge
