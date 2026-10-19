import { ExternalLink, GitBranch, Play, Settings2, Table2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import {
  dialectParam,
  clearHandoff,
  readAnalysisHandoff,
  readDiffHandoff,
  readLineageHandoff,
  writeAnalysisHandoff,
  writeDiffHandoff,
  writeLineageHandoff,
} from "../lib/handoff";
import { saveDraft } from "../lib/storage";
import type { ParseResponse } from "../lib/types";
import { Button, Card, CodeEditor, DialectSelect, EmptyState, ErrorPanel } from "../components/ui";
import { PageHeader } from "../components/PageHeader";

const templates = [
  { category: "Analytics", title: "Revenue by customer", description: "Rank customers by their total order value.", sql: "SELECT customer_id, SUM(total_amount) AS revenue\nFROM orders\nGROUP BY customer_id\nORDER BY revenue DESC;" },
  { category: "Operations", title: "Recent paid orders", description: "Find recent orders ready for fulfillment.", sql: "SELECT *\nFROM orders\nWHERE status = 'paid'\n  AND created_at >= CURRENT_DATE - INTERVAL '7 days';" },
  { category: "Quality", title: "Null audit", description: "Count missing values in a critical field.", sql: "SELECT COUNT(*) AS missing_count\nFROM orders\nWHERE customer_id IS NULL;" },
  { category: "Reporting", title: "Monthly order volume", description: "Create a compact monthly trend query.", sql: "SELECT DATE_TRUNC('month', created_at) AS month, COUNT(*)\nFROM orders\nGROUP BY month\nORDER BY month;" },
];

export function TemplatesPage() { const navigate = useNavigate(); return <div><PageHeader eyebrow="LIBRARY / TEMPLATES" title="Start from a proven shape" description="Reusable query patterns for exploration, reporting, and operational checks." /><div className="template-grid">{templates.map((template) => <article className="template-card" key={template.title}><span className="eyebrow">{template.category}</span><h2>{template.title}</h2><p>{template.description}</p><pre>{template.sql}</pre><Button variant="secondary" onClick={() => { clearHandoff("convert"); saveDraft(template.sql); navigate("/convert"); }}>Use in Convert <ExternalLink size={13} /></Button></article>)}</div></div>; }

const ANALYSIS_DEFAULT_SQL = "SELECT customer_id, COUNT(*) AS orders FROM orders GROUP BY customer_id ORDER BY orders DESC;";
const LINEAGE_DEFAULT_SQL = "SELECT o.id, c.name FROM orders o JOIN customers c ON c.id = o.customer_id;";

export function AnalysisPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const handoff = useMemo(() => readAnalysisHandoff(), []);
  const [sql, setSql] = useState(() => handoff?.sql || ANALYSIS_DEFAULT_SQL);
  const [dialect, setDialect] = useState(() => dialectParam(searchParams.get("dialect"), handoff?.dialect || "postgres"));
  const [result, setResult] = useState<Awaited<ReturnType<typeof api.parse>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const pendingRequest = useRef<AbortController | null>(null);
  useEffect(() => {
    if (searchParams.get("dialect") !== dialect) {
      setSearchParams((current) => { const next = new URLSearchParams(current); next.set("dialect", dialect); return next; }, { replace: true });
    }
  }, [dialect, searchParams, setSearchParams]);
  useEffect(() => {
    const timer = window.setTimeout(() => writeAnalysisHandoff({ sql, dialect }), 300);
    return () => window.clearTimeout(timer);
  }, [dialect, sql]);
  const analyze = useCallback(async () => {
    if (!sql.trim()) { setResult(null); setError("Enter SQL to analyze."); return; }
    pendingRequest.current?.abort();
    const controller = new AbortController();
    pendingRequest.current = controller;
    setLoading(true); setError(null);
    try {
      const next = await api.parse(sql, dialect, controller.signal);
      if (!controller.signal.aborted) setResult(next);
    } catch (e) {
      if (!controller.signal.aborted) { setResult(null); setError(e instanceof Error ? e.message : "Analysis failed"); }
    } finally {
      if (pendingRequest.current === controller) { pendingRequest.current = null; setLoading(false); }
    }
  }, [dialect, sql]);
  useEffect(() => () => pendingRequest.current?.abort(), []);
  const elements = result?.elements;
  const metrics = [{ label: "Tables", value: elements?.tables?.length ?? "—", detail: "Relations referenced" }, { label: "Joins", value: elements?.joins?.length ?? "—", detail: "Join edges" }, { label: "Columns", value: elements?.columns?.length ?? "—", detail: "Columns discovered" }, { label: "Functions", value: elements?.functions?.length ?? "—", detail: "Function calls" }];
  return <div><PageHeader eyebrow="WORKSPACE / QUERY ANALYSIS" title="Understand the shape of a query" description="Static SQL analysis highlights structure and risk. It does not execute a query or require a database connection." actions={<Button variant="primary" loading={loading} disabled={!sql.trim()} icon={<Play size={14} />} onClick={analyze}>Analyze</Button>} /><Card><div className="card-header"><div><h2>Static parser input</h2><p className="card-subtitle">The parser endpoint returns AST metadata without touching a database.</p></div><DialectSelect label="Dialect" compact value={dialect} onChange={(value) => { setDialect(value); setResult(null); setError(null); }} /></div><CodeEditor value={sql} onChange={(value) => { pendingRequest.current?.abort(); setSql(value); setResult(null); setError(null); }} minHeight={180} ariaLabel="Analysis SQL editor" />{error && <ErrorPanel message={error} onRetry={analyze} />}</Card><div className="metric-grid analysis-metrics">{metrics.map((metric) => <div className="metric" key={metric.label}><span className="metric-label">{metric.label}</span><div className="metric-value">{metric.value}</div><div className="metric-detail">{metric.detail}</div></div>)}</div>{elements && <Card><div className="card-header"><div><h2>Detected structure</h2><p className="card-subtitle">Query type: {elements.query_type || "unknown"}</p></div></div><div className="analysis-tags">{elements.has_cte && <span>CTE</span>}{elements.has_window && <span>Window</span>}{elements.has_aggregation && <span>Aggregation</span>}{elements.has_order_by && <span>Order by</span>}{elements.has_limit && <span>Limit</span>}{elements.tables?.map((table, index) => <span key={`${table.name}-${index}`}>{table.name}</span>)}</div></Card>}</div>;
}

export function DiffPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const handoff = useMemo(() => readDiffHandoff(), []);
  const [source, setSource] = useState(() => handoff?.sourceSql || "SELECT id, name FROM users WHERE active = 1;");
  const [target, setTarget] = useState(() => handoff?.targetSql ?? "SELECT id, name\nFROM users\nWHERE active = TRUE;");
  const [sourceDialect, setSourceDialect] = useState(() => dialectParam(searchParams.get("source"), handoff?.sourceDialect || "postgres"));
  const [targetDialect, setTargetDialect] = useState(() => dialectParam(searchParams.get("target"), handoff?.targetDialect || "mysql"));
  const [result, setResult] = useState<Awaited<ReturnType<typeof api.diff>> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [fallbackCompared, setFallbackCompared] = useState(false);
  const pendingRequest = useRef<AbortController | null>(null);
  const same = source.trim() === target.trim();
  useEffect(() => {
    if (searchParams.get("source") !== sourceDialect || searchParams.get("target") !== targetDialect) {
      setSearchParams((current) => { const next = new URLSearchParams(current); next.set("source", sourceDialect); next.set("target", targetDialect); return next; }, { replace: true });
    }
  }, [searchParams, setSearchParams, sourceDialect, targetDialect]);
  useEffect(() => {
    const timer = window.setTimeout(() => writeDiffHandoff({ sourceSql: source, targetSql: target, sourceDialect, targetDialect }), 300);
    return () => window.clearTimeout(timer);
  }, [source, sourceDialect, target, targetDialect]);
  const compare = useCallback(async () => {
    if (!source.trim() || !target.trim()) return;
    pendingRequest.current?.abort();
    const controller = new AbortController();
    pendingRequest.current = controller;
    setLoading(true); setError(null); setResult(null); setFallbackCompared(false);
    try {
      const next = await api.diff(source, target, sourceDialect, targetDialect, controller.signal);
      if (!controller.signal.aborted) setResult(next);
    } catch (caught) {
      if (!controller.signal.aborted) { setError(caught instanceof ApiError ? caught : new ApiError("Semantic diff unavailable", 0)); setFallbackCompared(true); }
    } finally {
      if (pendingRequest.current === controller) { pendingRequest.current = null; setLoading(false); }
    }
  }, [source, sourceDialect, target, targetDialect]);
  useEffect(() => () => pendingRequest.current?.abort(), []);
  const reset = (setter: (value: string) => void, value: string) => { pendingRequest.current?.abort(); setter(value); setResult(null); setError(null); setFallbackCompared(false); };
  const setDialects = (nextSource: typeof sourceDialect, nextTarget: typeof targetDialect) => { setSourceDialect(nextSource); setTargetDialect(nextTarget); setResult(null); setError(null); };
  const status = result?.status;
  return <div><PageHeader eyebrow="WORKSPACE / SEMANTIC DIFF" title="See the change, line by line" description="Compare SQL structure with target-aware semantic findings before you ship a query." actions={<Button variant="primary" loading={loading} disabled={!source.trim() || !target.trim()} icon={<Play size={14} />} onClick={compare}>Compare</Button>} />{error && <ErrorPanel message={error.message} onRetry={compare} />}{result && <div className={`diff-banner ${status === "equivalent" ? "same" : "changed"}`}><GitBranch size={17} aria-hidden="true" /><div><strong>{status === "equivalent" ? "Statements are semantically equivalent" : status === "parse_error" ? "Unable to parse one or both statements" : `Semantic status: ${status}`}</strong><p>{result.error || result.parse_error || (result.difference_categories.length ? `Categories: ${result.difference_categories.join(", ")}` : "No semantic differences were detected.")}</p></div></div>}{!result && fallbackCompared && <div className={`diff-banner ${same ? "same" : "changed"}`}><GitBranch size={17} aria-hidden="true" /><div><strong>{same ? "Statements are textually identical" : "Statements differ"}</strong><p>Semantic diff is unavailable; showing the local text comparison fallback.</p></div></div>}{!result && !fallbackCompared && !error && same && <div className="diff-banner same"><GitBranch size={17} aria-hidden="true" /><div><strong>Text inputs are identical</strong><p>Run Compare to request target-aware semantic analysis.</p></div></div>}<div className="split-editor"><div className="editor-panel"><div className="editor-head"><span>Source</span><DialectSelect label="Source dialect" compact value={sourceDialect} onChange={(value) => setDialects(value, targetDialect)} /></div><CodeEditor value={source} onChange={(value) => reset(setSource, value)} minHeight={390} ariaLabel="Source SQL editor" /></div><div className="editor-panel"><div className="editor-head"><span>Target</span><DialectSelect label="Target dialect" compact value={targetDialect} onChange={(value) => setDialects(sourceDialect, value)} /></div><CodeEditor value={target} onChange={(value) => reset(setTarget, value)} minHeight={390} ariaLabel="Target SQL editor" /></div></div>{result?.structured_differences.length ? <Card><div className="card-header"><div><h2>Structured findings</h2><p className="card-subtitle">Confidence: {Math.round(result.confidence * 100)}%</p></div></div><div className="report-columns">{result.structured_differences.map((finding, index) => <div className="report-item" key={`${finding.category}-${index}`}><strong>{finding.category} · {finding.severity}</strong><p>{finding.explanation}</p><small>{finding.source_fragment} → {finding.target_fragment}</small></div>)}</div></Card> : <Card className="diff-empty"><EmptyState icon={<GitBranch size={20} />} title="Semantic comparison is ready" text="Compare the two statements to show categorized findings, severity, and confidence." /></Card>}</div>;
}

export function LineagePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const handoff = useMemo(() => readLineageHandoff(), []);
  const [sql, setSql] = useState(() => handoff?.sql || LINEAGE_DEFAULT_SQL);
  const [dialect, setDialect] = useState(() => dialectParam(searchParams.get("dialect"), handoff?.dialect || "postgres"));
  const [elements, setElements] = useState<ParseResponse["elements"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const pendingRequest = useRef<AbortController | null>(null);
  useEffect(() => {
    if (searchParams.get("dialect") !== dialect) setSearchParams((current) => { const next = new URLSearchParams(current); next.set("dialect", dialect); return next; }, { replace: true });
  }, [dialect, searchParams, setSearchParams]);
  useEffect(() => {
    const timer = window.setTimeout(() => writeLineageHandoff({ sql, dialect }), 300);
    return () => window.clearTimeout(timer);
  }, [dialect, sql]);
  const build = useCallback(async () => {
    if (!sql.trim()) { setElements(null); setError("Enter SQL to build lineage."); return; }
    pendingRequest.current?.abort();
    const controller = new AbortController();
    pendingRequest.current = controller;
    setLoading(true); setError(null);
    try {
      const parsed = await api.parse(sql, dialect, controller.signal);
      if (!controller.signal.aborted) setElements(parsed.elements);
    } catch (caught) {
      if (!controller.signal.aborted) { setElements(null); setError(caught instanceof Error ? caught.message : "Lineage analysis failed"); }
    } finally {
      if (pendingRequest.current === controller) { pendingRequest.current = null; setLoading(false); }
    }
  }, [dialect, sql]);
  useEffect(() => () => pendingRequest.current?.abort(), []);
  return <div><PageHeader eyebrow="WORKSPACE / LINEAGE" title="Follow data through the query" description="A clean canvas for table and column relationships, designed for static SQL exploration." actions={<Button variant="primary" loading={loading} disabled={!sql.trim()} icon={<GitBranch size={14} />} onClick={build}>Build lineage</Button>} /><Card><div className="card-header"><DialectSelect label="Dialect" compact value={dialect} onChange={(value) => { pendingRequest.current?.abort(); setDialect(value); setElements(null); setError(null); }} /></div><CodeEditor value={sql} onChange={(value) => { pendingRequest.current?.abort(); setSql(value); setElements(null); setError(null); }} minHeight={150} ariaLabel="Lineage SQL editor" />{error && <ErrorPanel message={error} onRetry={build} />}{elements ? <LineageResults elements={elements} /> : <EmptyState icon={<GitBranch size={20} />} title="Lineage canvas" text="Analyze a query to map its source relations. Runtime execution is never assumed." />}</Card></div>;
}

type LineageColumn = NonNullable<ParseResponse["elements"]["columns"]>[number];

function LineageColumns({ columns, label, qualified = false }: { columns: LineageColumn[]; label: string; qualified?: boolean }) {
  return <ul className="lineage-columns" aria-label={label}>{columns.map((column, index) => <li key={`${column.table || ""}-${column.name}-${index}`}>
    <span className="mono">{qualified && column.table ? `${column.table}.${column.name}` : column.name}</span>
    {column.alias && column.alias !== column.name && <span className="muted"> as {column.alias}</span>}
  </li>)}</ul>;
}

function LineageResults({ elements }: { elements: ParseResponse["elements"] }) {
  const tables = elements.tables ?? [];
  const columns = elements.columns ?? [];
  const joins = elements.joins ?? [];
  const groupedColumns = new Map<string, LineageColumn[] | null>();
  for (const table of tables) {
    const key = table.alias || table.name;
    // The parser has no scope identifier to disambiguate repeated aliases.
    groupedColumns.set(key, groupedColumns.has(key) ? null : []);
  }
  const unqualified: LineageColumn[] = [];
  for (const column of columns) {
    const group = column.table ? groupedColumns.get(column.table) : undefined;
    if (group) group.push(column);
    else unqualified.push(column);
  }
  const counts = [
    { label: "Tables", value: tables.length },
    { label: "Columns", value: columns.length },
    { label: "Joins", value: joins.length },
    { label: "Unqualified columns", value: unqualified.length },
  ];

  return <section className="lineage-results" aria-label="Lineage results">
    <dl className="lineage-summary" aria-label="Lineage summary">{counts.map((count) => <div key={count.label}>
      <dt>{count.label}</dt><dd>{count.value}</dd>
    </div>)}</dl>
    {tables.length ? <ul className="lineage-table-grid" aria-label="Tables">{tables.map((table, index) => {
      const key = table.alias || table.name;
      const tableColumns = groupedColumns.get(key) ?? [];
      return <li key={`${key}-${index}`}><section className="lineage-table" aria-label={`Table ${key}`}>
        <header className="lineage-table-header"><Table2 size={16} aria-hidden="true" /><h3>{table.name}</h3></header>
        <div className="lineage-table-metadata">
          {table.alias && table.alias !== table.name && <p>Alias: <span className="mono">{table.alias}</span></p>}
          {table.schema && <p>Schema: <span className="mono">{table.schema}</span></p>}
          {table.catalog && <p>Catalog: <span className="mono">{table.catalog}</span></p>}
        </div>
        <p className="lineage-column-count">{tableColumns.length} {tableColumns.length === 1 ? "column" : "columns"}</p>
        {tableColumns.length ? <LineageColumns columns={tableColumns} label={`${key} columns`} /> : <p className="lineage-empty">No columns for this table.</p>}
      </section></li>;
    })}</ul> : <EmptyState icon={<GitBranch size={20} />} title="Lineage canvas" text="No source tables were found in this query." />}
    <section className="lineage-group" aria-label="Unqualified / unmatched columns">
      <h3>Unqualified / unmatched columns</h3>
      {unqualified.length ? <LineageColumns columns={unqualified} label="Unqualified and unmatched columns" qualified /> : <p className="lineage-empty">No unqualified or unmatched columns.</p>}
    </section>
    <section className="lineage-group" aria-label="Join relationships">
      <h3>JOIN relationships</h3>
      {joins.length ? <ul className="lineage-joins">{joins.map((join, index) => <li key={`${join.type}-${join.table}-${index}`}>
        <div className="lineage-join-header"><strong>{join.type}</strong><span>Target table: <span className="mono">{join.table}</span></span></div>
        <pre>{join.on_condition || "No ON condition."}</pre>
      </li>)}</ul> : <p className="lineage-empty">No joins found.</p>}
    </section>
  </section>;
}

export function RuntimePage() { const navigate = useNavigate(); return <div><PageHeader eyebrow="SYSTEM / RUNTIME" title="Runtime verification" description="Use this page when a database connection is available. Local SQL conversion never requires one." /><Card className="runtime-card"><div className="runtime-symbol"><Settings2 size={22} /></div><div><h2>No database connected</h2><p>Static parsing, conversion, functions, types, and NL2SQL remain fully available. Runtime checks will appear here after you configure a safe connection.</p><Button variant="secondary" onClick={() => navigate("/settings")}>Open settings</Button></div></Card></div>; }
