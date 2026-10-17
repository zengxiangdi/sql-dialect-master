import { Activity, BookOpen, BrainCircuit, Boxes, ChevronLeft, Code2, FileClock, GitCompareArrows, History, Moon, Network, Search, Settings2, Sun, Table2, TerminalSquare, WandSparkles } from "lucide-react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useCallback, useEffect, useRef, useState } from "react";
import { useApp } from "../lib/app-context";
import { api } from "../lib/api";
import { IconButton } from "./ui";

const groups = [
  { label: "Workspace", items: [{ to: "/convert", label: "Convert", icon: GitCompareArrows }, { to: "/nl2sql", label: "NL2SQL", icon: BrainCircuit }, { to: "/diff", label: "Semantic Diff", icon: Code2 }, { to: "/analysis", label: "Query Analysis", icon: Activity }, { to: "/lineage", label: "Lineage", icon: Network }] },
  { label: "Library", items: [{ to: "/functions", label: "Functions", icon: TerminalSquare }, { to: "/types", label: "Types", icon: Table2 }, { to: "/templates", label: "Templates", icon: Boxes }, { to: "/history", label: "History", icon: History }] },
];

export function Shell() {
  const { theme, setTheme, apiBase } = useApp();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const [palette, setPalette] = useState(false);
  const [apiStatus, setApiStatus] = useState<"checking" | "ready" | "offline">("checking");
  const inputRef = useRef<HTMLInputElement>(null);
  const commandTriggerRef = useRef<HTMLButtonElement>(null);
  const healthRequestRef = useRef<AbortController | null>(null);
  const closePalette = useCallback(() => { setPalette(false); window.setTimeout(() => commandTriggerRef.current?.focus(), 0); }, []);
  useEffect(() => { const handler = (event: KeyboardEvent) => { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setPalette(true); } if (event.key === "Escape" && palette) closePalette(); }; window.addEventListener("keydown", handler); return () => window.removeEventListener("keydown", handler); }, [closePalette, palette]);
  useEffect(() => { if (palette) inputRef.current?.focus(); }, [palette]);
  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const checkHealth = () => {
      if (!active) return;
      healthRequestRef.current?.abort();
      const controller = new AbortController();
      healthRequestRef.current = controller;
      setApiStatus("checking");
      api.health(controller.signal).then(() => {
        if (active && !controller.signal.aborted) setApiStatus("ready");
      }).catch(() => {
        if (active && !controller.signal.aborted) setApiStatus("offline");
      }).finally(() => {
        if (healthRequestRef.current === controller) healthRequestRef.current = null;
      });
    };
    const scheduleHealthCheck = () => {
      if (timer !== undefined) window.clearTimeout(timer);
      timer = window.setTimeout(checkHealth, 250);
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") scheduleHealthCheck();
    };
    scheduleHealthCheck();
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      healthRequestRef.current?.abort();
      healthRequestRef.current = null;
    };
  }, [apiBase]);
  const current = location.pathname.split("/")[1] || "convert";
  return <div className="app-shell">
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <div className="brand"><Link to="/convert" className="brand-mark"><span>↔</span><span className="brand-copy">SQL Dialect <b>Master</b><small>Developer workspace</small></span></Link><IconButton label="Collapse navigation" onClick={() => setCollapsed(!collapsed)}><ChevronLeft size={17} className={collapsed ? "rotate-180" : ""} /></IconButton></div>
      <div className="workspace-chip"><span className="online-dot" /><span>Local workspace</span><small>v1.1.5</small></div>
      <nav className="nav-groups">{groups.map((group) => <div className="nav-group" key={group.label}><span className="nav-label">{group.label}</span>{group.items.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} aria-label={label} title={label} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}><Icon size={17} aria-hidden="true" /><span>{label}</span></NavLink>)}</div>)}</nav>
      <div className="sidebar-bottom"><NavLink to="/runtime" aria-label="Runtime" title="Runtime" className={`nav-item ${current === "runtime" ? "active" : ""}`}><Activity size={17} aria-hidden="true" /><span>Runtime</span></NavLink><NavLink to="/settings" aria-label="Settings" title="Settings" className={`nav-item ${current === "settings" ? "active" : ""}`}><Settings2 size={17} aria-hidden="true" /><span>Settings</span></NavLink></div>
    </aside>
    <main className="main-shell">
      <header className="topbar"><div className="breadcrumbs"><span>SQL Dialect Master</span><span className="crumb-separator">/</span><strong>{groups.flatMap((group) => group.items).find((item) => item.to === location.pathname)?.label || (current === "settings" ? "Settings" : "Workspace")}</strong></div><div className="top-actions"><button ref={commandTriggerRef} type="button" className="command-trigger" aria-haspopup="dialog" aria-expanded={palette} onClick={() => setPalette(true)}><Search size={15} aria-hidden="true" /><span>Jump to anything</span><kbd>⌘ K</kbd></button><IconButton label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`} onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>{theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}</IconButton><div className={`api-health api-${apiStatus}`} role="status"><span className="online-dot" /> {apiStatus === "checking" ? "Checking API…" : apiStatus === "ready" ? "API ready" : "API offline"}</div></div></header>
      <div className="page-frame"><Outlet /></div>
    </main>
    {palette && <CommandPalette close={closePalette} inputRef={inputRef} />}
  </div>;
}

function CommandPalette({ close, inputRef }: { close: () => void; inputRef: React.RefObject<HTMLInputElement | null> }) {
  const navigate = useNavigate();
  const commands = [{ label: "New conversion", to: "/convert", icon: WandSparkles }, { label: "Natural language to SQL", to: "/nl2sql", icon: BrainCircuit }, { label: "Semantic diff", to: "/diff", icon: GitCompareArrows }, { label: "Function encyclopedia", to: "/functions", icon: BookOpen }, { label: "Conversion history", to: "/history", icon: FileClock }, { label: "Settings", to: "/settings", icon: Settings2 }];
  const [query, setQuery] = useState(""); const [activeIndex, setActiveIndex] = useState(0); const filtered = commands.filter((item) => item.label.toLowerCase().includes(query.toLowerCase()));
  useEffect(() => setActiveIndex(0), [query]);
  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") { event.preventDefault(); setActiveIndex((index) => filtered.length ? (index + 1) % filtered.length : 0); }
    else if (event.key === "ArrowUp") { event.preventDefault(); setActiveIndex((index) => filtered.length ? (index - 1 + filtered.length) % filtered.length : 0); }
    else if (event.key === "Enter" && filtered[activeIndex]) { event.preventDefault(); navigate(filtered[activeIndex].to); close(); }
  };
  const activeOptionId = filtered.length ? `command-option-${activeIndex}` : undefined;
  return <div className="overlay" onMouseDown={(event) => event.target === event.currentTarget && close()}><div className="command-palette" role="dialog" aria-modal="true" aria-labelledby="command-palette-title"><h2 id="command-palette-title" className="sr-only">Workspace commands</h2><div className="palette-search"><Search size={18} aria-hidden="true" /><input ref={inputRef} aria-label="Search workspace commands" aria-controls="command-list" aria-activedescendant={activeOptionId} value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={onKeyDown} placeholder="Search workspace..." /><kbd>ESC</kbd></div><div className="palette-list" id="command-list" role="listbox">{filtered.map(({ label, to, icon: Icon }, index) => <Link to={to} onClick={close} className={`palette-item ${index === activeIndex ? "active" : ""}`} id={`command-option-${index}`} role="option" aria-selected={index === activeIndex} key={to} onMouseEnter={() => setActiveIndex(index)}><Icon size={17} aria-hidden="true" /><span>{label}</span><span className="palette-arrow">↵</span></Link>)}{!filtered.length && <p className="palette-empty" role="status">No matching command</p>}</div><div className="palette-footer"><span><kbd>↑</kbd><kbd>↓</kbd> navigate</span><span><kbd>↵</kbd> open</span><span><kbd>ESC</kbd> close</span></div></div></div>;
}
