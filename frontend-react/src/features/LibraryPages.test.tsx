import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FunctionsPage } from "./LibraryPages";

describe("function library metadata", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("uses categories returned by the API", async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string) => ({
      ok: true,
      status: 200,
      headers: new Headers(),
      json: async () => url === "/api/functions/categories"
        ? { success: true, categories: [{ name: "experimental", count: 2, description: "New functions", icon: "✨" }], count: 1 }
        : { success: true, functions: [], count: 0, total: 0 },
    }));
    vi.stubGlobal("fetch", fetchMock);

    render(<FunctionsPage />);

    await waitFor(() => expect(screen.getByRole("option", { name: "experimental" })).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith("/api/functions/categories", expect.objectContaining({ signal: expect.any(AbortSignal), headers: expect.any(Headers) }));
  });
});
