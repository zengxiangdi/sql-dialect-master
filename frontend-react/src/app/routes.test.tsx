import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppRoutes } from "./routes";
import { AppProvider } from "../lib/app-context";

describe("React workspace shell", () => {
  afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); });
  it("renders the Convert workspace with keyboard command affordance", () => {
    render(<MemoryRouter initialEntries={["/convert"]}><AppProvider><AppRoutes /></AppProvider></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "Convert SQL with confidence" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /jump to anything/i })).toBeInTheDocument();
    expect(screen.getByLabelText("Source SQL editor")).toBeInTheDocument();
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
});
