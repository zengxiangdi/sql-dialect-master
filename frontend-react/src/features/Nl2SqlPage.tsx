import { ArrowRight, BrainCircuit, Lightbulb, Send, Sparkles } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { clearHandoff, readDiffHandoff, writeDiffHandoff } from "../lib/handoff";
import { saveDraft } from "../lib/storage";
import type { Dialect, Nl2SqlResponse } from "../lib/types";
import { Button, Card, CodeEditor, DialectSelect, EmptyState, ErrorPanel, TextInput } from "../components/ui";
import { PageHeader } from "../components/PageHeader";

const examples = ["Find the top 10 customers by revenue", "查询最近 7 天的已支付订单", "统计每个部门的员工数量"];
export function Nl2SqlPage() {
  const navigate = useNavigate(); const [text, setText] = useState(""); const [dialect, setDialect] = useState<Dialect>("postgres"); const [table, setTable] = useState(""); const [columnHints, setColumnHints] = useState(""); const [result, setResult] = useState<Nl2SqlResponse | null>(null); const [error, setError] = useState<ApiError | null>(null); const [loading, setLoading] = useState(false); const pendingRequest = useRef<AbortController | null>(null);
  const cancelPendingRequest = useCallback(() => { pendingRequest.current?.abort(); }, []);
  const generate = useCallback(async () => {
    if (!text.trim()) return;
    cancelPendingRequest();
    const controller = new AbortController();
    pendingRequest.current = controller;
    setLoading(true); setError(null);
    try {
      const columns = columnHints.split(",").map((value) => value.trim()).filter(Boolean);
      const next = await api.nl2sql(text, dialect, table, columns, controller.signal);
      if (controller.signal.aborted) return;
      setResult(next);
      if (!next.success) setError(new ApiError(next.explanation || "Generation failed", 422));
    } catch (caught) {
      if (controller.signal.aborted) return;
      setError(caught instanceof ApiError ? caught : new ApiError("Generation failed", 500));
    } finally {
      if (pendingRequest.current === controller) { pendingRequest.current = null; setLoading(false); }
    }
  }, [cancelPendingRequest, columnHints, dialect, table, text]);
  useEffect(() => cancelPendingRequest, [cancelPendingRequest]);
  const resetInput = (update: () => void) => { cancelPendingRequest(); setLoading(false); update(); setResult(null); setError(null); };
  return <div><PageHeader eyebrow="WORKSPACE / NL2SQL" title="Turn intent into SQL" description="Describe the question in natural language. The engine returns a dialect-aware, evidence-backed query you can review before conversion." actions={<span className="surface-hint"><Sparkles size={14} /> No database required</span>} />
    <div className="nl-grid"><Card><div className="card-header"><div><h2>Describe your query</h2><p className="card-subtitle">Chinese and English are supported.</p></div><BrainCircuit size={22} className="card-icon" /></div><div className="example-list">{examples.map((example) => <button className="example-chip" key={example} onClick={() => resetInput(() => setText(example))}>{example}</button>)}</div><label className="field"><span className="field-label">Natural language</span><textarea className="nl-input" value={text} onChange={(event) => resetInput(() => setText(event.target.value))} placeholder="e.g. Show paid orders from the last 30 days..." /></label><div className="nl-options"><DialectSelect label="Target dialect" value={dialect} onChange={(value) => resetInput(() => setDialect(value))} /><label className="field"><span className="field-label">Table hint <small>optional</small></span><TextInput value={table} onChange={(event) => resetInput(() => setTable(event.target.value))} placeholder="orders" /></label><label className="field"><span className="field-label">Column hints <small>optional, comma separated</small></span><TextInput aria-label="Column hints" value={columnHints} onChange={(event) => resetInput(() => setColumnHints(event.target.value))} placeholder="orders.customer_id, orders.created_at" /></label></div>{error && <ErrorPanel message={error.message} onRetry={generate} />}<Button variant="primary" loading={loading} disabled={!text.trim()} icon={<Sparkles size={15} />} onClick={generate}>Generate SQL</Button></Card><Card className="nl-result-card"><div className="card-header"><div><h2>Generated result</h2><p className="card-subtitle">Review the query and its confidence before using it.</p></div>{result && <span className={`badge badge-${result.success ? "success" : "error"}`}>{result.success ? `${Math.round(result.confidence * 100)}% confidence` : "Needs review"}</span>}</div>{result?.sql ? <><CodeEditor value={result.sql} readOnly minHeight={310} ariaLabel="Generated SQL" /><div className="button-row"><Button variant="secondary" icon={<Send size={14} />} onClick={() => { clearHandoff("convert"); saveDraft(result.sql || ""); navigate("/convert"); }}>Use in Convert <ArrowRight size={13} /></Button><Button variant="secondary" onClick={() => { const existing = readDiffHandoff(); const targetDialect = existing?.targetDialect || (dialect === "postgres" ? "mysql" : "postgres"); writeDiffHandoff({ sourceSql: result.sql || "", targetSql: existing?.targetSql || "", sourceDialect: dialect, targetDialect }); navigate(`/diff?source=${dialect}&target=${targetDialect}`); }}>Use in Diff</Button></div><div className="explanation"><Lightbulb size={15} /><p>{result.explanation}</p></div>{result.evidence && <details><summary>Evidence and parameters</summary><pre className="json-block">{JSON.stringify({ evidence: result.evidence, parameters: result.parameters, parameter_style: result.parameter_style }, null, 2)}</pre></details>}</> : <EmptyState icon={<BrainCircuit size={20} />} title="Nothing generated yet" text="Choose an example or describe your own question" />}</Card></div>
  </div>;
}
