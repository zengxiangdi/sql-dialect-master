import { Check, ChevronDown, Copy, Download, Loader2, RotateCcw, Sparkles, X } from "lucide-react";
import { useState, type ButtonHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from "react";
import type { Dialect, Status } from "../lib/types";
import { DIALECT_ICONS, DIALECT_LABELS } from "../lib/types";

export function Button({ variant = "secondary", loading, icon, children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger"; loading?: boolean; icon?: ReactNode }) {
  return <button className={`button button-${variant}`} disabled={props.disabled || loading} {...props}>{loading ? <Loader2 size={15} className="spin" /> : icon}{children}</button>;
}

export function IconButton({ label, children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return <button className="icon-button" aria-label={label} title={label} {...props}>{children}</button>;
}

export function Card({ children, className = "", ...props }: { children: ReactNode; className?: string } & React.HTMLAttributes<HTMLDivElement>) {
  return <section className={`card ${className}`} {...props}>{children}</section>;
}

export function Badge({ status = "neutral", children }: { status?: Status; children: ReactNode }) {
  return <span className={`badge badge-${status}`}><span className="status-dot" />{children}</span>;
}

export function DialectSelect({ value, onChange, label, compact = false, options }: { value: Dialect; onChange: (value: Dialect) => void; label?: string; compact?: boolean; options?: Dialect[] }) {
  return <label className={`dialect-select ${compact ? "compact" : ""}`}>{label && <span className="field-label">{label}</span>}<span className="select-wrap"><span className="dialect-icon">{DIALECT_ICONS[value]}</span><select value={value} onChange={(event) => onChange(event.target.value as Dialect)}>{(options || Object.keys(DIALECT_LABELS) as Dialect[]).map((dialect) => <option key={dialect} value={dialect}>{DIALECT_LABELS[dialect]}</option>)}</select><ChevronDown size={14} /></span></label>;
}

export function CodeEditor({ value, onChange, placeholder, className = "", readOnly = false, minHeight = 300, ariaLabel }: Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "value" | "onChange"> & { value: string; onChange?: (value: string) => void; minHeight?: number; ariaLabel?: string }) {
  return <textarea aria-label={ariaLabel || "SQL editor"} className={`code-editor ${className}`} style={{ minHeight }} value={value} onChange={(event) => onChange?.(event.target.value)} placeholder={placeholder} readOnly={readOnly} spellCheck={false} />;
}

export function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => { await navigator.clipboard.writeText(value); setCopied(true); window.setTimeout(() => setCopied(false), 1500); };
  return <Button variant="ghost" icon={copied ? <Check size={14} /> : <Copy size={14} />} onClick={copy} disabled={!value}>{copied ? "Copied" : "Copy"}</Button>;
}

export function DownloadButton({ value, filename = "converted.sql" }: { value: string; filename?: string }) {
  const download = () => { const url = URL.createObjectURL(new Blob([value], { type: "text/plain" })); const anchor = document.createElement("a"); anchor.href = url; anchor.download = filename; anchor.click(); URL.revokeObjectURL(url); };
  return <Button variant="ghost" icon={<Download size={14} />} onClick={download} disabled={!value}>Download</Button>;
}

export function EmptyState({ icon = <Sparkles size={22} />, title, text, action }: { icon?: ReactNode; title: string; text: string; action?: ReactNode }) {
  return <div className="empty-state"><div className="empty-icon">{icon}</div><h3>{title}</h3><p>{text}</p>{action}</div>;
}

export function ErrorPanel({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return <div className="error-panel"><div><strong>Something needs attention</strong><p>{message}</p></div>{onRetry && <Button variant="ghost" icon={<RotateCcw size={14} />} onClick={onRetry}>Retry</Button>}<X size={16} className="error-mark" /></div>;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return <label className="field"><span className="field-label">{label}</span>{children}{hint && <span className="field-hint">{hint}</span>}</label>;
}

export function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) { return <input className="text-input" {...props} />; }
