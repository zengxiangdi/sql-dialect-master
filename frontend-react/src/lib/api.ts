import type { ConvertResponse, Dialect, DialectsResponse, DiffResponse, FunctionCategory, FunctionDetailResponse, FunctionItem, Nl2SqlResponse, ParseResponse, TypeMappingsResponse } from "./types";
import { safeGetItem } from "./storage";

export class ApiError extends Error {
  status: number;
  code?: string;
  retryAfter?: string;

  constructor(message: string, status: number, code?: string, retryAfter?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
  }
}

/** Keep the request ID in the RFC 4122 format expected by the API middleware. */
const requestId = () => {
  const random = typeof globalThis.crypto !== "undefined" ? globalThis.crypto : undefined;
  if (typeof random?.randomUUID === "function") return random.randomUUID();
  const bytes = new Uint8Array(16);
  if (typeof random?.getRandomValues === "function") random.getRandomValues(bytes);
  else for (let index = 0; index < bytes.length; index += 1) bytes[index] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
};

export const apiBase = () => (safeGetItem("sdm.apiBase")?.trim() || import.meta.env.VITE_API_BASE_URL?.trim() || "").replace(/\/+$/, "");

async function request<T>(path: string, init: RequestInit = {}, timeout = 30000): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = window.setTimeout(() => { timedOut = true; controller.abort(); }, timeout);
  const apiKey = safeGetItem("sdm.apiKey");
  const headers = new Headers(init.headers);
  let removeCallerAbortListener: (() => void) | undefined;
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  headers.set("X-Request-ID", requestId());
  if (apiKey) headers.set("X-API-Key", apiKey);
  try {
    // Preserve a caller's signal while still enforcing the client timeout. This
    // lets search/filter pages cancel stale requests when inputs change.
    const signal = init.signal;
    if (signal) {
      if (signal.aborted) controller.abort(signal.reason);
      else {
        const onAbort = () => controller.abort(signal.reason);
        signal.addEventListener("abort", onAbort, { once: true });
        removeCallerAbortListener = () => signal.removeEventListener("abort", onAbort);
      }
    }
    const response = await fetch(`${apiBase()}${path}`, { ...init, headers, signal: controller.signal });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = payload?.error?.message || payload?.detail || payload?.error || `Request failed (${response.status})`;
      // FastAPI's normalized error envelope uses `error.code`; older API
      // versions used `error_code`, so accept both while migrating clients.
      const errorCode = payload?.error?.code ?? payload?.error?.error_code;
      throw new ApiError(String(detail), response.status, errorCode == null ? undefined : String(errorCode), response.headers.get("Retry-After") ?? undefined);
    }
    return payload as T;
  } catch (error) {
    if (((error instanceof DOMException && error.name === "AbortError") || (error instanceof Error && error.name === "AbortError")) && timedOut) throw new ApiError("Request timed out. Try again.", 504);
    if (error instanceof TypeError) throw new ApiError("Unable to reach the API. Check the backend URL.", 0);
    throw error;
  } finally {
    removeCallerAbortListener?.();
    window.clearTimeout(timer);
  }
}

export const api = {
  dialects: () => request<DialectsResponse>("/api/dialects"),
  convert: (sql: string, source_dialect: Dialect, target_dialect: Dialect, pretty = true, signal?: AbortSignal) =>
    request<ConvertResponse>("/api/convert", { method: "POST", body: JSON.stringify({ sql, source_dialect, target_dialect, pretty }), signal }),
  nl2sql: (text: string, dialect: Dialect, table_hint?: string, column_hintsOrSignal?: string[] | AbortSignal, signal?: AbortSignal) => {
    // Keep the previous fourth-argument AbortSignal form working for callers
    // that do not provide column hints yet.
    const column_hints = Array.isArray(column_hintsOrSignal) ? column_hintsOrSignal : undefined;
    const requestSignal = Array.isArray(column_hintsOrSignal)
      ? signal
      : column_hintsOrSignal ?? signal;
    return request<Nl2SqlResponse>("/api/nl2sql", { method: "POST", body: JSON.stringify({ text, dialect, table_hint: table_hint || null, column_hints: column_hints?.length ? column_hints : null }), signal: requestSignal });
  },
  parse: (sql: string, dialect: Dialect, signal?: AbortSignal) =>
    request<ParseResponse>("/api/parse", { method: "POST", body: JSON.stringify({ sql, dialect }), signal }),
  diff: (source_sql: string, target_sql: string, source_dialect: Dialect, target_dialect: Dialect, signal?: AbortSignal) =>
    request<DiffResponse>("/api/diff", { method: "POST", body: JSON.stringify({ source_sql, target_sql, source_dialect, target_dialect }), signal }),
  functions: (search = "", category = "", limit = 100, signal?: AbortSignal) =>
    request<{ functions: FunctionItem[]; count: number; total: number }>(`/api/functions?limit=${limit}${search ? `&search=${encodeURIComponent(search)}` : ""}${category ? `&category=${encodeURIComponent(category)}` : ""}`, { signal }),
  functionDetail: (name: string, signal?: AbortSignal) =>
    request<FunctionDetailResponse>(`/api/functions/${encodeURIComponent(name)}`, { signal }),
  functionCategories: (signal?: AbortSignal) =>
    request<{ categories: FunctionCategory[]; count: number }>("/api/functions/categories", { signal }),
  types: (source?: Dialect, target?: Dialect, signal?: AbortSignal) =>
    request<TypeMappingsResponse>(`/api/types${source || target ? `?${source ? `source=${source}` : ""}${source && target ? "&" : ""}${target ? `target=${target}` : ""}` : ""}`, { signal }),
  health: (signal?: AbortSignal) => request<{ status: string; version: string }>("/health", { signal }, 5000),
};
