import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppRoutes } from "./routes";
import { AppProvider } from "../lib/app-context";

describe("React workspace shell", () => {
  afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
  it("renders the Convert workspace with keyboard command affordance", () => {
    render(<MemoryRouter initialEntries={["/convert"]}><AppProvider><AppRoutes /></AppProvider></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "Convert SQL with confidence" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /jump to anything/i })).toBeInTheDocument();
    expect(screen.getByLabelText("Source SQL editor")).toBeInTheDocument();
    expect(screen.getByText("v1.1.9")).toBeInTheDocument();
  });

  it("clears history in memory as well as local storage", () => {
    localStorage.setItem("sdm.history", JSON.stringify([{
      id: "history-1", source: "SELECT 1", target: "SELECT 1", sourceDialect: "mysql", targetDialect: "postgres",
      createdAt: new Date().toISOString(), status: "success",
    }]));
    render(<MemoryRouter initialEntries={["/history"]}><AppProvider><AppRoutes /></AppProvider></MemoryRouter>);
    expect(screen.getByText(/mysql/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /clear local history/i }));
    expect(screen.getByText("No local history yet")).toBeInTheDocument();
    expect(localStorage.getItem("sdm.history")).toBe("[]");
  });

  it("ignores malformed persisted history entries", () => {
    localStorage.setItem("sdm.history", JSON.stringify([{ source: null }, { id: "missing-status" }]));
    render(<MemoryRouter initialEntries={["/history"]}><AppProvider><AppRoutes /></AppProvider></MemoryRouter>);
    expect(screen.getByText("No local history yet")).toBeInTheDocument();
  });

  it("keeps rendering and clearing history when persistence hits a quota error", () => {
    localStorage.setItem("sdm.history", JSON.stringify([{
      id: "history-quota", source: "SELECT 1", target: "SELECT 1", sourceDialect: "mysql", targetDialect: "postgres",
      createdAt: new Date().toISOString(), status: "success",
    }]));
    const originalSetItem = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (this: Storage, key, value) {
      if (key === "sdm.history") throw new DOMException("full", "QuotaExceededError");
      return originalSetItem.call(this, key, value);
    });
    render(<MemoryRouter initialEntries={["/history"]}><AppProvider><AppRoutes /></AppProvider></MemoryRouter>);
    expect(screen.getByText(/mysql/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /clear local history/i }));
    expect(screen.getByText("No local history yet")).toBeInTheDocument();
  });

  it("uses defaults when localStorage reads throw", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    render(<MemoryRouter initialEntries={["/convert"]}><AppProvider><AppRoutes /></AppProvider></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "Convert SQL with confidence" })).toBeInTheDocument();
    expect((screen.getByLabelText("Source SQL editor") as HTMLTextAreaElement).value).toContain("customer_id");
  });

  it("disables copying history entries whose SQL was truncated", () => {
    localStorage.setItem("sdm.history", JSON.stringify([{
      id: "history-truncated", source: "SELECT " + "s".repeat(20_000), target: "SELECT " + "t".repeat(20_000),
      sourceDialect: "mysql", targetDialect: "postgres", createdAt: new Date().toISOString(), status: "success", truncated: true,
    }]));
    render(<MemoryRouter initialEntries={["/history"]}><AppProvider><AppRoutes /></AppProvider></MemoryRouter>);
    expect(screen.getByText("Preview truncated; actions disabled")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy" })).toBeDisabled();
  });

  it("rechecks API health when the document becomes visible", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers(),
      json: async () => ({ status: "alive", version: "1.1.4" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter initialEntries={["/convert"]}><AppProvider><AppRoutes /></AppProvider></MemoryRouter>);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const initialCalls = fetchMock.mock.calls.length;
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    fireEvent(document, new Event("visibilitychange"));
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(initialCalls));
  });

  it("renders equivalent and different semantic diff responses", async () => {
    let status: "equivalent" | "different" = "equivalent";
    const fetchMock = vi.fn().mockImplementation(async (url: string) => ({
      ok: true,
      status: 200,
      headers: new Headers(),
      json: async () => url === "/health"
        ? { status: "alive", version: "1.1.4" }
        : {
          success: true,
          status,
          equivalent: status === "equivalent",
          differences: status === "different" ? ["Canonical AST SQL differs"] : [],
          difference_categories: status === "different" ? ["projection"] : [],
          structured_differences: status === "different" ? [{ category: "projection", severity: "warning", source_fragment: "id", target_fragment: "name", explanation: "Projection changed", confidence: 0.7 }] : [],
          confidence: status === "equivalent" ? 0.95 : 0.7,
        },
    }));
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter initialEntries={["/diff"]}><AppProvider><AppRoutes /></AppProvider></MemoryRouter>);
    await waitFor(() => expect(screen.getByRole("button", { name: "Compare" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Compare" }));
    await waitFor(() => expect(screen.getByText("Statements are semantically equivalent")).toBeInTheDocument());
    status = "different";
    fireEvent.change(screen.getByLabelText("Target SQL editor"), { target: { value: "SELECT name FROM users" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare" }));
    await waitFor(() => expect(screen.getByText("Semantic status: different")).toBeInTheDocument());
    expect(screen.getByText("projection · warning")).toBeInTheDocument();
  });
});
