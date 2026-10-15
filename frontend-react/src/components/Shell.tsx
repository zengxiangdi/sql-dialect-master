import { Activity, BookOpen, BrainCircuit, Boxes, ChevronLeft, Code2, FileClock, GitCompareArrows, History, Moon, Network, Search, Settings2, Sun, Table2, TerminalSquare, WandSparkles } from "lucide-react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useEffect, useRef, useState } from "react";
import { useApp } from "../lib/app-context";
import { IconButton } from "./ui";

const groups = [
  { label: "Workspace", items: [{ to: "/convert", label: "Convert", icon: GitCompareArrows }, { to: "/nl2sql", label: "NL2SQL", icon: BrainCircuit }, { to: "/diff", label: "Semantic Diff", icon: Code2 }, { to: "/analysis", label: "Query Analysis", icon: Activity }, { to: "/lineage", label: "Lineage", icon: Network }] },
  { label: "Library", items: [{ to: "/functions", label: "Functions", icon: TerminalSquare }, { to: "/types", label: "Types", icon: Table2 }, { to: "/templates", label: "Templates", icon: Boxes }, { to: "/history", label: "History", icon: History }] },
];

export function Shell() {
  const { theme, setTheme } = useApp();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const [palette, setPalette] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => { const handler = (event: KeyboardEvent) => { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setPalette(true); } if (event.key === "Escape") setPalette(false); }; window.addEventListener("keydown", handler); return () => window.removeEventListener("keydown", handler); }, []);
  useEffect(() => { if (palette) inputRef.current?.focus(); }, [palette]);
  const current = location.pathname.split("/")[1] || "convert";
  return <div className="app-shell">
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <div className="brand"><Link to="/convert" className="brand-mark"><span>↔</span><span className="brand-copy">SQL Dialect <b>Master</b><small>Developer workspace</small></span></Link><IconButton label="Collapse navigation" onClick={() => setCollapsed(!collapsed)}><ChevronLeft size={17} className={collapsed ? "rotate-180" : ""} /></IconButton></div>
      <div className="workspace-chip"><span className="online-dot" /><span>Local workspace</span><small>v1.1.4</small></div>
      <nav className="nav-groups">{groups.map((group) => <div className="nav-group" key={group.label}><span className="nav-label">{group.label}</span>{group.items.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}><Icon size={17} /><span>{label}</span></NavLink>)}</div>)}</nav>
      <div className="sidebar-bottom"><NavLink to="/runtime" className={`nav-item ${current === "runtime" ? "active" : ""}`}><Activity size={17} /><span>Runtime</span></NavLink><NavLink to="/settings" className={`nav-item ${current === "settings" ? "active" : ""}`}><Settings2 size={17} /><span>Settings</span></NavLink></div>
    </aside>
    <main className="main-shell">
      <header className="topbar"><div className="breadcrumbs"><span>SQL Dialect Master</span><span className="crumb-separator">/</span><strong>{groups.flatMap((group) => group.items).find((item) => item.to === location.pathname)?.label || (current === "settings" ? "Settings" : "Workspace")}</strong></div><div className="top-actions"><button className="command-trigger" onClick={() => setPalette(true)}><Search size={15} /><span>Jump to anything</span><kbd>⌘ K</kbd></button><IconButton label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`} onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>{theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}</IconButton><div className="api-health"><span className="online-dot" /> API ready</div></div></header>
      <div className="page-frame"><Outlet /></div>
    </main>
    {palette && <CommandPalette close={() => setPalette(false)} inputRef={inputRef} />}
  </div>;
}

function CommandPalette({ close, inputRef }: { close: () => void; inputRef: React.RefObject<HTMLInputElement | null> }) {
  const commands = [{ label: "New conversion", to: "/convert", icon: WandSparkles }, { label: "Natural language to SQL", to: "/nl2sql", icon: BrainCircuit }, { label: "Semantic diff", to: "/diff", icon: GitCompareArrows }, { label: "Function encyclopedia", to: "/functions", icon: BookOpen }, { label: "Conversion history", to: "/history", icon: FileClock }, { label: "Settings", to: "/settings", icon: Settings2 }];
  const [query, setQuery] = useState(""); const filtered = commands.filter((item) => item.label.toLowerCase().includes(query.toLowerCase()));
  return <div className="overlay" onMouseDown={(event) => event.target === event.currentTarget && close()}><div className="command-palette"><div className="palette-search"><Search size={18} /><input ref={inputRef} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search workspace..." /><kbd>ESC</kbd></div><div className="palette-list">{filtered.map(({ label, to, icon: Icon }) => <Link to={to} onClick={close} className="palette-item" key={to}><Icon size={17} /><span>{label}</span><span className="palette-arrow">↵</span></Link>)}{!filtered.length && <p className="palette-empty">No matching command</p>}</div><div className="palette-footer"><span><kbd>↑</kbd><kbd>↓</kbd> navigate</span><span><kbd>↵</kbd> open</span><span><kbd>ESC</kbd> close</span></div></div></div>;
}
