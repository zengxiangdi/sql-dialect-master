import { afterEach, describe, expect, it, vi } from "vitest";
import type { HistoryItem } from "./types";
import {
  DRAFT_MAX_CHARS,
  HISTORY_MAX_SERIALIZED_BYTES,
  SQL_PREVIEW_MAX_CHARS,
  normalizeHistory,
  safeGetItem,
  safeGetJson,
  safeRemoveItem,
  safeSetItem,
  readDraft,
  saveDraft,
  serializedByteLength,
} from "./storage";

describe("safe browser storage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("catches storage read, write, and remove failures", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    expect(safeGetItem("sdm.test")).toBeNull();

    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("full", "QuotaExceededError");
    });
    expect(safeSetItem("sdm.test", "value")).toBe(false);

    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    expect(safeRemoveItem("sdm.test")).toBe(false);
  });

  it("uses a fallback when JSON is malformed or storage reads throw", () => {
    localStorage.setItem("sdm.test", "{");
    expect(safeGetJson("sdm.test", { fallback: true })).toEqual({ fallback: true });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage unavailable");
    });
    expect(safeGetJson("sdm.test", [])).toEqual([]);
  });

  it("truncates SQL previews and evicts oldest entries by serialized budget", () => {
    const items = Array.from({ length: 50 }, (_, index) => ({
      id: `history-${index}`,
      source: `SELECT ${"s".repeat(SQL_PREVIEW_MAX_CHARS)} ${index}`,
      target: `SELECT ${"t".repeat(SQL_PREVIEW_MAX_CHARS)} ${index}`,
      sourceDialect: "mysql" as const,
      targetDialect: "postgres" as const,
      createdAt: new Date().toISOString(),
      status: "success" as const,
      favorite: index % 2 === 0,
    }));

    const normalized = normalizeHistory(items);
    expect(normalized[0].truncated).toBe(true);
    expect(normalized[0].source).toHaveLength(SQL_PREVIEW_MAX_CHARS);
    expect(normalized.length).toBeLessThan(items.length);
    expect(normalized.map((item) => item.favorite)).toEqual(
      items.slice(0, normalized.length).map((item) => item.favorite),
    );
    expect(serializedByteLength(JSON.stringify(normalized))).toBeLessThanOrEqual(
      HISTORY_MAX_SERIALIZED_BYTES,
    );
  });

  it("round-trips active drafts without silently truncating them", () => {
    const draft = "x".repeat(50_000);
    expect(saveDraft(draft)).toBe(true);
    expect(readDraft()).toBe(draft);

    const oversizedDraft = "y".repeat(DRAFT_MAX_CHARS + 1);
    expect(saveDraft(oversizedDraft)).toBe(true);
    expect(readDraft()).toBe(oversizedDraft);
  });

  it.each([true, false, undefined])("preserves favorite=%s while normalizing history", (favorite) => {
    const item: HistoryItem = {
      id: "favorite-history",
      source: "SELECT id FROM users",
      target: "SELECT id FROM users",
      sourceDialect: "mysql",
      targetDialect: "postgres",
      createdAt: "2026-10-21T00:00:00Z",
      status: "success",
      ...(favorite === undefined ? {} : { favorite }),
    };

    const [normalized] = normalizeHistory([item]);

    expect(normalized).toEqual(item);
    expect(normalized.favorite).toBe(favorite);
  });

  it.each([true, false])("preserves favorite=%s when SQL is truncated", (favorite) => {
    const item: HistoryItem = {
      id: "truncated-favorite-history",
      source: "s".repeat(SQL_PREVIEW_MAX_CHARS + 1),
      target: "t".repeat(SQL_PREVIEW_MAX_CHARS + 1),
      sourceDialect: "mysql",
      targetDialect: "postgres",
      createdAt: "2026-10-21T00:00:00Z",
      status: "success",
      favorite,
    };

    const [normalized] = normalizeHistory([item]);

    expect(normalized.source).toHaveLength(SQL_PREVIEW_MAX_CHARS);
    expect(normalized.target).toHaveLength(SQL_PREVIEW_MAX_CHARS);
    expect(normalized.truncated).toBe(true);
    expect(normalized.favorite).toBe(favorite);
  });
});
