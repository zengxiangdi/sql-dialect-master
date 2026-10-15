import { Clock3, FileDiff, History as HistoryIcon, Trash2 } from "lucide-react";
import { useState } from "react";
import { useApp } from "../lib/app-context";
import { Button, Card, CopyButton, EmptyState } from "../components/ui";
import { PageHeader } from "../components/PageHeader";

/** Local conversion history is isolated from the larger utility route module;
 * the small local-only screen stays eager so returning users see it instantly. */
export function HistoryPage() {
  const { history, removeHistory, clearHistory } = useApp();
  const [query, setQuery] = useState("");
  const normalizedQuery = query.toLowerCase();
  const filtered = history.filter((item) => `${item.source} ${item.target} ${item.sourceDialect} ${item.targetDialect}`.toLowerCase().includes(normalizedQuery));
  return <div>
    <PageHeader eyebrow="LIBRARY / HISTORY" title="Recent conversions" description="Your local history stays in this browser and can be reused without a database." actions={<Button variant="secondary" icon={<Clock3 size={14} />} onClick={clearHistory} disabled={!history.length}>Clear local history</Button>} />
    <Card>
      <label className="search-field wide-search"><HistoryIcon size={15} aria-hidden="true" /><span className="sr-only">Search conversion history</span><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search SQL or dialect..." /></label>
      {filtered.length ? <div className="history-list">{filtered.map((item) => <div className="history-row" key={item.id}><div className="history-icon"><FileDiff size={15} aria-hidden="true" /></div><div className="history-main"><div><span className="history-dialects">{item.sourceDialect} <span>→</span> {item.targetDialect}</span><span className={`badge badge-${item.status}`}>{item.status}</span></div><p>{item.source.replace(/\s+/g, " ").slice(0, 130)}</p><small>{new Date(item.createdAt).toLocaleString()}</small></div><div className="history-actions"><CopyButton value={item.target} /><Button variant="ghost" icon={<Trash2 size={14} />} onClick={() => removeHistory(item.id)}>Remove</Button></div></div>)}</div> : <EmptyState icon={<HistoryIcon size={20} />} title="No local history yet" text="Your successful conversions will appear here." />}
    </Card>
  </div>;
}
