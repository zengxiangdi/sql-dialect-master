import type { HistoryItem } from "./types";

export const HISTORY_STORAGE_KEY = "sdm.history";
export const DRAFT_STORAGE_KEY = "sdm.convert.draft";
export const HISTORY_MAX_ITEMS = 50;
export const HISTORY_MAX_SERIALIZED_BYTES = 1_500_000;
export const SQL_PREVIEW_MAX_CHARS = 20_000;
// This matches the backend's maximum accepted SQL input. Draft persistence
// does not truncate values: keeping the full active editor value avoids losing
// user input silently. The API still reports its normal validation error for
// requests above this limit.
export const DRAFT_MAX_CHARS = 100_000;

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function safeGetItem(key: string): string | null {
  try {
    return storage()?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

export function safeSetItem(key: string, value: string): boolean {
  try {
    const target = storage();
    if (!target) return false;
    target.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

export function safeRemoveItem(key: string): boolean {
  try {
    const target = storage();
    if (!target) return false;
    target.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

export function safeGetJson<T>(key: string, fallback: T): T {
  const raw = safeGetItem(key);
  if (raw === null) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function safeSetJson(key: string, value: unknown): boolean {
  try {
    return safeSetItem(key, JSON.stringify(value));
  } catch {
    return false;
  }
}

export function serializedByteLength(value: string): number {
  try {
    return typeof TextEncoder === "undefined"
      ? value.length * 2
      : new TextEncoder().encode(value).length;
  } catch {
    return value.length * 2;
  }
}

function previewSql(value: string): { value: string; truncated: boolean } {
  return value.length > SQL_PREVIEW_MAX_CHARS
    ? { value: value.slice(0, SQL_PREVIEW_MAX_CHARS), truncated: true }
    : { value, truncated: false };
}

/** Normalize persisted history before it enters React state or storage. */
export function normalizeHistory(items: HistoryItem[]): HistoryItem[] {
  const normalized = items.slice(0, HISTORY_MAX_ITEMS).map((item) => {
    const source = previewSql(item.source);
    const target = previewSql(item.target);
    const truncated = Boolean(item.truncated || source.truncated || target.truncated);
    return {
      ...item,
      source: source.value,
      target: target.value,
      ...(truncated ? { truncated: true } : {}),
    };
  });

  const kept: HistoryItem[] = [];
  for (const item of normalized) {
    const candidate = JSON.stringify([...kept, item]);
    if (serializedByteLength(candidate) > HISTORY_MAX_SERIALIZED_BYTES) break;
    kept.push(item);
  }
  return kept;
}

export function readDraft(): string {
  return safeGetItem(DRAFT_STORAGE_KEY) || "";
}

export function saveDraft(value: string): boolean {
  return safeSetItem(DRAFT_STORAGE_KEY, value);
}

export function removeDraft(): boolean {
  return safeRemoveItem(DRAFT_STORAGE_KEY);
}
