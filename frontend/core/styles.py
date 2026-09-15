"""Centralized CSS generation for SQL Dialect Master v2.

Generates a complete stylesheet using CSS custom properties derived from
design tokens. All UI components consume these variables — no inline
style hex values leak into templates.
"""
from __future__ import annotations

from .design_tokens import ColorTokens


def generate_css(tokens: ColorTokens) -> str:
    """Generate the full application stylesheet.

    Args:
        tokens: ColorTokens from the active theme

    Returns:
        CSS string for injection via st.markdown(..., unsafe_allow_html=True)
    """
    return f"""
<style>
/* ── Theme Variables ─────────────────────────────────────────────── */
:root {{
  --sdm-bg:             {tokens.bg};
  --sdm-surface:        {tokens.surface};
  --sdm-surface-elev:   {tokens.surface_elevated};
  --sdm-border:         {tokens.border};
  --sdm-border-subtle:  {tokens.border_subtle};
  --sdm-text-primary:   {tokens.text_primary};
  --sdm-text-secondary: {tokens.text_secondary};
  --sdm-text-muted:     {tokens.text_muted};
  --sdm-text-accent:    {tokens.text_on_accent};
  --sdm-accent:         {tokens.accent};
  --sdm-success:        {tokens.success};
  --sdm-warning:        {tokens.warning};
  --sdm-danger:         {tokens.danger};
  --sdm-info:           {tokens.info};
  --sdm-input-bg:       {tokens.input_bg};
  --sdm-input-border:   {tokens.input_border};
  --sdm-input-focus:    {tokens.input_border_focus};
  --sdm-hover:          {tokens.hover_bg};
  --sdm-selected:       {tokens.selected_bg};
  --sdm-font-ui:        'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --sdm-font-mono:      'JetBrains Mono', 'SFMono-Regular', Menlo, Monaco, Consolas, monospace;
  --sdm-radius-sm:      4px;
  --sdm-radius-md:      6px;
  --sdm-radius-lg:      8px;
}}

/* ── Reset & Base ─────────────────────────────────────────────────── */
html, body {{
  font-family: var(--sdm-font-ui);
  color: var(--sdm-text-primary);
  background: var(--sdm-bg);
  font-size: 14px;
  line-height: 1.5;
}}

/* ── App Shell ────────────────────────────────────────────────────── */
.sdm-app {{
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}}

.sdm-topbar {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 48px;
  background: var(--sdm-surface);
  border-bottom: 1px solid var(--sdm-border);
  position: sticky;
  top: 0;
  z-index: 100;
}}

.sdm-topbar-title {{
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--sdm-text-muted);
  margin: 0;
}}

.sdm-topbar-version {{
  font-size: 11px;
  color: var(--sdm-text-muted);
  font-family: var(--sdm-font-mono);
}}

/* ── Sidebar ──────────────────────────────────────────────────────── */
.sdm-sidebar {{
  width: 220px;
  min-width: 220px;
  background: var(--sdm-surface);
  border-right: 1px solid var(--sdm-border);
  display: flex;
  flex-direction: column;
  padding: 16px 0;
  overflow-y: auto;
}}

.sdm-nav-group {{
  margin-bottom: 20px;
}}

.sdm-nav-group-label {{
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--sdm-text-muted);
  padding: 0 16px;
  margin-bottom: 4px;
}}

.sdm-nav-item {{
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 16px;
  font-size: 13px;
  font-weight: 500;
  color: var(--sdm-text-secondary);
  cursor: pointer;
  border-left: 2px solid transparent;
  text-decoration: none;
  transition: color 0.15s, border-color 0.15s, background 0.15s;
}}

.sdm-nav-item:hover {{
  color: var(--sdm-text-primary);
  background: var(--sdm-hover);
}}

.sdm-nav-item.active {{
  color: var(--sdm-accent);
  border-left-color: var(--sdm-accent);
  background: var(--sdm-selected);
}}

.sdm-nav-icon {{
  font-size: 14px;
  width: 18px;
  text-align: center;
  flex-shrink: 0;
}}

/* ── Main Workspace ───────────────────────────────────────────────── */
.sdm-main {{
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}}

.sdm-workspace {{
  display: flex;
  flex: 1;
  overflow: hidden;
}}

.sdm-content {{
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  background: var(--sdm-bg);
}}

.sdm-inspector {{
  width: 320px;
  min-width: 320px;
  background: var(--sdm-surface);
  border-left: 1px solid var(--sdm-border);
  overflow-y: auto;
  padding: 20px;
  display: none;
}}

.sdm-inspector.visible {{
  display: block;
}}

/* ── Editor ───────────────────────────────────────────────────────── */
.sdm-editor-wrap {{
  border: 1px solid var(--sdm-border);
  border-radius: var(--sdm-radius-md);
  overflow: hidden;
  background: var(--sdm-input-bg);
}}

.sdm-editor-wrap:focus-within {{
  border-color: var(--sdm-input-focus);
  box-shadow: 0 0 0 3px {tokens.accent}20;
}}

.sdm-editor-label {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  background: var(--sdm-surface-elev);
  border-bottom: 1px solid var(--sdm-border);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--sdm-text-muted);
}}

.sdm-editor-label-dialect {{
  font-family: var(--sdm-font-mono);
  color: var(--sdm-accent);
  font-size: 11px;
}}

.sdm-editor {{
  width: 100%;
  min-height: 240px;
  resize: vertical;
  border: none;
  outline: none;
  background: transparent;
  color: var(--sdm-text-primary);
  font-family: var(--sdm-font-mono);
  font-size: 13px;
  line-height: 1.6;
  padding: 12px;
  tab-size: 4;
  white-space: pre;
  overflow: auto;
}}

.sdm-editor::placeholder {{
  color: var(--sdm-text-muted);
}}

/* ── Toolbar ──────────────────────────────────────────────────────── */
.sdm-toolbar {{
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 0;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--sdm-border-subtle);
}}

.sdm-btn {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 500;
  font-family: var(--sdm-font-ui);
  border: 1px solid var(--sdm-border);
  border-radius: var(--sdm-radius-sm);
  background: var(--sdm-surface);
  color: var(--sdm-text-secondary);
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}}

.sdm-btn:hover {{
  background: var(--sdm-hover);
  color: var(--sdm-text-primary);
  border-color: var(--sdm-text-muted);
}}

.sdm-btn-primary {{
  background: var(--sdm-accent);
  border-color: var(--sdm-accent);
  color: var(--sdm-text-accent);
}}

.sdm-btn-primary:hover {{
  filter: brightness(1.1);
  background: var(--sdm-accent);
  color: var(--sdm-text-accent);
}}

.sdm-btn-sm {{
  padding: 4px 8px;
  font-size: 11px;
}}

.sdm-separator {{
  width: 1px;
  height: 20px;
  background: var(--sdm-border);
  margin: 0 4px;
}}

/* ── Panels (source / target) ─────────────────────────────────────── */
.sdm-panels {{
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 0;
  align-items: stretch;
}}

.sdm-panel {{
  display: flex;
  flex-direction: column;
  border: 1px solid var(--sdm-border);
  border-radius: var(--sdm-radius-md);
  overflow: hidden;
  background: var(--sdm-surface);
}}

.sdm-panel + .sdm-panel {{
  margin-left: 0;
}}

.sdm-panel-divider {{
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 12px;
  color: var(--sdm-text-muted);
  font-size: 18px;
  flex-shrink: 0;
}}

/* ── Status badges ────────────────────────────────────────────────── */
.sdm-badge {{
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  border-radius: var(--sdm-radius-sm);
  border: 1px solid transparent;
}}

.sdm-badge-success {{
  background: {tokens.success}15;
  color: var(--sdm-success);
  border-color: {tokens.success}40;
}}

.sdm-badge-warning {{
  background: {tokens.warning}15;
  color: var(--sdm-warning);
  border-color: {tokens.warning}40;
}}

.sdm-badge-error {{
  background: {tokens.danger}15;
  color: var(--sdm-danger);
  border-color: {tokens.danger}40;
}}

.sdm-badge-info {{
  background: {tokens.info}15;
  color: var(--sdm-info);
  border-color: {tokens.info}40;
}}

.sdm-badge-neutral {{
  background: var(--sdm-hover);
  color: var(--sdm-text-muted);
  border-color: var(--sdm-border);
}}

/* ── Result card ──────────────────────────────────────────────────── */
.sdm-result-card {{
  background: var(--sdm-surface);
  border: 1px solid var(--sdm-border);
  border-radius: var(--sdm-radius-lg);
  overflow: hidden;
  margin-bottom: 16px;
}}

.sdm-result-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--sdm-border);
  background: var(--sdm-surface-elev);
}}

.sdm-result-header-title {{
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--sdm-text-muted);
}}

.sdm-result-body {{
  padding: 14px;
}}

/* ── Status matrix ────────────────────────────────────────────────── */
.sdm-status-grid {{
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
  margin-bottom: 14px;
}}

.sdm-status-item {{
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: var(--sdm-input-bg);
  border: 1px solid var(--sdm-border);
  border-radius: var(--sdm-radius-md);
}}

.sdm-status-dot {{
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}}

.sdm-status-dot.green  {{ background: var(--sdm-success); }}
.sdm-status-dot.yellow {{ background: var(--sdm-warning); }}
.sdm-status-dot.red    {{ background: var(--sdm-danger); }}
.sdm-status-dot.gray   {{ background: var(--sdm-text-muted); }}

.sdm-status-label {{
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--sdm-text-muted);
}}

.sdm-status-value {{
  font-size: 12px;
  font-weight: 500;
  color: var(--sdm-text-primary);
}}

/* ── Inspector ────────────────────────────────────────────────────── */
.sdm-inspector-section {{
  margin-bottom: 20px;
}}

.sdm-inspector-title {{
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--sdm-text-muted);
  margin-bottom: 8px;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--sdm-border-subtle);
}}

.sdm-inspector-row {{
  display: flex;
  justify-content: space-between;
  padding: 5px 0;
  font-size: 12px;
}}

.sdm-inspector-key {{
  color: var(--sdm-text-muted);
}}

.sdm-inspector-val {{
  color: var(--sdm-text-primary);
  font-family: var(--sdm-font-mono);
  font-size: 11px;
  text-align: right;
  max-width: 60%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}}

/* ── Dialect select wrapper ───────────────────────────────────────── */
.sdm-dialect-select {{
  font-family: var(--sdm-font-mono);
  font-size: 12px;
  color: var(--sdm-text-primary);
  background: var(--sdm-input-bg);
  border: 1px solid var(--sdm-border);
  border-radius: var(--sdm-radius-sm);
  padding: 4px 8px;
}}

/* ── Scrollbar ────────────────────────────────────────────────────── */
::-webkit-scrollbar {{ width: 6px; height: 6px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: var(--sdm-border); border-radius: 3px; }}
::-webkit-scrollbar-thumb:hover {{ background: var(--sdm-text-muted); }}

/* ── Utility ──────────────────────────────────────────────────────── */
.sdm-mono {{ font-family: var(--sdm-font-mono); }}
.sdm-text-muted {{ color: var(--sdm-text-muted); }}
.sdm-text-secondary {{ color: var(--sdm-text-secondary); }}
.sdm-mb-8 {{ margin-bottom: 8px; }}
.sdm-mb-12 {{ margin-bottom: 12px; }}
.sdm-mb-16 {{ margin-bottom: 16px; }}
.sdm-mb-20 {{ margin-bottom: 20px; }}
.sdm-mt-8 {{ margin-top: 8px; }}
.sdm-flex {{ display: flex; }}
.sdm-gap-8 {{ gap: 8px; }}
.sdm-gap-12 {{ gap: 12px; }}
.sdm-items-center {{ align-items: center; }}
.sdm-truncate {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.sdm-w-full {{ width: 100%; }}
</style>
""".strip()


def _vars(tokens: ColorTokens) -> ColorTokens:
    """Identity helper — tokens are injected directly via f-string."""
    return tokens
