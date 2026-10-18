import { Check, ChevronDown, Copy, Download, Loader2, RotateCcw, Sparkles, X } from "lucide-react";
import { useState, type ButtonHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from "react";
import type { Dialect, Status } from "../lib/types";
import { DIALECT_ICONS, DIALECT_LABELS } from "../lib/types";

export function Button({ variant = "secondary", loading, icon, children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger"; loading?: boolean; icon?: ReactNode }) {
  return <button className={`button button-${variant}`} disabled={props.disabled || loading} aria-busy={loading || undefined} {...props}>{loading ? <Loader2 size={15} className="spin" aria-hidden="true" /> : icon}{children}</button>;
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

export function CopyButton({ value, disabled = false, title }: { value: string; disabled?: boolean; title?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(value);
      else {
        const area = document.createElement("textarea");
        area.value = value; area.setAttribute("readonly", ""); area.style.position = "fixed"; area.style.opacity = "0";
        document.body.appendChild(area); area.select(); document.execCommand("copy"); area.remove();
      }
      setCopied(true); window.setTimeout(() => setCopied(false), 1500);
    } catch { setCopied(false); }
  };
  return <Button variant="ghost" icon={copied ? <Check size={14} /> : <Copy size={14} />} onClick={copy} disabled={disabled || !value} title={title}>{copied ? "Copied" : "Copy"}</Button>;
}

export function DownloadButton({ value, filename = "converted.sql" }: { value: string; filename?: string }) {
  const download = () => { const url = URL.createObjectURL(new Blob([value], { type: "text/plain;charset=utf-8" })); const anchor = document.createElement("a"); anchor.href = url; anchor.download = filename; document.body.appendChild(anchor); anchor.click(); anchor.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 0); };
  return <Button variant="ghost" icon={<Download size={14} />} onClick={download} disabled={!value}>Download</Button>;
}

export function EmptyState({ icon = <Sparkles size={22} />, title, text, action }: { icon?: ReactNode; title: string; text: string; action?: ReactNode }) {
  return <div className="empty-state"><div className="empty-icon">{icon}</div><h3>{title}</h3><p>{text}</p>{action}</div>;
}

export function ErrorPanel({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return <div className="error-panel" role="alert" aria-live="assertive"><div><strong>Something needs attention</strong><p>{message}</p></div>{onRetry && <Button variant="ghost" icon={<RotateCcw size={14} />} onClick={onRetry}>Retry</Button>}<X size={16} className="error-mark" aria-hidden="true" /></div>;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return <label className="field"><span className="field-label">{label}</span>{children}{hint && <span className="field-hint">{hint}</span>}</label>;
}

export function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) { return <input className="text-input" {...props} />; }
