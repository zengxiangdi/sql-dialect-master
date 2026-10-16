import { BookOpen, Filter, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../lib/api";
import { DIALECT_LABELS, type Dialect, type FunctionItem, type TypeMapping } from "../lib/types";
import { Badge, Card, DialectSelect, EmptyState, ErrorPanel } from "../components/ui";
import { PageHeader } from "../components/PageHeader";

export function FunctionsPage() {
  const [items, setItems] = useState<FunctionItem[]>([]);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloadToken, setReloadToken] = useState(0);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true); setError(null);
      api.functions(search, category, 100, controller.signal).then((data) => { if (active) setItems(data.functions); }).catch((e) => { if (active && !controller.signal.aborted) setError(e instanceof ApiError ? e : new ApiError("Unable to load functions", 0)); }).finally(() => { if (active) setLoading(false); });
    }, 180);
    return () => { active = false; controller.abort(); window.clearTimeout(timer); };
  }, [search, category, reloadToken]);
  return <div><PageHeader eyebrow="LIBRARY / FUNCTIONS" title="Function encyclopedia" description="Search syntax, semantics, and dialect coverage from one compact reference." /><Card><div className="filter-row"><label className="search-field"><Search size={15} aria-hidden="true" /><span className="sr-only">Search functions</span><input aria-label="Search functions" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search functions..." /></label><label className="select-inline"><Filter size={14} aria-hidden="true" /><span className="sr-only">Filter functions by category</span><select aria-label="Filter functions by category" value={category} onChange={(e) => setCategory(e.target.value)}><option value="">All categories</option>{["string", "date", "math", "aggregate", "window", "conditional", "conversion", "json", "array", "system", "geo"].map((item) => <option key={item} value={item}>{item}</option>)}</select></label></div>{error ? <ErrorPanel message={error.message} onRetry={() => setReloadToken((value) => value + 1)} /> : loading ? <div className="loading-line" role="status">Loading functions…</div> : <div className="function-grid">{items.map((item) => <article className="function-card" key={item.name}><div className="function-title"><span className="function-symbol">ƒ</span><div><h3>{item.name}</h3><span className="muted">{item.category}</span></div></div><p>{item.description || "Cross-dialect SQL function"}</p><div className="dialect-pills">{Object.keys(item.dialects || {}).slice(0, 5).map((dialect) => <span key={dialect}>{DIALECT_LABELS[dialect as Dialect] || dialect}</span>)}</div></article>)}{!items.length && <EmptyState icon={<BookOpen size={20} />} title="No functions found" text="Try a broader search or clear the category filter." />}</div>}</Card></div>;
}

export function TypesPage() {
  const [source, setSource] = useState<Dialect>("mysql");
  const [target, setTarget] = useState<Dialect>("postgres");
  const [items, setItems] = useState<TypeMapping[]>([]);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloadToken, setReloadToken] = useState(0);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api.types(source, target, controller.signal)
      .then((data) => { if (active) setItems(data.mappings); })
      .catch((e) => {
        // An in-flight request is expected to be cancelled when the user
        // changes dialects; do not surface that cancellation as an error.
        if (active && !controller.signal.aborted) setError(e instanceof ApiError ? e : new ApiError("Unable to load type mappings", 500));
      })
      .finally(() => { if (active && !controller.signal.aborted) setLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [source, target, reloadToken]);
  const filtered = useMemo(() => {
    const normalized = search.toLowerCase();
    return items.filter((item) => JSON.stringify(item).toLowerCase().includes(normalized));
  }, [items, search]);
  return <div><PageHeader eyebrow="LIBRARY / TYPES" title="Type mapping matrix" description="Compare source and target type contracts before you migrate a schema." /><Card><div className="filter-row"><DialectSelect compact label="Source" value={source} onChange={setSource} /><DialectSelect compact label="Target" value={target} onChange={setTarget} /><label className="search-field"><Search size={15} aria-hidden="true" /><span className="sr-only">Filter types</span><input aria-label="Filter types" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Filter types..." /></label></div>{error ? <ErrorPanel message={error.message} onRetry={() => setReloadToken((value) => value + 1)} /> : loading ? <div className="loading-line" role="status">Loading type mappings…</div> : <div className="table-wrap"><table><caption className="sr-only">SQL type mappings from {DIALECT_LABELS[source]} to {DIALECT_LABELS[target]}</caption><thead><tr><th>Canonical type</th><th>{DIALECT_LABELS[source]}</th><th>{DIALECT_LABELS[target]}</th><th>Status</th></tr></thead><tbody>{filtered.slice(0, 80).map((item, index) => { const sourceValue = item.source ?? "N/A"; const targetValue = item.target ?? "N/A"; const status = targetValue === "N/A" ? "warning" : "success"; return <tr key={`${item.type}-${index}`}><td className="mono">{item.type}</td><td className="mono">{sourceValue}</td><td className="mono">{targetValue}</td><td><Badge status={status}>{status === "success" ? "Mapped" : "Unsupported"}</Badge></td></tr>; })}</tbody></table></div>}</Card></div>;
}
