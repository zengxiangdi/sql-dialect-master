import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ALL_DIALECTS, type FunctionItem, type TypeMapping } from "../lib/types";
import { FunctionsPage, TypesPage } from "./LibraryPages";

function response(payload: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, headers: new Headers(), json: async () => payload };
}

const concat: FunctionItem = {
  name: "CONCAT",
  category: "string",
  description: "Combine strings into a single value.",
  dialects: { mysql: "CONCAT(a, b)", postgres: "a || b", oracle: "N/A", spark: "" },
};

const categoryResponse = { success: true, categories: [{ name: "string", count: 1 }, { name: "math", count: 1 }], count: 2 };

function functions(count: number, prefix = "FUNCTION", category = "string"): FunctionItem[] {
  return Array.from({ length: count }, (_, index) => ({ ...concat, name: `${prefix}_${index + 1}`, category }));
}

describe("function library", () => {
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

  it("shows the catalog summary, descriptions, supported dialects, and only available parameter counts", async () => {
    const parameter = { name: "value", type: "string", required: true, description: "Input value" };
    const items = [concat, { ...concat, name: "UPPER", parameters: [parameter] }, { ...concat, name: "LOWER", parameters: [] }];
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string) => response(url === "/api/functions/categories"
      ? categoryResponse
      : { success: true, functions: items, count: 3, total: 298 })));

    render(<FunctionsPage />);

    expect(await screen.findByText("Showing 3 of 3 matching functions · 298 in catalog · 2 categories · 12 dialects")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Load more/ })).not.toBeInTheDocument();
    const card = screen.getByRole("button", { name: "View CONCAT details" });
    expect(card.tagName).toBe("BUTTON");
    expect(within(card).getByText(concat.description!)).toBeInTheDocument();
    expect(within(card).getByText("string")).toBeInTheDocument();
    expect(within(card).getByText("2 dialects")).toBeInTheDocument();
    expect(within(card).getByText("MySQL")).toBeInTheDocument();
    expect(within(card).getByText("PostgreSQL")).toBeInTheDocument();
    expect(within(card).queryByText("Oracle")).not.toBeInTheDocument();
    expect(within(card).queryByText("Spark SQL")).not.toBeInTheDocument();
    expect(within(card).getByText("View details")).toBeInTheDocument();
    expect(within(card).queryByText(/parameters?/)).not.toBeInTheDocument();
    expect(within(screen.getByRole("button", { name: "View UPPER details" })).getByText("1 parameter")).toBeInTheDocument();
    expect(within(screen.getByRole("button", { name: "View LOWER details" })).queryByText(/parameters?/)).not.toBeInTheDocument();
  });

  it("keeps search and category parameters on debounced library requests", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockImplementation(async (url: string) => response(url === "/api/functions/categories"
      ? categoryResponse
      : { success: true, functions: [concat], count: 1, total: 298 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<FunctionsPage />);
    await screen.findByRole("button", { name: "View CONCAT details" });

    await user.type(screen.getByRole("textbox", { name: "Search functions" }), "CON");
    await user.selectOptions(screen.getByRole("combobox", { name: "Filter functions by category" }), "string");

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/functions?limit=500&search=CON&category=string", expect.objectContaining({ signal: expect.any(AbortSignal) })));
    expect(screen.getByRole("textbox", { name: "Search functions" })).toHaveValue("CON");
    expect(screen.getByRole("combobox", { name: "Filter functions by category" })).toHaveValue("string");
  });

  it("clears both filters from the empty state and loads the unfiltered catalog", async () => {
    const user = userEvent.setup();
    const catalog = [concat, ...functions(129)];
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url === "/api/functions/categories") return response(categoryResponse);
      const params = new URL(url, "https://example.test").searchParams;
      const items = params.has("search") || params.has("category") ? [] : catalog;
      return response({ success: true, functions: items, count: items.length, total: 298 });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<FunctionsPage />);
    await screen.findByRole("button", { name: "View CONCAT details" });
    await user.click(screen.getByRole("button", { name: "Load more (70 remaining)" }));
    expect(screen.getAllByRole("button", { name: /^View .+ details$/ })).toHaveLength(120);
    await user.type(screen.getByRole("textbox", { name: "Search functions" }), "missing");
    await user.selectOptions(screen.getByRole("combobox", { name: "Filter functions by category" }), "math");

    expect(await screen.findByText("No functions found")).toBeInTheDocument();
    expect(screen.getByText("Showing 0 of 0 matching functions · 298 in catalog · 2 categories · 12 dialects")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear filters" }));

    expect(screen.getByRole("textbox", { name: "Search functions" })).toHaveValue("");
    expect(screen.getByRole("combobox", { name: "Filter functions by category" })).toHaveValue("");
    expect(await screen.findByRole("button", { name: "View CONCAT details" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^View .+ details$/ })).toHaveLength(60);
    expect(screen.getByRole("button", { name: "Load more (70 remaining)" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.at(-1)?.[0]).toBe("/api/functions?limit=500");
  });

  it("reveals the fetched catalog in groups of 60 without fetching again", async () => {
    const user = userEvent.setup();
    const catalog = functions(130);
    const fetchMock = vi.fn().mockImplementation(async (url: string) => response(url === "/api/functions/categories"
      ? categoryResponse
      : { success: true, functions: catalog, count: catalog.length, total: 130 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<FunctionsPage />);

    expect(await screen.findByText("Showing 60 of 130 matching functions · 130 in catalog · 2 categories · 12 dialects")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^View .+ details$/ })).toHaveLength(60);
    expect(screen.queryByRole("button", { name: "View FUNCTION_61 details" })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/functions?limit=500", expect.objectContaining({ signal: expect.any(AbortSignal) }));
    const fetchCount = fetchMock.mock.calls.length;

    await user.click(screen.getByRole("button", { name: "Load more (70 remaining)" }));
    expect(screen.getAllByRole("button", { name: /^View .+ details$/ })).toHaveLength(120);
    expect(screen.getByText("Showing 120 of 130 matching functions · 130 in catalog · 2 categories · 12 dialects")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "View FUNCTION_121 details" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Load more (10 remaining)" }));
    expect(screen.getAllByRole("button", { name: /^View .+ details$/ })).toHaveLength(130);
    expect(screen.getByRole("button", { name: "View FUNCTION_130 details" })).toBeInTheDocument();
    expect(screen.getByText("Showing 130 of 130 matching functions · 130 in catalog · 2 categories · 12 dialects")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Load more/ })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(fetchCount);
  });

  it.each([
    { filter: "search", count: 125, requestUrl: "/api/functions?limit=500&search=MATCH" },
    { filter: "category", count: 90, requestUrl: "/api/functions?limit=500&category=math" },
  ])("resets the visible cards after changing $filter", async ({ filter, count, requestUrl }) => {
    const user = userEvent.setup();
    const catalog = functions(130);
    const matching = functions(count, "MATCH", "math");
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url === "/api/functions/categories") return response(categoryResponse);
      const items = url === "/api/functions?limit=500" ? catalog : matching;
      return response({ success: true, functions: items, count: items.length, total: 298 });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<FunctionsPage />);
    await screen.findByRole("button", { name: "View FUNCTION_1 details" });
    await user.click(screen.getByRole("button", { name: "Load more (70 remaining)" }));
    expect(screen.getAllByRole("button", { name: /^View .+ details$/ })).toHaveLength(120);

    if (filter === "search") await user.type(screen.getByRole("textbox", { name: "Search functions" }), "MATCH");
    else await user.selectOptions(screen.getByRole("combobox", { name: "Filter functions by category" }), "math");

    expect(await screen.findByText(`Showing 60 of ${count} matching functions · 298 in catalog · 2 categories · 12 dialects`)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^View .+ details$/ })).toHaveLength(60);
    expect(screen.getByRole("button", { name: `Load more (${count - 60} remaining)` })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "View MATCH_61 details" })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(requestUrl, expect.objectContaining({ signal: expect.any(AbortSignal) }));
  });

  it("opens the real detail drawer from a native button card", async () => {
    const user = userEvent.setup();
    const functionDetail = { ...concat, dialects: concat.dialects!, parameters: [], examples: {}, notes: "Details from the API." };
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url === "/api/functions/categories") return response(categoryResponse);
      if (url.startsWith("/api/functions?")) return response({ success: true, functions: [concat], count: 1, total: 298 });
      return response({ success: true, function: functionDetail, comparison: { ...functionDetail, dialects: Object.fromEntries(ALL_DIALECTS.map((dialect) => [dialect, concat.dialects?.[dialect] || "N/A"])), availability: { supported: ["mysql", "postgres"], not_supported: [], coverage: "2/12" } } });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<FunctionsPage />);
    const card = await screen.findByRole("button", { name: "View CONCAT details" });
    expect(card).toHaveAttribute("aria-haspopup", "dialog");
    expect(card).toHaveAttribute("aria-expanded", "false");
    await user.click(card);

    expect(await screen.findByRole("dialog", { name: "CONCAT" })).toBeInTheDocument();
    expect(await screen.findByText("Details from the API.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/functions/CONCAT", expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(card).toHaveAttribute("aria-expanded", "true");
    await user.click(screen.getByRole("button", { name: "Close function details" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(card).toHaveFocus();
  });

  it("keeps list loading, error, and retry behavior", async () => {
    const user = userEvent.setup();
    let listCalls = 0;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string) => {
      if (url === "/api/functions/categories") return response(categoryResponse);
      listCalls += 1;
      return listCalls === 1 ? response({ error: { code: "SERVICE_UNAVAILABLE", message: "Library unavailable" } }, 503)
        : response({ success: true, functions: [concat], count: 1, total: 298 });
    }));
    render(<FunctionsPage />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading functions");
    expect(await screen.findByRole("alert")).toHaveTextContent("Library unavailable");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("button", { name: "View CONCAT details" })).toBeInTheDocument();
    expect(listCalls).toBe(2);
  });
});

describe("type mapping library", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  function mappings(count: number): TypeMapping[] {
    return Array.from({ length: count }, (_, index) => {
      const suffix = String(index + 1).padStart(3, "0");
      return { type: `TYPE_${suffix}`, source: `SOURCE_${suffix}`, target: index === count - 1 ? "N/A" : `TARGET_${suffix}` };
    });
  }

  it("renders all 85 returned mappings with the existing caption, columns, and status", async () => {
    const items = mappings(85);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ success: true, mappings: items, type_count: items.length })));
    render(<TypesPage />);

    const table = await screen.findByRole("table", { name: "SQL type mappings from MySQL to PostgreSQL" });
    expect(within(table).getAllByRole("row")).toHaveLength(86);
    expect(screen.getByText("Showing 85 of 85 types")).toBeInTheDocument();
    expect(within(table).getAllByRole("columnheader").map((header) => header.textContent)).toEqual(["Canonical type", "MySQL", "PostgreSQL", "Status"]);
    const firstRow = within(table).getByRole("cell", { name: "TYPE_001" }).closest("tr")!;
    expect(within(firstRow).getByRole("cell", { name: "SOURCE_001" })).toBeInTheDocument();
    expect(within(firstRow).getByRole("cell", { name: "TARGET_001" })).toBeInTheDocument();
    expect(within(firstRow).getByText("Mapped")).toBeInTheDocument();
    const lastRow = within(table).getByRole("cell", { name: "TYPE_085" }).closest("tr")!;
    expect(within(lastRow).getByRole("cell", { name: "SOURCE_085" })).toBeInTheDocument();
    expect(within(lastRow).getByRole("cell", { name: "N/A" })).toBeInTheDocument();
    expect(within(lastRow).getByText("Unsupported")).toBeInTheDocument();
  });

  it("counts and filters all 39 mappings locally, then restores them when search is cleared", async () => {
    const user = userEvent.setup();
    const items = mappings(39);
    const fetchMock = vi.fn().mockResolvedValue(response({ success: true, mappings: items, type_count: items.length }));
    vi.stubGlobal("fetch", fetchMock);
    render(<TypesPage />);

    const summary = await screen.findByText("Showing 39 of 39 types");
    expect(summary).toHaveAttribute("aria-live", "polite");
    const search = screen.getByRole("textbox", { name: "Filter types" });
    const fetchCount = fetchMock.mock.calls.length;
    await user.type(search, "type_00");

    expect(screen.getByText("Showing 9 of 39 types")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(10);
    expect(screen.getByRole("cell", { name: "TYPE_009" })).toBeInTheDocument();
    expect(screen.queryByRole("cell", { name: "TYPE_010" })).not.toBeInTheDocument();
    await user.clear(search);
    await user.type(search, "not-a-type");
    expect(screen.getByText("Showing 0 of 39 types")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(1);

    await user.clear(search);
    expect(screen.getByText("Showing 39 of 39 types")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(40);
    expect(screen.getByRole("cell", { name: "TYPE_039" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(fetchCount);
  });

  it("keeps source and target dialects in mapping requests and table headings", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue(response({ success: true, mappings: mappings(1), type_count: 1 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<TypesPage />);
    await screen.findByRole("table", { name: "SQL type mappings from MySQL to PostgreSQL" });
    expect(fetchMock).toHaveBeenCalledWith("/api/types?source=mysql&target=postgres", expect.objectContaining({ signal: expect.any(AbortSignal) }));

    await user.selectOptions(screen.getByRole("combobox", { name: "Source" }), "oracle");
    await user.selectOptions(screen.getByRole("combobox", { name: "Target" }), "duckdb");

    expect(await screen.findByRole("table", { name: "SQL type mappings from Oracle to DuckDB" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Oracle" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "DuckDB" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/types?source=oracle&target=duckdb", expect.objectContaining({ signal: expect.any(AbortSignal) }));
  });

  it("preserves mapping loading, errors, and retry without displaying a stale count", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ error: { message: "Mappings unavailable", code: "SERVICE_UNAVAILABLE" } }, 503))
      .mockResolvedValueOnce(response({ success: true, mappings: mappings(2), type_count: 2 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<TypesPage />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading type mappings");
    expect(screen.queryByText(/Showing \d+ of \d+ types/)).not.toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("Mappings unavailable");
    expect(screen.queryByText(/Showing \d+ of \d+ types/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("Showing 2 of 2 types")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(3);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
