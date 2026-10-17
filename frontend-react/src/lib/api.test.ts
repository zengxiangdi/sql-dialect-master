import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

describe("API client request lifecycle", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("sends a middleware-compatible UUID and forwards a caller signal", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers(),
      json: async () => ({ success: true, dialect: "postgres", elements: {} }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await api.parse("SELECT 1", "postgres", controller.signal);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/parse");
    expect(init.signal).toBeInstanceOf(AbortSignal);
    expect((init.headers as Headers).get("X-Request-ID")).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
  });

  it("propagates caller cancellation without converting it into an API error", async () => {
    const fetchMock = vi.fn((_url: string, init: RequestInit) => new Promise<never>((_resolve, reject) => {
      init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    }));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    const request = api.parse("SELECT 1", "postgres", controller.signal);
    controller.abort();

    await expect(request).rejects.toMatchObject({ name: "AbortError" });
  });

  it("sends optional NL2SQL column hints as an array", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers(),
      json: async () => ({ success: true, input_text: "count orders", sql: "SELECT COUNT(*) FROM orders", dialect: "postgres", explanation: "", confidence: 1, suggestions: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await api.nl2sql("count orders", "postgres", "orders", ["orders.id", "orders.created_at"]);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      text: "count orders",
      dialect: "postgres",
      table_hint: "orders",
      column_hints: ["orders.id", "orders.created_at"],
    });
  });

  it("keeps the previous NL2SQL signal argument and empty-hints contract", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers(),
      json: async () => ({ success: true }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await api.nl2sql("list orders", "postgres", "orders", controller.signal);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.signal).toBeInstanceOf(AbortSignal);
    expect(JSON.parse(String(init.body))).toMatchObject({ column_hints: null });
  });
});
