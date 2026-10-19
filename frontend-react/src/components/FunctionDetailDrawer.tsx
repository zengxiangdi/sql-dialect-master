import { X } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { api, ApiError } from "../lib/api";
import { ALL_DIALECTS, DIALECT_LABELS, type Dialect, type FunctionDetailResponse } from "../lib/types";
import { EmptyState, ErrorPanel } from "./ui";

interface FunctionDetailDrawerProps {
  name: string | null;
  onClose: () => void;
}

export function FunctionDetailDrawer({ name, onClose }: FunctionDetailDrawerProps) {
  return name ? <OpenFunctionDetailDrawer key={name} name={name} onClose={onClose} /> : null;
}

function OpenFunctionDetailDrawer({ name, onClose }: { name: string; onClose: () => void }) {
  const [data, setData] = useState<FunctionDetailResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloadToken, setReloadToken] = useState(0);
  const titleId = useId();
  const panelRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    return () => {
      document.body.style.overflow = overflow;
      if (trigger?.isConnected) trigger.focus();
    };
  }, []);

  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onClose();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api.functionDetail(name, controller.signal)
      .then((response) => { if (!controller.signal.aborted) setData(response); })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof ApiError ? reason : new ApiError("Unable to load function details", 0));
        }
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [name, reloadToken]);

  const trapFocus = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Tab") return;
    const controls = panelRef.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex="0"]',
    );
    if (!controls?.length) return;
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const detail = data?.function;
  const comparison = data?.comparison;
  const parameters = detail?.parameters ?? comparison?.parameters ?? [];
  const examples = Object.entries(detail?.examples ?? comparison?.examples ?? {});
  const notes = detail?.notes ?? comparison?.notes;

  return createPortal(
    <div className="function-detail-overlay" data-testid="function-detail-backdrop" onClick={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section ref={panelRef} className="function-detail-drawer" role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={trapFocus}>
        <header className="function-detail-header">
          <div><h2 id={titleId}>{name}</h2>{detail && !loading && !error && <span className="muted">{detail.category}</span>}</div>
          <button ref={closeRef} type="button" className="icon-button" aria-label="Close function details" onClick={onClose}><X size={18} aria-hidden="true" /></button>
        </header>
        <div className="function-detail-content">
          {loading ? <div className="loading-line" role="status">Loading function details…</div> : error ? (
            <ErrorPanel message={error.message} onRetry={() => { closeRef.current?.focus(); setReloadToken((value) => value + 1); }} />
          ) : detail && comparison && <>
            {(detail.description || comparison.description) && <p className="function-detail-description">{detail.description || comparison.description}</p>}
            <section aria-label="Function parameters">
              <h3>Parameters</h3>
              {parameters.length ? <div className="table-wrap"><table>
                <caption className="sr-only">{name} parameters</caption>
                <thead><tr><th scope="col">Name</th><th scope="col">Type</th><th scope="col">Required</th><th scope="col">Description</th></tr></thead>
                <tbody>{parameters.map((parameter, index) => <tr key={`${parameter.name}-${index}`}>
                  <th scope="row" className="mono">{parameter.name}</th><td className="mono">{parameter.type}</td><td>{parameter.required ? "Yes" : "No"}</td><td>{parameter.description}</td>
                </tr>)}</tbody>
              </table></div> : <EmptyState title="No parameters" text="No parameter information is available for this function." />}
            </section>
            <section aria-label="Dialect comparison">
              <h3>Dialect syntax</h3>
              <div className="table-wrap"><table>
                <caption className="sr-only">{name} syntax across 12 dialects</caption>
                <thead><tr><th scope="col">Dialect</th><th scope="col">Syntax</th></tr></thead>
                <tbody>{ALL_DIALECTS.map((dialect) => <tr key={dialect}>
                  <th scope="row">{DIALECT_LABELS[dialect]}</th><td className="mono">{comparison.dialects[dialect] || detail.dialects[dialect] || "N/A"}</td>
                </tr>)}</tbody>
              </table></div>
            </section>
            {!!examples.length && <section aria-label="Function examples"><h3>Examples</h3>{examples.map(([label, example]) => <div className="function-detail-example" key={label}>
              <h4>{DIALECT_LABELS[label as Dialect] || label}</h4><pre>{example}</pre>
            </div>)}</section>}
            {notes && <section aria-label="Function notes"><h3>Notes</h3><p>{notes}</p></section>}
          </>}
        </div>
      </section>
    </div>,
    document.body,
  );
}
