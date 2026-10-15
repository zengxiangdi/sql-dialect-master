import type { ConvertResponse, Dialect, DialectsResponse, FunctionItem, Nl2SqlResponse, ParseResponse, TypeMapping } from "./types";

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

const requestId = () => `web-${crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`}`;

export const apiBase = () => (localStorage.getItem("sdm.apiBase") || import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

async function request<T>(path: string, init: RequestInit = {}, timeout = 30000): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeout);
  const apiKey = localStorage.getItem("sdm.apiKey");
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  headers.set("X-Request-ID", requestId());
  if (apiKey) headers.set("X-API-Key", apiKey);
  try {
    const response = await fetch(`${apiBase()}${path}`, { ...init, headers, signal: controller.signal });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = payload?.error?.message || payload?.detail || payload?.error || `Request failed (${response.status})`;
      throw new ApiError(String(detail), response.status, payload?.error?.error_code, response.headers.get("Retry-After") ?? undefined);
    }
    return payload as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw new ApiError("Request timed out. Try again.", 504);
    if (error instanceof TypeError) throw new ApiError("Unable to reach the API. Check the backend URL.", 0);
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

export const api = {
  dialects: () => request<DialectsResponse>("/api/dialects"),
  convert: (sql: string, source_dialect: Dialect, target_dialect: Dialect, pretty = true) =>
    request<ConvertResponse>("/api/convert", { method: "POST", body: JSON.stringify({ sql, source_dialect, target_dialect, pretty }) }),
  nl2sql: (text: string, dialect: Dialect, table_hint?: string) =>
    request<Nl2SqlResponse>("/api/nl2sql", { method: "POST", body: JSON.stringify({ text, dialect, table_hint: table_hint || null }) }),
  parse: (sql: string, dialect: Dialect) =>
    request<ParseResponse>("/api/parse", { method: "POST", body: JSON.stringify({ sql, dialect }) }),
  functions: (search = "", category = "", limit = 100) =>
    request<{ functions: FunctionItem[]; count: number; total: number }>(`/api/functions?limit=${limit}${search ? `&search=${encodeURIComponent(search)}` : ""}${category ? `&category=${encodeURIComponent(category)}` : ""}`),
  types: (source?: Dialect, target?: Dialect) => request<{ mappings: TypeMapping[]; type_count: number }>(`/api/types${source || target ? `?${source ? `source=${source}` : ""}${source && target ? "&" : ""}${target ? `target=${target}` : ""}` : ""}`),
  health: () => request<{ status: string; version: string }>("/health", {}, 5000),
};
