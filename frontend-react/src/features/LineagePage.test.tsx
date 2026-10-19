import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppProvider } from "../lib/app-context";
import { readLineageHandoff, writeLineageHandoff } from "../lib/handoff";
import { LineagePage } from "./UtilityPages";

function response(payload: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, headers: new Headers(), json: async () => payload };
}

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="location">{location.pathname}{location.search}</span>;
}

function renderPage(path = "/lineage") {
  return render(<MemoryRouter initialEntries={[path]}><AppProvider><LocationProbe /><LineagePage /></AppProvider></MemoryRouter>);
}

function expectCount(label: string, count: number) {
  const term = screen.getByText(label, { selector: "dt" });
  expect(term.nextElementSibling).toHaveTextContent(new RegExp(`^${count}$`));
}

const lineagePayload = {
  success: true,
  dialect: "postgres",
  elements: {
    tables: [{ name: "users" }, { name: "orders" }],
    columns: [
      { name: "id", table: "users" },
      { name: "email", table: "users" },
      { name: "id", table: "orders" },
      { name: "user_id", table: "orders" },
      { name: "total_amount", table: null },
    ],
    joins: [{ type: "INNER", table: "orders", on_condition: "orders.user_id = users.id" }],
  },
};

describe("LineagePage column relationships", () => {
  afterEach(() => {
    cleanup();
    localStorage.clear();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("groups qualified columns under their table and renders joins and counts", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(lineagePayload)));
    renderPage();
    expect(screen.getByRole("heading", { name: "Lineage canvas" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Build lineage" }));

    const users = await screen.findByRole("region", { name: "Table users" });
    const orders = screen.getByRole("region", { name: "Table orders" });
    expect(screen.getAllByRole("region", { name: /^Table / })).toHaveLength(2);
    expect(within(users).getAllByRole("listitem")).toHaveLength(2);
    expect(within(users).getByText("id", { exact: true })).toBeInTheDocument();
    expect(within(users).getByText("email", { exact: true })).toBeInTheDocument();
    expect(within(users).queryByText("user_id", { exact: true })).not.toBeInTheDocument();
    expect(within(orders).getAllByRole("listitem")).toHaveLength(2);
    expect(within(orders).getByText("id", { exact: true })).toBeInTheDocument();
    expect(within(orders).getByText("user_id", { exact: true })).toBeInTheDocument();
    expect(within(orders).queryByText("email", { exact: true })).not.toBeInTheDocument();

    const unqualified = screen.getByRole("region", { name: "Unqualified / unmatched columns" });
    expect(within(unqualified).getAllByRole("listitem")).toHaveLength(1);
    expect(within(unqualified).getByText("total_amount", { exact: true })).toBeInTheDocument();
    expect(within(users).queryByText("total_amount")).not.toBeInTheDocument();
    expect(within(orders).queryByText("total_amount")).not.toBeInTheDocument();

    const joins = screen.getByRole("region", { name: "Join relationships" });
    expect(joins).toHaveTextContent("INNER");
    expect(joins).toHaveTextContent("orders");
    expect(joins).toHaveTextContent("orders.user_id = users.id");
    expectCount("Tables", 2);
    expectCount("Columns", 5);
    expectCount("Joins", 1);
    expectCount("Unqualified columns", 1);
  });

  it("uses exact alias matches and keeps unmatched or differently cased qualifiers separate", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({
      success: true,
      dialect: "postgres",
      elements: {
        tables: [{ name: "users", alias: "u", schema: "public", catalog: "app" }, { name: "orders", alias: "o" }],
        columns: [
          { name: "id", table: "u", alias: "user_identifier" },
          { name: "user_id", table: "o" },
          { name: "name", table: "users" },
          { name: "capitalized", table: "U" },
          { name: "external", table: "unknown" },
        ],
        joins: [],
      },
    })));
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Build lineage" }));

    const users = await screen.findByRole("region", { name: "Table u" });
    const orders = screen.getByRole("region", { name: "Table o" });
    expect(users).toHaveTextContent("users");
    expect(users).toHaveTextContent("public");
    expect(users).toHaveTextContent("app");
    expect(users).toHaveTextContent("user_identifier");
    expect(within(users).getAllByRole("listitem")).toHaveLength(1);
    expect(within(users).getByText("id", { exact: true })).toBeInTheDocument();
    expect(within(orders).getAllByRole("listitem")).toHaveLength(1);
    expect(within(orders).getByText("user_id", { exact: true })).toBeInTheDocument();
    const unqualified = screen.getByRole("region", { name: "Unqualified / unmatched columns" });
    expect(within(unqualified).getAllByRole("listitem")).toHaveLength(3);
    for (const name of ["users.name", "U.capitalized", "unknown.external"]) {
      expect(within(unqualified).getByText(name, { exact: true })).toBeInTheDocument();
      expect(within(users).queryByText(name, { exact: true })).not.toBeInTheDocument();
      expect(within(orders).queryByText(name, { exact: true })).not.toBeInTheDocument();
    }
    expectCount("Columns", 5);
    expectCount("Unqualified columns", 3);
  });

  it.each([
    { name: "duplicate aliases", tables: [{ name: "users", alias: "u" }, { name: "orders", alias: "u" }] },
    { name: "a table name and alias collision", tables: [{ name: "u" }, { name: "orders", alias: "u" }] },
  ])("keeps ambiguously qualified columns separate for $name", async ({ tables }) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({
      success: true,
      dialect: "postgres",
      elements: { tables, columns: [{ name: "id", table: "u" }], joins: [] },
    })));
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Build lineage" }));

    const cards = await screen.findAllByRole("region", { name: "Table u" });
    expect(cards).toHaveLength(2);
    for (const card of cards) {
      expect(within(card).getByText("No columns for this table.")).toBeInTheDocument();
      expect(within(card).queryByRole("listitem")).not.toBeInTheDocument();
      expect(within(card).queryByText("id", { exact: true })).not.toBeInTheDocument();
    }
    const unqualified = screen.getByRole("region", { name: "Unqualified / unmatched columns" });
    expect(within(unqualified).getAllByRole("listitem")).toHaveLength(1);
    expect(within(unqualified).getByText("u.id", { exact: true })).toBeInTheDocument();
    expectCount("Tables", 2);
    expectCount("Columns", 1);
    expectCount("Unqualified columns", 1);
  });

  it("handles tables-only responses with explicit empty column and join states", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ success: true, dialect: "postgres", elements: { tables: [{ name: "users" }, { name: "orders" }] } })));
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Build lineage" }));

    const users = await screen.findByRole("region", { name: "Table users" });
    const orders = screen.getByRole("region", { name: "Table orders" });
    expect(within(users).getByText("No columns for this table.")).toBeInTheDocument();
    expect(within(orders).getByText("No columns for this table.")).toBeInTheDocument();
    expect(screen.getByText("No joins found.")).toBeInTheDocument();
    expect(within(users).queryByRole("list")).not.toBeInTheDocument();
    expect(within(orders).queryByRole("list")).not.toBeInTheDocument();
    expectCount("Tables", 2);
    expectCount("Columns", 0);
    expectCount("Joins", 0);
    expectCount("Unqualified columns", 0);
  });

  it("keeps columns visible even when a query has no source tables", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({
      success: true,
      dialect: "postgres",
      elements: { tables: [], columns: [{ name: "answer", table: "" }], joins: [] },
    })));
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Build lineage" }));

    const unqualified = await screen.findByRole("region", { name: "Unqualified / unmatched columns" });
    expect(within(unqualified).getByText("answer", { exact: true })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Lineage canvas" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /^Table / })).not.toBeInTheDocument();
    expectCount("Tables", 0);
    expectCount("Columns", 1);
    expectCount("Unqualified columns", 1);
  });

  it("shows join conditions as plain text and handles a missing ON condition", async () => {
    const condition = 'users.note = \'<img src="x" onerror="alert(1)">\'';
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({
      success: true,
      dialect: "postgres",
      elements: {
        tables: [{ name: "users" }],
        columns: [],
        joins: [{ type: "INNER", table: "orders", on_condition: condition }, { type: "CROSS", table: "products", on_condition: null }],
      },
    })));
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Build lineage" }));

    const joins = await screen.findByRole("region", { name: "Join relationships" });
    expect(within(joins).getAllByRole("listitem")).toHaveLength(2);
    expect(within(joins).getByText(condition, { exact: true })).toBeInTheDocument();
    expect(within(joins).getByText("No ON condition.")).toBeInTheDocument();
    expect(joins.querySelector("img")).toBeNull();
    expectCount("Joins", 2);
  });

  it("shows a failed parse request in ErrorPanel and retries the same input", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ error: { message: "Parser unavailable" } }, 503))
      .mockResolvedValueOnce(response(lineagePayload));
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Build lineage" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Parser unavailable");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("region", { name: "Table users" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/parse");
    expect(fetchMock.mock.calls[1][1].body).toBe(fetchMock.mock.calls[0][1].body);
  });

  it("keeps SQL handoff and URL dialect priority and sends the selected dialect to parse", async () => {
    writeLineageHandoff({ sql: "SELECT handoff_id FROM users", dialect: "oracle" });
    const fetchMock = vi.fn().mockResolvedValue(response(lineagePayload));
    vi.stubGlobal("fetch", fetchMock);
    renderPage("/lineage?dialect=mysql&tab=columns");

    expect(screen.getByLabelText("Lineage SQL editor")).toHaveValue("SELECT handoff_id FROM users");
    expect(screen.getByLabelText("Dialect")).toHaveValue("mysql");
    fireEvent.change(screen.getByLabelText("Dialect"), { target: { value: "snowflake" } });
    fireEvent.change(screen.getByLabelText("Lineage SQL editor"), { target: { value: "SELECT id FROM users" } });
    expect(screen.getByTestId("location")).toHaveTextContent("/lineage?dialect=snowflake&tab=columns");
    await waitFor(() => expect(readLineageHandoff()).toEqual({ sql: "SELECT id FROM users", dialect: "snowflake" }));
    fireEvent.click(screen.getByRole("button", { name: "Build lineage" }));

    await screen.findByRole("region", { name: "Table users" });
    expect(fetchMock).toHaveBeenCalledWith("/api/parse", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ sql: "SELECT id FROM users", dialect: "snowflake" }),
    }));
  });

  it("aborts an in-flight parse when SQL changes and ignores its stale response", async () => {
    let resolveParse!: (value: ReturnType<typeof response>) => void;
    const fetchMock = vi.fn().mockImplementation(() => new Promise<ReturnType<typeof response>>((resolve) => { resolveParse = resolve; }));
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Build lineage" }));
    const signal = fetchMock.mock.calls[0][1].signal as AbortSignal;
    expect(signal.aborted).toBe(false);

    fireEvent.change(screen.getByLabelText("Lineage SQL editor"), { target: { value: "SELECT changed FROM products" } });
    expect(signal.aborted).toBe(true);
    resolveParse(response(lineagePayload));
    await waitFor(() => expect(screen.getByRole("button", { name: "Build lineage" })).not.toBeDisabled());
    expect(screen.queryByRole("region", { name: "Table users" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Lineage canvas" })).toBeInTheDocument();
  });

  it("aborts parsing after a dialect change and only renders the next dialect result", async () => {
    let resolveParse!: (value: ReturnType<typeof response>) => void;
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => new Promise<ReturnType<typeof response>>((resolve) => { resolveParse = resolve; }))
      .mockResolvedValueOnce(response({ success: true, dialect: "oracle", elements: { tables: [{ name: "current" }] } }));
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Build lineage" }));
    const signal = fetchMock.mock.calls[0][1].signal as AbortSignal;

    fireEvent.change(screen.getByLabelText("Dialect"), { target: { value: "oracle" } });
    expect(signal.aborted).toBe(true);
    resolveParse(response(lineagePayload));
    await waitFor(() => expect(screen.getByRole("button", { name: "Build lineage" })).not.toBeDisabled());
    expect(screen.queryByRole("region", { name: "Table users" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Build lineage" }));

    expect(await screen.findByRole("region", { name: "Table current" })).toBeInTheDocument();
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).dialect).toBe("oracle");
    expect(screen.queryByRole("region", { name: "Table users" })).not.toBeInTheDocument();
  });

  it("aborts an in-flight parse when the page unmounts", () => {
    const fetchMock = vi.fn().mockImplementation((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    }));
    vi.stubGlobal("fetch", fetchMock);
    const page = renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Build lineage" }));
    const signal = fetchMock.mock.calls[0][1].signal as AbortSignal;
    page.unmount();
    expect(signal.aborted).toBe(true);
  });
});
