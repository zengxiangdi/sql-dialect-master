import { ArrowLeftRight, CheckCircle2, FileCode2, Keyboard, RefreshCw, Wand2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { useApp } from "../lib/app-context";
import { dialectParam, readConvertHandoff, writeDiffHandoff } from "../lib/handoff";
import { readDraft, removeDraft, saveDraft } from "../lib/storage";
import type { ConvertResponse, Dialect } from "../lib/types";
import { Button, Card, CodeEditor, CopyButton, DialectSelect, DownloadButton, EmptyState, ErrorPanel } from "../components/ui";
import { PageHeader } from "../components/PageHeader";

const SAMPLE = `SELECT\n  customer_id,\n  COUNT(*) AS order_count,\n  SUM(total_amount) AS revenue\nFROM orders\nWHERE created_at >= CURRENT_DATE - INTERVAL '30 days'\nGROUP BY customer_id\nORDER BY revenue DESC;`;

export function ConvertPage() {
  const { addHistory } = useApp();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const convertHandoff = useMemo(() => readConvertHandoff(), []);
  const [source, setSource] = useState<Dialect>(() => dialectParam(searchParams.get("source"), convertHandoff?.sourceDialect || "mysql"));
  const [target, setTarget] = useState<Dialect>(() => dialectParam(searchParams.get("target"), convertHandoff?.targetDialect || "postgres"));
  const [sql, setSql] = useState(() => convertHandoff?.sql || readDraft() || SAMPLE);
  const [result, setResult] = useState<ConvertResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [formatting, setFormatting] = useState(false);
  const [lastAction, setLastAction] = useState<"convert" | "format">("convert");
  const pendingRequest = useRef<AbortController | null>(null);
  const stale = Boolean(result && result.source_sql !== sql);
  const output = result?.target_sql || "";
  const canConvert = sql.trim().length > 0 && source !== target;
  const resultStatus = useMemo(() => result?.success ? (result.warnings.length ? "warning" : "success") : "error", [result]);

  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    let changed = false;
    if (next.get("source") !== source) { next.set("source", source); changed = true; }
    if (next.get("target") !== target) { next.set("target", target); changed = true; }
    if (changed) setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams, source, target]);

  const setDialects = (nextSource: Dialect, nextTarget: Dialect) => {
    setSource(nextSource); setTarget(nextTarget);
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("source", nextSource); next.set("target", nextTarget);
      return next;
    }, { replace: true });
  };

  const cancelPendingRequest = useCallback(() => {
    pendingRequest.current?.abort();
  }, []);

  const convert = useCallback(async () => {
    if (!canConvert) return;
    cancelPendingRequest();
    setFormatting(false);
    setLastAction("convert");
    const controller = new AbortController();
    pendingRequest.current = controller;
    setLoading(true); setError(null);
    try {
      saveDraft(sql);
      const next = await api.convert(sql, source, target, true, controller.signal);
      if (controller.signal.aborted) return;
      setResult(next);
      if (next.success) addHistory({ source: sql, target: next.target_sql || "", sourceDialect: source, targetDialect: target, status: next.warnings.length ? "warning" : "success" });
      else setError(new ApiError(next.error || "Conversion failed", 422, next.error_code || undefined));
    } catch (caught) {
      if (controller.signal.aborted) return;
      setError(caught instanceof ApiError ? caught : new ApiError("Conversion failed", 500));
    } finally {
      if (pendingRequest.current === controller) {
        pendingRequest.current = null;
        setLoading(false);
      }
    }
  }, [addHistory, cancelPendingRequest, canConvert, source, sql, target]);

  const format = useCallback(async () => {
    if (!sql.trim()) return;
    cancelPendingRequest();
    setLoading(false);
    setLastAction("format");
    const controller = new AbortController();
    pendingRequest.current = controller;
    setFormatting(true); setError(null);
    try {
      const formatted = await api.convert(sql, source, source, true, controller.signal);
      if (controller.signal.aborted) return;
      if (formatted.success && formatted.target_sql) {
        setSql(formatted.target_sql); setResult(null); saveDraft(formatted.target_sql);
      } else setError(new ApiError(formatted.error || "Formatting failed", 422, formatted.error_code || undefined));
    } catch (caught) {
      if (controller.signal.aborted) return;
      setError(caught instanceof ApiError ? caught : new ApiError("Formatting failed", 500));
    } finally {
      if (pendingRequest.current === controller) {
        pendingRequest.current = null;
        setFormatting(false);
      }
    }
  }, [cancelPendingRequest, sql, source]);

  useEffect(() => cancelPendingRequest, [cancelPendingRequest]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && canConvert && !loading && !formatting) {
        event.preventDefault();
        void convert();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [canConvert, loading, formatting, convert]);
  const swap = () => { cancelPendingRequest(); setLoading(false); setFormatting(false); setDialects(target, source); setSql(output || sql); setResult(null); setError(null); };
  return <div>
    <PageHeader eyebrow="WORKSPACE / CONVERT" title="Convert SQL with confidence" description="A focused workspace for translating, validating, and reviewing SQL across twelve database dialects." actions={<><Button variant="ghost" icon={<Keyboard size={14} />} onClick={convert} disabled={!canConvert || loading || formatting}>⌘ Enter</Button><Button variant="secondary" icon={<RefreshCw size={14} />} onClick={() => { cancelPendingRequest(); setLoading(false); setFormatting(false); setSql(""); setResult(null); setError(null); removeDraft(); }}>New query</Button></>} />
    <div className="convert-toolbar"><div className="dialect-row"><DialectSelect label="Source dialect" value={source} onChange={(value) => { cancelPendingRequest(); setLoading(false); setFormatting(false); setDialects(value, target); setResult(null); setError(null); }} /><Button variant="ghost" icon={<ArrowLeftRight size={16} />} onClick={swap} aria-label="Swap source and target dialects">Swap</Button><DialectSelect label="Target dialect" value={target} onChange={(value) => { cancelPendingRequest(); setLoading(false); setFormatting(false); setDialects(source, value); setResult(null); setError(null); }} /></div><div className="convert-actions"><Button variant="secondary" loading={formatting} disabled={!sql.trim() || loading} onClick={format}>Format</Button><Button variant="primary" loading={loading} disabled={!canConvert || formatting} icon={<Wand2 size={15} />} onClick={convert}>Convert SQL</Button></div></div>
    {error && <ErrorPanel message={`${error.message}${error.code ? ` · ${error.code}` : ""}`} onRetry={() => void (lastAction === "format" ? format() : convert())} />}
    <div className="split-editor convert-editor"><div className="editor-panel"><div className="editor-head"><span><FileCode2 size={14} /> Source SQL</span><span className="editor-dialect">{source}</span></div><CodeEditor value={sql} onChange={(value) => { cancelPendingRequest(); setLoading(false); setFormatting(false); setSql(value); setResult((current) => current ? { ...current } : current); setError(null); }} minHeight={430} placeholder="Paste SQL here..." ariaLabel="Source SQL editor" /><div className="editor-footer"><span>{sql.length.toLocaleString()} chars</span><button className="link-button" onClick={() => { cancelPendingRequest(); setLoading(false); setFormatting(false); setSql(SAMPLE); setResult(null); setError(null); }}>Load example</button></div></div><div className="editor-panel"><div className="editor-head"><span><CheckCircle2 size={14} /> Target SQL</span><span className="editor-dialect">{target}</span></div>{output ? <pre className={`result-code ${stale ? "stale" : ""}`}>{output}</pre> : <EmptyState icon={<Wand2 size={20} />} title="Your converted SQL appears here" text="Choose dialects, paste a query, then run the conversion." action={<Button variant="secondary" onClick={convert} disabled={!canConvert}>Try conversion</Button>} />}<div className="editor-footer"><span>{stale ? "Result is stale — run again" : result ? `${result.target_validation_state} · ${result.transformations.length} transformations` : "Waiting for input"}</span><div className="result-actions"><CopyButton value={output} />{result?.success && output && <Button variant="ghost" onClick={() => { writeDiffHandoff({ sourceSql: sql, targetSql: output, sourceDialect: source, targetDialect: target }); navigate(`/diff?source=${source}&target=${target}`); }}>Open Diff</Button>}<DownloadButton value={output} /></div></div></div></div>
    {result && result.success && <div className="conversion-details"><Card><div className="card-header"><div><h2>Conversion report</h2><p className="card-subtitle">Review what changed before you use the result.</p></div><span className={`badge badge-${resultStatus}`}>{resultStatus === "success" ? "Validated" : "Review warnings"}</span></div><div className="metric-grid"><div className="metric"><span className="metric-label">Validation</span><div className="metric-value">{result.target_validation_state === "target_valid" ? "Ready" : "Review"}</div></div><div className="metric"><span className="metric-label">Transformations</span><div className="metric-value">{result.transformations.length}</div></div><div className="metric"><span className="metric-label">Warnings</span><div className="metric-value">{result.warnings.length}</div></div><div className="metric"><span className="metric-label">Notes</span><div className="metric-value">{result.compatibility_notes.length}</div></div></div>{(result.warnings.length || result.compatibility_notes.length) ? <div className="report-columns"><div><h3>Warnings</h3>{result.warnings.map((item) => <p className="report-item" key={item}>{item}</p>)}</div><div><h3>Compatibility notes</h3>{result.compatibility_notes.map((item) => <p className="report-item" key={item}>{item}</p>)}</div></div> : <p className="success-line"><CheckCircle2 size={15} /> No compatibility warnings for this conversion.</p>}</Card></div>}
  </div>;
}
