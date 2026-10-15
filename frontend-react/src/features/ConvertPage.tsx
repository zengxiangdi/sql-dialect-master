import { ArrowLeftRight, CheckCircle2, FileCode2, Keyboard, RefreshCw, Wand2 } from "lucide-react";
import { useMemo, useState } from "react";
import { api, ApiError } from "../lib/api";
import { useApp } from "../lib/app-context";
import type { ConvertResponse, Dialect } from "../lib/types";
import { Button, Card, CodeEditor, CopyButton, DialectSelect, DownloadButton, EmptyState, ErrorPanel } from "../components/ui";
import { PageHeader } from "../components/PageHeader";

const SAMPLE = `SELECT\n  customer_id,\n  COUNT(*) AS order_count,\n  SUM(total_amount) AS revenue\nFROM orders\nWHERE created_at >= CURRENT_DATE - INTERVAL '30 days'\nGROUP BY customer_id\nORDER BY revenue DESC;`;

export function ConvertPage() {
  const { addHistory } = useApp();
  const [source, setSource] = useState<Dialect>("mysql");
  const [target, setTarget] = useState<Dialect>("postgres");
  const [sql, setSql] = useState(() => localStorage.getItem("sdm.convert.draft") || SAMPLE);
  const [result, setResult] = useState<ConvertResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [formatting, setFormatting] = useState(false);
  const stale = Boolean(result && result.source_sql !== sql);
  const output = result?.target_sql || "";
  const canConvert = sql.trim().length > 0 && source !== target;
  const resultStatus = useMemo(() => result?.success ? (result.warnings.length ? "warning" : "success") : "error", [result]);

  const convert = async () => {
    setLoading(true); setError(null);
    try { localStorage.setItem("sdm.convert.draft", sql); const next = await api.convert(sql, source, target); setResult(next); if (next.success) addHistory({ source: sql, target: next.target_sql || "", sourceDialect: source, targetDialect: target, status: next.warnings.length ? "warning" : "success" }); else setError(new ApiError(next.error || "Conversion failed", 422, next.error_code || undefined)); }
    catch (caught) { setError(caught instanceof ApiError ? caught : new ApiError("Conversion failed", 500)); }
    finally { setLoading(false); }
  };
  const swap = () => { setSource(target); setTarget(source); setSql(output || sql); setResult(null); setError(null); };
  const format = async () => { if (!sql.trim()) return; setFormatting(true); setError(null); try { const formatted = await api.convert(sql, source, source, true); if (formatted.success && formatted.target_sql) { setSql(formatted.target_sql); setResult(null); localStorage.setItem("sdm.convert.draft", formatted.target_sql); } else setError(new ApiError(formatted.error || "Formatting failed", 422, formatted.error_code || undefined)); } catch (caught) { setError(caught instanceof ApiError ? caught : new ApiError("Formatting failed", 500)); } finally { setFormatting(false); } };
  return <div>
    <PageHeader eyebrow="WORKSPACE / CONVERT" title="Convert SQL with confidence" description="A focused workspace for translating, validating, and reviewing SQL across twelve database dialects." actions={<><Button variant="ghost" icon={<Keyboard size={14} />}>⌘ Enter</Button><Button variant="secondary" icon={<RefreshCw size={14} />} onClick={() => { setSql(""); setResult(null); setError(null); }}>New query</Button></>} />
    <div className="convert-toolbar"><div className="dialect-row"><DialectSelect label="Source dialect" value={source} onChange={(value) => { setSource(value); setResult(null); }} /><Button variant="ghost" icon={<ArrowLeftRight size={16} />} onClick={swap} aria-label="Swap source and target dialects">Swap</Button><DialectSelect label="Target dialect" value={target} onChange={(value) => { setTarget(value); setResult(null); }} /></div><div className="convert-actions"><Button variant="secondary" loading={formatting} disabled={!sql.trim()} onClick={format}>Format</Button><Button variant="primary" loading={loading} disabled={!canConvert} icon={<Wand2 size={15} />} onClick={convert}>Convert SQL</Button></div></div>
    {error && <ErrorPanel message={`${error.message}${error.code ? ` · ${error.code}` : ""}`} onRetry={convert} />}
    <div className="split-editor convert-editor"><div className="editor-panel"><div className="editor-head"><span><FileCode2 size={14} /> Source SQL</span><span className="editor-dialect">{source}</span></div><CodeEditor value={sql} onChange={(value) => { setSql(value); setResult((current) => current ? { ...current } : current); }} minHeight={430} placeholder="Paste SQL here..." ariaLabel="Source SQL editor" /><div className="editor-footer"><span>{sql.length.toLocaleString()} chars</span><button className="link-button" onClick={() => setSql(SAMPLE)}>Load example</button></div></div><div className="editor-panel"><div className="editor-head"><span><CheckCircle2 size={14} /> Target SQL</span><span className="editor-dialect">{target}</span></div>{output ? <pre className={`result-code ${stale ? "stale" : ""}`}>{output}</pre> : <EmptyState icon={<Wand2 size={20} />} title="Your converted SQL appears here" text="Choose dialects, paste a query, then run the conversion." action={<Button variant="secondary" onClick={convert} disabled={!canConvert}>Try conversion</Button>} />}<div className="editor-footer"><span>{stale ? "Result is stale — run again" : result ? `${result.target_validation_state} · ${result.transformations.length} transformations` : "Waiting for input"}</span><div className="result-actions"><CopyButton value={output} /><DownloadButton value={output} /></div></div></div></div>
    {result && result.success && <div className="conversion-details"><Card><div className="card-header"><div><h2>Conversion report</h2><p className="card-subtitle">Review what changed before you use the result.</p></div><span className={`badge badge-${resultStatus}`}>{resultStatus === "success" ? "Validated" : "Review warnings"}</span></div><div className="metric-grid"><div className="metric"><span className="metric-label">Validation</span><div className="metric-value">{result.target_validation_state === "target_valid" ? "Ready" : "Review"}</div></div><div className="metric"><span className="metric-label">Transformations</span><div className="metric-value">{result.transformations.length}</div></div><div className="metric"><span className="metric-label">Warnings</span><div className="metric-value">{result.warnings.length}</div></div><div className="metric"><span className="metric-label">Notes</span><div className="metric-value">{result.compatibility_notes.length}</div></div></div>{(result.warnings.length || result.compatibility_notes.length) ? <div className="report-columns"><div><h3>Warnings</h3>{result.warnings.map((item) => <p className="report-item" key={item}>{item}</p>)}</div><div><h3>Compatibility notes</h3>{result.compatibility_notes.map((item) => <p className="report-item" key={item}>{item}</p>)}</div></div> : <p className="success-line"><CheckCircle2 size={15} /> No compatibility warnings for this conversion.</p>}</Card></div>}
  </div>;
}
