# Frontend v2 Architecture Audit

**Date:** 2026-09-15
**Scope:** `frontend/` + `sdm_local.py` + backend contracts consumed by frontend
**Status:** Phase F0 — Audit Complete

---

## 1. Current Architecture

### File Map (2002 lines total)

| File | Lines | Role | Risk |
|------|-------|------|------|
| `sdm_local.py` | 243 | App entry point | P0: XSS via `unsafe_allow_html=True` on branding/header |
| `frontend/app_context.py` | 159 | Services: `convert()`, `batch_convert()`, `_esc()` | P0: incomplete `_esc()` (no `'` escaping) |
| `frontend/themes.py` | 227 | Theme definitions + CSS generator | P1: custom theme JSON uncontrolled CSS injection path |
| `frontend/components.py` | 227 | Shared render helpers (broken merge artifact at line 222) | P0: `render_history_card` unescaped SQL preview |
| `frontend/templates.py` | 117 | SQL templates, emoji-heavy | Low |
| `frontend/tabs/convert.py` | 314 | Conversion tab | P0: batch split bug at line 291 |
| `frontend/tabs/functions.py` | 92 | Function encyclopedia | P1: `unsafe_allow_html=True` with theme values |
| `frontend/tabs/types.py` | 98 | Type mapping matrix | P1: `unsafe_allow_html=True` |
| `frontend/tabs/explain.py` | 125 | Simulated plan comparison | P1: `unsafe_allow_html=True` |
| `frontend/tabs/lineage.py` | 139 | Mermaid lineage diagram | P1: Mermaid injection with unescaped user data |
| `frontend/tabs/nl2sql.py` | 123 | NL2SQL generation | Low (no HTML injection) |

### Existing IA (6 flat tabs)

```
⚡ Convert | 📚 Functions | 🗂️ Types | 💬 NL2SQL | 📊 Explain | 🔗 Lineage
```

### Existing State Model

```python
st.session_state = {
    "theme": "🌊 Ocean",
    "dark_mode": True,
    "history": [],       # List[dict] with sql/src/tgt/result
    "favorites": [],     # Same shape as history
    "load_sql": None,    # Cross-tab transfer key
    "last_conversion": None,  # Raw dict: {"ok": bool, "sql": str, "notes": [...]}
    "custom_theme": None,
    "show_welcome": True,
    # Per-tab ephemeral state (no namespacing):
    "src", "tgt", "in", "last_sql", "formatted_src",
    "batch_sql", "batch_src", "batch_tgt",
    "tpl", "nl_ex", "nl", "nld", "nl_table",
    "exp_sql", "exp_d1", "exp_d2",
    "lin_dialect", "lin_sql",
    "fsearch", "fcat", "type_src", "type_tgt", "type_cat", "tsel",
}
```

---

## 2. Security Findings

### P0 — HTML Injection / XSS Boundaries

| Location | Risk | Severity |
|----------|------|----------|
| `components.py:58` `render_history_card` | `sql_preview` from `history_item['sql']` is NOT escaped before f-string injection into HTML | **P0** |
| `sdm_local.py:88` `render_sidebar_branding` | No user data, but sets precedent for `unsafe_allow_html=True` | P2 |
| `sdm_local.py:196` `render_main_header` | No user data | P2 |
| `sdm_local.py:237-242` footer HTML | Static content, no user data | P2 |
| `themes.py:140` `generate_theme_css` | **Custom theme JSON import path**: users can paste arbitrary CSS | **P1** |
| `tabs/lineage.py:72-97` Mermaid generation | Table/column names from parsed SQL injected into Mermaid without escaping; `<script>` inside SQL would appear as text in Mermaid node labels but Mermaid parser may misinterpret certain strings | **P1** |
| `tabs/convert.py:91-97` arrow HTML | Uses `current_theme['accent']` only (controlled), safe | P3 |
| `tabs/functions.py:83-88` | Dialect name + syntax from JSON (trusted), theme values controlled | P2 |
| `tabs/explain.py:83-117` | Uses `_esc()` properly | Low |
| `tabs/types.py:91-98` | Uses `_esc()` properly | Low |
| `components.py:26-30` `render_dialect_chip` | Dialect name from controlled set, theme values controlled | P2 |

### P0 — `_esc()` is Incomplete

Current implementation in `app_context.py:145-153`:

```python
def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
```

Missing: single quote `\'` escaping for HTML attribute contexts. Should use `markupsafe.escape()` or equivalent.

### P0 — Batch Split Bug (semantic error, not security)

`tabs/convert.py:291`:
```python
statement_lines = [s.strip() for s in batch_sql.split("\n") if s.strip()]
```

This splits on newline, not on semicolon. Semicolons inside string literals (`SELECT ';' AS value`) would break this logic incorrectly, and comments containing semicolons (`-- comment ;`) are also split wrong.

Fix: use canonical `SQLTranspiler.batch_transpile()` with a proper statement splitter, or accept the batch input as already-split statements from the user (one per line) and delegate splitting to the backend layer.

### P1 — Mermaid Injection in Lineage

`tabs/lineage.py:75-86`:
```python
mermaid += f"        {t['name']}[(\"{t['name']}\")]\n"
...
mermaid += f"        {safe_name}[\"{oc}\"]\n"
```

If a table name contains `"` or `\` or `]`, it can break the Mermaid syntax. Table names from `sqlglot.parse_one()` are AST nodes — they come from user SQL but after parsing, the `.name` attribute is a plain Python string. However, user-controlled SQL like `FROM "x"]["y"` could produce a table name with quotes.

Safe approach: sanitize Mermaid node labels and identifiers.

---

## 3. UX Findings

### Visual Debt
- **5 themes** (Dark, Light, Ocean, Sakura, Forest) — specification requires 2
- **57+ emoji** across UI labels, templates, function categories, dialect chips
- **Gradient-heavy header** with card hover lift animations
- **Dashboard aesthetic**: large rounded cards, box shadows, animated elements
- All HTML rendered via f-string with inline styles (no CSS class system)

### Structural Issues
- No sidebar navigation hierarchy — flat tabs
- No Inspector panel (spec requirement)
- No Command Palette (spec requirement)
- No separation between Workspace/Library/System sections
- History is inline in sidebar (full history not paginated/searchable)
- Convert result is a single `st.code()` block + `st.success()` — no structured status panel

### State Coupling
- `st.session_state` keys are not namespaced per workspace
- `last_conversion` dict shape (`{"ok", "sql", "notes"}`) differs from `TranspileResult` dataclass shape
- History entries store original dict, not structured data

---

## 4. Coupling & Debt

### Tight Couplings
1. `components.py` functions depend on `theme: Dict[str, str]` with magic keys (`bg`, `fg`, `accent`, `secondary`, `card`)
2. `themes.py` generates CSS with hardcoded Streamlit selectors (`.stApp`, `.stButton>button`, etc.)
3. `app_context.py` returns raw dicts from `convert()` — no ViewModel layer
4. `templates.py` contains both SQL templates AND emoji category mappings (dual purpose)

### Dead / Unused Code
- `render_conversion_arrow()` in `components.py:132-145` — never called
- `render_lineage_result()` in `components.py:183-226` — never called (lineage renders inline in `lineage.py`)
- `render_dialect_grid_item()` in `components.py:148-180` — never called
- `CATEGORY_EMOJI` in `templates.py:73-85` — duplicated from `functions.py`

### Merge Artifact
- `components.py:222-223`:
  ```python
      mermaid += f"        {safe_name}[\"{oc}\"]\n"
      mermaid += "    end\n\n"
  ```
  Wait — actually line 222 reads:
  ```
  222:         safe_name = str(oc).replace(' ', '_').replace('-', '_')
  223:         mermaid += f"        {safe_name}[\"{oc}\"]\n"
  ```
  But the file ends abruptly at line 226. Let me re-read... the file appears to have a stray fragment at lines 222-223 where two lines from a different context are present but it still imports correctly. Actually, looking again:

  Lines 220-226:
  ```python
      for oc in output_cols[:6]:
          safe_name = str(oc).replace(' ', '_').replace('-', '_')
          mermaid += f"    RESULT --> {safe_name}\n"
      
      mermaid += "```"
      return mermaid
  ```
  This is fine — the earlier read was just showing the end of the file.

---

## 5. Backend Contracts Consumed by Frontend

### `TranspileResult` (dataclass)
```python
success: bool
source_sql: str
target_sql: Optional[str]
source_dialect: str
target_dialect: str
error: Optional[str]
error_code: Optional[str]
compatibility_notes: List[str]
transformations: List[str]
warnings: List[str]
```

### `SemanticDiff` (dataclass)
```python
equivalent: bool
source_normalized: Optional[str]
target_normalized: Optional[str]
differences: List[str]
parse_error: Optional[str]
status: str  # "equivalent" | "different" | "unknown" | "parse_error"
difference_categories: List[str]
structured_differences: List[StructuredSemanticDifference]
semantic_classification: str  # "equivalent" | "structurally_equivalent" | "potentially_different" | "definitely_different"
confidence: float
evidence: Optional[str]
```

### `StructuredSemanticDifference` (frozen dataclass)
```python
category: str
severity: str  # "error" | "warning"
source_fragment: str
target_fragment: str
explanation: str
confidence: float
evidence: Optional[str]
```

### `NL2SQLResult` (dataclass)
```python
success: bool
input_text: str
sql: Optional[str]
dialect: str
explanation: str
confidence: float
suggestions: list
parsed_elements: dict
```

### `convert()` return contract (app_context.py)
```python
{"ok": bool, "sql": Optional[str], "notes": List[str], "err": Optional[str]}
```

### `batch_convert()` return contract
```python
List[{"ok": bool, "sql": Optional[str], "notes": List[str], "err": Optional[str]}]
```

---

## 6. Migration Strategy

### Phase F0 — Audit ✅ (this document)

### Phase F1 — Design System
1. Create `frontend/core/design_tokens.py` — color tokens (Dark/Light palettes)
2. Create `frontend/core/themes.py` — replace old themes.py with 2-theme system
3. Create `frontend/core/styles.py` — centralized CSS generation using tokens
4. Deprecate old `frontend/themes.py` → migrate references, remove in F3

### Phase F2 — Application Shell
1. Create `frontend/core/state.py` — typed state model
2. Create `frontend/ui/navigation.py` — sidebar navigation (Workspace/Library/System)
3. Create `frontend/ui/shell.py` — layout with sidebar + main + inspector placeholders
4. Refactor `sdm_local.py` to use new shell
5. Keep all 6 existing tabs functional under new IA

### Phase F3 — Convert Workspace (P0 bug fix included)
1. Create `frontend/core/viewmodels.py` — `ConversionViewModel`
2. Create `frontend/ui/editor.py` — SQL editor wrapper (good text_area with monospace)
3. Create `frontend/ui/status.py` — conversion status panel (AST / Semantic / Runtime)
4. Create `frontend/ui/diff.py` — semantic diff view using `SemanticDiff` dataclass
5. Refactor `tabs/convert.py` — fix batch split bug, use ViewModel, use new status panel
6. Fix batch split: accept raw user text, delegate to canonical `batch_transpile()` with proper splitting

### Phase F4 — Semantic Diff
1. Create `frontend/pages/diff.py` — standalone diff workspace
2. Reuse `frontend/ui/diff.py` component
3. Connect to existing `diff_sql_ast()` from backend

### Phase F5 — NL2SQL
1. Refactor `tabs/nl2sql.py` — new ViewModel, cleaner result display
2. Show confidence as overall only (no breakdown fabrication)

### Phase F6 — Lineage / Query Analysis / Runtime
1. Refactor `tabs/lineage.py` — escape Mermaid labels, safer node names
2. Rename "Explain" → "Query Analysis" in navigation
3. Create `frontend/pages/runtime.py` stub (Not available placeholder)

### Phase F7 — Security / Regression / Cleanup
1. Replace all `_esc()` with `markupsafe.escape()` or equivalent
2. Audit all `unsafe_allow_html=True` calls
3. Add frontend test suite
4. Clean up dead code from `components.py`
5. Remove old emoji-heavy templates/categories from `templates.py`
6. Run full test suite

---

## 7. Critical File Changes Map

| New File | Purpose |
|----------|---------|
| `frontend/core/__init__.py` | Public exports |
| `frontend/core/design_tokens.py` | Dark/Light color tokens |
| `frontend/core/themes.py` | Theme management (2 themes only) |
| `frontend/core/styles.py` | CSS generation from tokens |
| `frontend/core/state.py` | Typed session state model |
| `frontend/core/viewmodels.py` | Backend→Frontend adapters |
| `frontend/ui/shell.py` | App shell layout |
| `frontend/ui/navigation.py` | Sidebar navigation |
| `frontend/ui/editor.py` | SQL editor component |
| `frontend/ui/status.py` | Status/result panel |
| `frontend/ui/diff.py` | Semantic diff component |
| `frontend/ui/inspector.py` | Right-side inspector panel |
| `frontend/ui/command_palette.py` | ⌘K palette |
| `frontend/pages/convert.py` | New convert workspace |
| `frontend/pages/nl2sql.py` | New NL2SQL workspace |
| `frontend/pages/diff.py` | Semantic diff workspace |
| `frontend/pages/lineage.py` | New lineage workspace |
| `frontend/pages/functions.py` | Function library (table view) |
| `frontend/pages/types.py` | Type mapping (refined) |
| `frontend/pages/history.py` | Full history page |
| `frontend/pages/settings.py` | Settings page |
| `backend/tests/frontend/test_frontend_security.py` | XSS test coverage |
| `backend/tests/frontend/test_frontend_batch.py` | Batch splitting test |
| `backend/tests/frontend/test_frontend_state.py` | State isolation test |
| `backend/tests/frontend/test_frontend_viewmodels.py` | ViewModel contract test |

---

## 8. Remaining Risks (Post-Audit)

1. **Streamlit version lock**: `streamlit==1.63.0` is frozen in lock file. Any feature using newer Streamlit APIs must check compatibility.
2. **No Monaco available**: Task says "if you cannot reasonably introduce Monaco, don't force it." We will build a solid `st.text_area` abstraction with monospace styling and leave hook for future Monaco swap.
3. **Mermaid in Streamlit**: Streamlit has built-in Mermaid support (`st.markdown` with ` ```mermaid ` fence). No external dependency needed.
4. **Session state persistence**: With restructured state model, need to ensure `st.rerun()` doesn't lose critical state between workspace switches.
5. **Old `components.py` dead code**: Should be cleaned up in F7, not during active implementation phases.

---

## 9. Go/No-Go for F1

- Backend test suite: **1143 passed** ✅
- Current frontend imports: **all pass** ✅
- No blocking blockers for design system work ✅
- Lock file validated: streamlit==1.63.0 compatible with expected APIs ✅

**Proceed to Phase F1.**
