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
});
