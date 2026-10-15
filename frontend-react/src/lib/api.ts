import type { ConvertResponse, Dialect, DialectsResponse, FunctionItem, Nl2SqlResponse, ParseResponse, TypeMapping, TypeMappingsResponse } from "./types";

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

export const apiBase = () => (localStorage.getItem("sdm.apiBase")?.trim() || import.meta.env.VITE_API_BASE_URL?.trim() || "").replace(/\/+$/, "");

/**
 * The API intentionally keeps the type matrix keyed by canonical type name
 * for Python clients.  The React table needs a stable iterable, though, and
 * older deployments may already return an array.  Normalize both contracts
 * at this boundary so a server upgrade cannot turn the Types page into a
 * runtime `.map is not a function` error.
 */
export function normalizeTypeMappings(payload: {
  mappings?: unknown;
  [key: string]: unknown;
}): TypeMappingsResponse {
  const raw = payload.mappings;
  let mappings: TypeMapping[];
  if (Array.isArray(raw)) {
    mappings = raw.filter((item): item is TypeMapping => Boolean(item && typeof item === "object"));
  } else if (raw && typeof raw === "object") {
    mappings = Object.entries(raw).map(([type, value]) => ({
      ...(value && typeof value === "object" ? value : {}),
      type: type,
      type_name: type,
      canonical_type: type,
    } as TypeMapping));
  } else {
    mappings = [];
  }
  return {
    ...payload,
    mappings,
    type_count: typeof payload.type_count === "number" ? payload.type_count : mappings.length,
  } as TypeMappingsResponse;
}

async function request<T>(path: string, init: RequestInit = {}, timeout = 30000): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeout);
  const apiKey = localStorage.getItem("sdm.apiKey");
  const headers = new Headers(init.headers);
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  headers.set("X-Request-ID", requestId());
  if (apiKey) headers.set("X-API-Key", apiKey);
  try {
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
    if ((error instanceof DOMException && error.name === "AbortError") || (error instanceof Error && error.name === "AbortError")) throw new ApiError("Request timed out. Try again.", 504);
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
  types: async (source?: Dialect, target?: Dialect) => normalizeTypeMappings(await request<{ mappings?: unknown; [key: string]: unknown }>(`/api/types${source || target ? `?${source ? `source=${source}` : ""}${source && target ? "&" : ""}${target ? `target=${target}` : ""}` : ""}`)),
  health: () => request<{ status: string; version: string }>("/health", {}, 5000),
};
