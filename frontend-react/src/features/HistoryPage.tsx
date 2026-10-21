import { Clock3, FileDiff, History as HistoryIcon, Star, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApp } from "../lib/app-context";
import { writeConvertHandoff, writeDiffHandoff } from "../lib/handoff";
import { Button, Card, CopyButton, EmptyState, IconButton } from "../components/ui";
import { PageHeader } from "../components/PageHeader";

const HISTORY_PAGE_SIZE = 10;

/** Local conversion history is isolated from the larger utility route module;
 * the small local-only screen stays eager so returning users see it instantly. */
export function HistoryPage() {
  const { history, removeHistory, clearHistory, toggleFavorite } = useApp();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "favorites">("all");
  const [page, setPage] = useState(1);
  const normalizedQuery = query.toLowerCase();
  const filtered = history.filter((item) => (
    `${item.source} ${item.target} ${item.sourceDialect} ${item.targetDialect}`.toLowerCase().includes(normalizedQuery)
    && (filter === "all" || item.favorite === true)
  ));
  const pageCount = Math.max(1, Math.ceil(filtered.length / HISTORY_PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  // Persist the clamp when deletion or removing a favorite shrinks the list.
  // Keeping this guarded avoids rendering an empty, out-of-range page.
  if (page !== currentPage) setPage(currentPage);
  const start = (currentPage - 1) * HISTORY_PAGE_SIZE;
  const visible = filtered.slice(start, start + HISTORY_PAGE_SIZE);
  const noFavorites = filter === "favorites" && !history.some((item) => item.favorite === true);
  const emptyTitle = !history.length ? "No local history yet" : noFavorites ? "No favorites yet" : "No matching history";
  const emptyText = !history.length
    ? "Your successful conversions will appear here."
    : noFavorites ? "Star a conversion to find it here." : "Try a different search or filter.";
  const changeFilter = (next: "all" | "favorites") => {
    if (next !== filter) { setFilter(next); setPage(1); }
  };
  return <div>
    <PageHeader eyebrow="LIBRARY / HISTORY" title="Recent conversions" description="Your local history stays in this browser and can be reused without a database." actions={<Button variant="secondary" icon={<Clock3 size={14} />} onClick={clearHistory} disabled={!history.length}>Clear local history</Button>} />
    <Card>
      <div className="history-toolbar">
        <label className="search-field wide-search"><HistoryIcon size={15} aria-hidden="true" /><span className="sr-only">Search conversion history</span><input value={query} onChange={(e) => { setQuery(e.target.value); setPage(1); }} placeholder="Search SQL or dialect..." /></label>
        <div className="history-tabs" role="group" aria-label="History filters">
          <Button variant="ghost" aria-pressed={filter === "all"} onClick={() => changeFilter("all")}>All</Button>
          <Button variant="ghost" aria-pressed={filter === "favorites"} onClick={() => changeFilter("favorites")}>Favorites</Button>
        </div>
      </div>
      {visible.length ? <div className="history-list">{visible.map((item) => <div className="history-row" key={item.id}>
        <div className="history-icon"><FileDiff size={15} aria-hidden="true" /></div>
        <div className="history-main">
          <div><span className="history-dialects">{item.sourceDialect} <span>→</span> {item.targetDialect}</span><span className={`badge badge-${item.status}`}>{item.status}</span></div>
          <p>{item.source.replace(/\s+/g, " ").slice(0, 130)}</p>
          <small>{new Date(item.createdAt).toLocaleString()}</small>
          {item.truncated && <small role="status">Preview truncated; actions disabled</small>}
        </div>
        <div className="history-actions">
          <IconButton label={item.favorite ? "Remove from favorites" : "Add to favorites"} aria-pressed={item.favorite === true} className={`icon-button history-favorite${item.favorite ? " selected" : ""}`} onClick={() => toggleFavorite(item.id)}><Star size={15} fill={item.favorite ? "currentColor" : "none"} aria-hidden="true" /></IconButton>
          <Button variant="ghost" disabled={item.truncated} title={item.truncated ? "Preview truncated; action disabled" : undefined} onClick={() => { writeConvertHandoff({ sql: item.source, sourceDialect: item.sourceDialect, targetDialect: item.targetDialect }); navigate(`/convert?source=${item.sourceDialect}&target=${item.targetDialect}`); }}>Use in Convert</Button>
          <Button variant="ghost" disabled={item.truncated} title={item.truncated ? "Preview truncated; action disabled" : undefined} onClick={() => { writeDiffHandoff({ sourceSql: item.source, targetSql: item.target, sourceDialect: item.sourceDialect, targetDialect: item.targetDialect }); navigate(`/diff?source=${item.sourceDialect}&target=${item.targetDialect}`); }}>Use in Diff</Button>
          <CopyButton value={item.target} disabled={item.truncated} title={item.truncated ? "Preview truncated; copying is disabled" : undefined} />
          <Button variant="ghost" icon={<Trash2 size={14} />} onClick={() => removeHistory(item.id)}>Remove</Button>
        </div>
      </div>)}</div> : <EmptyState icon={<HistoryIcon size={20} />} title={emptyTitle} text={emptyText} />}
      <div className="history-pagination">
        <div className="history-pagination-summary" aria-live="polite"><span>Page {currentPage} of {pageCount}</span><span>Showing {filtered.length ? start + 1 : 0}–{Math.min(start + HISTORY_PAGE_SIZE, filtered.length)} of {filtered.length}</span></div>
        <div className="history-pagination-controls">
          <Button variant="secondary" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}>Prev</Button>
          <Button variant="secondary" disabled={currentPage === pageCount} onClick={() => setPage(currentPage + 1)}>Next</Button>
        </div>
      </div>
    </Card>
  </div>;
}
