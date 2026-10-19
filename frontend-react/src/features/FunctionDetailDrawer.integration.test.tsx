import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FunctionDetailDrawer } from "../components/FunctionDetailDrawer";
import { AppProvider } from "../lib/app-context";
import { ALL_DIALECTS, DIALECT_LABELS } from "../lib/types";
import { FunctionsPage } from "./LibraryPages";

function response(payload: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, headers: new Headers(), json: async () => payload };
}

function detail(name = "CONCAT", parameters = [{ name: "str1", type: "string", required: true, description: "First string to concatenate" }]) {
  const value = {
    name,
    category: "string",
    description: "Concatenate strings into one value",
    parameters,
    dialects: { mysql: "CONCAT(str1, str2)", postgres: "str1 || str2" },
    examples: { mysql: "SELECT CONCAT('hello', ' world');" },
    notes: "NULL handling varies across dialects.",
  };
  return {
    success: true,
    function: value,
    comparison: {
      ...value,
      dialects: Object.fromEntries(ALL_DIALECTS.map((dialect) => [dialect, value.dialects[dialect as keyof typeof value.dialects] || "N/A"])),
      availability: { supported: ["mysql", "postgres"], not_supported: ALL_DIALECTS.filter((dialect) => dialect !== "mysql" && dialect !== "postgres"), coverage: "2/12" },
    },
  };
}

function mockLibrary(detailResponse = detail()) {
  const fetchMock = vi.fn().mockImplementation(async (url: string) => {
    if (url === "/api/functions/categories") return response({ success: true, categories: [{ name: "string", count: 1 }], count: 1 });
    if (url.startsWith("/api/functions?")) return response({ success: true, functions: [detailResponse.function], count: 1, total: 1 });
    return response(detailResponse);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderPage() {
  return render(<MemoryRouter initialEntries={["/functions"]}><AppProvider><FunctionsPage /></AppProvider></MemoryRouter>);
}

function drawer(name: string | null, onClose = vi.fn()) {
  return <MemoryRouter><AppProvider><FunctionDetailDrawer name={name} onClose={onClose} /></AppProvider></MemoryRouter>;
}

describe("function detail drawer", () => {
  afterEach(() => {
    cleanup();
    localStorage.clear();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("loads details on card activation and shows parameters, all dialects, examples, and notes", async () => {
    const fetchMock = mockLibrary();
    renderPage();
    const card = await screen.findByRole("button", { name: "View CONCAT details" });
    expect(fetchMock.mock.calls.some(([url]) => url === "/api/functions/CONCAT")).toBe(false);
    fireEvent.click(card);

    const dialog = await screen.findByRole("dialog", { name: "CONCAT" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    await waitFor(() => expect(within(dialog).getByText("First string to concatenate")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith("/api/functions/CONCAT", expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(within(dialog).getByText("Concatenate strings into one value")).toBeInTheDocument();
    const parameterRow = within(dialog).getAllByRole("row").find((row) => row.textContent?.includes("First string to concatenate"));
    expect(parameterRow).toBeDefined();
    expect(within(parameterRow!).getByText("str1")).toBeInTheDocument();
    expect(within(parameterRow!).getByText("string")).toBeInTheDocument();
    expect(within(parameterRow!).getByText(/yes|required/i)).toBeInTheDocument();
    for (const dialect of ALL_DIALECTS) {
      const row = within(dialog).getAllByRole("row").find((candidate) => within(candidate).queryByText(DIALECT_LABELS[dialect], { exact: true }));
      expect(row, dialect).toBeDefined();
      expect(within(row!).getByText(detail().comparison.dialects[dialect], { exact: true })).toBeInTheDocument();
    }
    expect(within(dialog).getByText("SELECT CONCAT('hello', ' world');")).toBeInTheDocument();
    expect(within(dialog).getByText("NULL handling varies across dialects.")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByText("Concatenate strings into one value"));
    expect(screen.getByRole("dialog", { name: "CONCAT" })).toBeInTheDocument();
  });

  it("hides the parameters section when a function has no parameters", async () => {
    mockLibrary(detail("CURRENT_DATE", []));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "View CURRENT_DATE details" }));
    expect(await screen.findByRole("table", { name: "CURRENT_DATE syntax across 12 dialects" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Function parameters" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Parameters" })).not.toBeInTheDocument();
  });

  it("handles catalog records without optional parameter, example, or note fields", async () => {
    const payload = detail("CURRENT_DATE", []);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({
      ...payload,
      function: {
        name: payload.function.name,
        category: payload.function.category,
        description: payload.function.description,
        dialects: payload.function.dialects,
      },
      comparison: { ...payload.comparison, parameters: [], examples: {}, notes: "" },
    })));
    render(drawer("CURRENT_DATE"));
    const table = await screen.findByRole("table", { name: "CURRENT_DATE syntax across 12 dialects" });
    expect(screen.queryByRole("region", { name: "Function parameters" })).not.toBeInTheDocument();
    expect(within(table).getAllByRole("row")).toHaveLength(13);
    for (const dialect of ALL_DIALECTS) expect(within(table).getByRole("rowheader", { name: DIALECT_LABELS[dialect] })).toBeInTheDocument();
    expect(within(table).getAllByText("N/A")).toHaveLength(10);
    expect(screen.queryByRole("region", { name: "Function examples" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Function notes" })).not.toBeInTheDocument();
  });

  it("shows the API error and retries the detail request", async () => {
    let attempts = 0;
    const fetchMock = vi.fn().mockImplementation(async () => {
      attempts += 1;
      return attempts === 1 ? response({ error: { message: "Details are temporarily unavailable" } }, 503) : response(detail());
    });
    vi.stubGlobal("fetch", fetchMock);
    render(drawer("CONCAT"));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Details are temporarily unavailable");
    fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("First string to concatenate")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("moves focus from Retry to Close while the retried request is loading", async () => {
    let pendingSignal!: AbortSignal;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ error: { message: "Please retry" } }, 503))
      .mockImplementation((_url: string, init: RequestInit) => {
        pendingSignal = init.signal as AbortSignal;
        return new Promise((_resolve, reject) => {
          pendingSignal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
        });
      });
    vi.stubGlobal("fetch", fetchMock);
    const view = render(drawer("CONCAT"));
    const retry = await screen.findByRole("button", { name: "Retry" });
    retry.focus();
    expect(retry).toHaveFocus();
    fireEvent.click(retry);
    expect(screen.getByRole("status")).toHaveTextContent("Loading function details");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const close = screen.getByRole("button", { name: "Close function details" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(close, { key: "Tab" });
    expect(close).toHaveFocus();
    expect(screen.getByRole("dialog", { name: "CONCAT" })).toContainElement(document.activeElement as HTMLElement);
    expect(pendingSignal.aborted).toBe(false);
    await act(async () => { view.unmount(); });
    expect(pendingSignal.aborted).toBe(true);
  });

  it.each(["Escape", "backdrop", "close button"])("closes with %s and restores focus to the trigger card", async (action) => {
    mockLibrary();
    renderPage();
    const card = await screen.findByRole("button", { name: "View CONCAT details" });
    card.focus();
    fireEvent.click(card);
    const close = await screen.findByRole("button", { name: "Close function details" });
    expect(close).toHaveFocus();
    if (action === "Escape") fireEvent.keyDown(close, { key: "Escape" });
    else if (action === "backdrop") fireEvent.click(screen.getByTestId("function-detail-backdrop"));
    else fireEvent.click(close);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(card).toHaveFocus();
  });

  it.each(["Enter", " "])("opens a focused card with the %s key", async (key) => {
    mockLibrary();
    renderPage();
    const card = await screen.findByRole("button", { name: "View CONCAT details" });
    card.focus();
    await userEvent.keyboard(key === "Enter" ? "{Enter}" : " ");
    expect(await screen.findByRole("dialog", { name: "CONCAT" })).toBeInTheDocument();
  });

  it("keeps Tab and Shift+Tab focus inside the modal", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ error: { message: "Please retry" } }, 503)));
    render(drawer("CONCAT"));
    const retry = await screen.findByRole("button", { name: "Retry" });
    const close = screen.getByRole("button", { name: "Close function details" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
    expect(retry).toHaveFocus();
    fireEvent.keyDown(retry, { key: "Tab" });
    expect(close).toHaveFocus();
  });

  it("URL-encodes the entire function name in the detail request", async () => {
    const name = "ARRAY JOIN/#?";
    const fetchMock = vi.fn().mockResolvedValue(response(detail(name)));
    vi.stubGlobal("fetch", fetchMock);
    render(drawer(name));
    await screen.findByText("First string to concatenate");
    expect(fetchMock).toHaveBeenCalledWith(`/api/functions/${encodeURIComponent(name)}`, expect.objectContaining({ signal: expect.any(AbortSignal) }));
  });

  it("aborts the previous request on a name change and ignores its stale response", async () => {
    let resolveOld!: (value: ReturnType<typeof response>) => void;
    let oldSignal!: AbortSignal;
    const fetchMock = vi.fn().mockImplementation((url: string, init: RequestInit) => {
      if (url === "/api/functions/CONCAT") {
        oldSignal = init.signal as AbortSignal;
        return new Promise<ReturnType<typeof response>>((resolve) => { resolveOld = resolve; });
      }
      return Promise.resolve(response(detail("LOWER", [])));
    });
    vi.stubGlobal("fetch", fetchMock);
    const view = render(drawer("CONCAT"));
    expect(screen.getByRole("status")).toHaveTextContent("Loading function details");
    expect(oldSignal.aborted).toBe(false);
    view.rerender(drawer("LOWER"));
    expect(oldSignal.aborted).toBe(true);
    expect(await screen.findByRole("table", { name: "LOWER syntax across 12 dialects" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Function parameters" })).not.toBeInTheDocument();
    await act(async () => { resolveOld(response(detail("CONCAT"))); });
    expect(screen.getByRole("dialog", { name: "LOWER" })).toBeInTheDocument();
    expect(screen.queryByText("First string to concatenate")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("aborts a pending request when closed and does not surface an abort error", async () => {
    let signal!: AbortSignal;
    vi.stubGlobal("fetch", vi.fn().mockImplementation((_url: string, init: RequestInit) => {
      signal = init.signal as AbortSignal;
      return new Promise((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
      });
    }));
    const view = render(drawer("CONCAT"));
    expect(screen.getByRole("status")).toHaveTextContent("Loading function details");
    expect(signal.aborted).toBe(false);
    await act(async () => { view.rerender(drawer(null)); });
    expect(signal.aborted).toBe(true);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
