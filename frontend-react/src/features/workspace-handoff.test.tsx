import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppRoutes } from "../app/routes";
import { AppProvider } from "../lib/app-context";
import { readConvertHandoff, readDiffHandoff } from "../lib/handoff";
import { ConvertPage } from "./ConvertPage";
import { Nl2SqlPage } from "./Nl2SqlPage";
import { AnalysisPage, DiffPage, LineagePage } from "./UtilityPages";

function response(payload: unknown) {
  return { ok: true, status: 200, headers: new Headers(), json: async () => payload };
}

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="location">{location.pathname}{location.search}</span>;
}

const diffPayload = {
  success: true, equivalent: true, status: "equivalent", differences: [],
  difference_categories: [], structured_differences: [], confidence: 1,
};

describe("workspace handoff and dialect selection", () => {
  afterEach(() => {
    cleanup();
    localStorage.clear();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("initializes Diff dialects from the URL and sends them to the API", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(diffPayload));
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter initialEntries={["/diff?source=mysql&target=oracle"]}><LocationProbe /><DiffPage /></MemoryRouter>);
    expect(screen.getByLabelText("Source dialect")).toHaveValue("mysql");
    expect(screen.getByLabelText("Target dialect")).toHaveValue("oracle");
    fireEvent.click(screen.getByRole("button", { name: "Compare" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === "/api/diff")).toBe(true));
    const [, init] = fetchMock.mock.calls.find(([url]) => url === "/api/diff") as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toMatchObject({ source_dialect: "mysql", target_dialect: "oracle" });
    fireEvent.change(screen.getByLabelText("Source dialect"), { target: { value: "postgres" } });
    expect(screen.getByTestId("location")).toHaveTextContent("/diff?source=postgres&target=oracle");
  });

  it("falls back when Diff URL dialects are invalid", () => {
    render(<MemoryRouter initialEntries={["/diff?source=unknown&target=bad"]}><DiffPage /></MemoryRouter>);
    expect(screen.getByLabelText("Source dialect")).toHaveValue("postgres");
    expect(screen.getByLabelText("Target dialect")).toHaveValue("mysql");
  });

  it("uses the selected dialect for Analysis and Lineage parsing", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ success: true, dialect: "mysql", elements: { tables: [{ name: "users" }] } }));
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter initialEntries={["/analysis?dialect=mysql"]}><AnalysisPage /></MemoryRouter>);
    expect(screen.getByLabelText("Dialect")).toHaveValue("mysql");
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === "/api/parse")).toBe(true));
    const [, analysisInit] = fetchMock.mock.calls.find(([url]) => url === "/api/parse") as [string, RequestInit];
    expect(JSON.parse(String(analysisInit.body)).dialect).toBe("mysql");

    cleanup();
    fetchMock.mockClear();
    render(<MemoryRouter initialEntries={["/lineage?dialect=oracle"]}><LineagePage /></MemoryRouter>);
    expect(screen.getByLabelText("Dialect")).toHaveValue("oracle");
    fireEvent.click(screen.getByRole("button", { name: "Build lineage" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === "/api/parse")).toBe(true));
    const [, lineageInit] = fetchMock.mock.calls.find(([url]) => url === "/api/parse") as [string, RequestInit];
    expect(JSON.parse(String(lineageInit.body)).dialect).toBe("oracle");
  });

  it("moves a normal history entry to Diff and blocks truncated actions", async () => {
    localStorage.setItem("sdm.history", JSON.stringify([{
      id: "normal", source: "SELECT 1", target: "SELECT 2", sourceDialect: "mysql", targetDialect: "postgres",
      createdAt: new Date().toISOString(), status: "success",
    }, {
      id: "truncated", source: "SELECT 3", target: "SELECT 4", sourceDialect: "mysql", targetDialect: "postgres",
      createdAt: new Date().toISOString(), status: "success", truncated: true,
    }]));
    render(<MemoryRouter initialEntries={["/history"]}><LocationProbe /><AppProvider><AppRoutes /></AppProvider></MemoryRouter>);
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Use in Diff" })).toHaveLength(2));
    const actions = screen.getAllByRole("button", { name: "Use in Diff" });
    expect(actions[1]).toBeDisabled();
    fireEvent.click(actions[0]);
    expect(readDiffHandoff()).toEqual({ sourceSql: "SELECT 1", targetSql: "SELECT 2", sourceDialect: "mysql", targetDialect: "postgres" });
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/diff?source=mysql&target=postgres"));
  });

  it("moves a normal history entry to Convert", async () => {
    localStorage.setItem("sdm.history", JSON.stringify([{
      id: "normal-convert", source: "SELECT 10", target: "SELECT 10", sourceDialect: "postgres", targetDialect: "mysql",
      createdAt: new Date().toISOString(), status: "success",
    }]));
    render(<MemoryRouter initialEntries={["/history"]}><LocationProbe /><AppProvider><AppRoutes /></AppProvider></MemoryRouter>);
    const button = await waitFor(() => screen.getByRole("button", { name: "Use in Convert" }));
    fireEvent.click(button);
    expect(readConvertHandoff()).toEqual({ sql: "SELECT 10", sourceDialect: "postgres", targetDialect: "mysql" });
  });

  it("initializes Convert from a handoff payload", () => {
    localStorage.setItem("sdm.handoff.convert", JSON.stringify({ sql: "SELECT handoff", sourceDialect: "oracle", targetDialect: "duckdb" }));
    render(<MemoryRouter initialEntries={["/convert"]}><AppProvider><ConvertPage /></AppProvider></MemoryRouter>);
    expect(screen.getByLabelText("Source dialect")).toHaveValue("oracle");
    expect(screen.getByLabelText("Target dialect")).toHaveValue("duckdb");
    expect((screen.getByLabelText("Source SQL editor") as HTMLTextAreaElement).value).toBe("SELECT handoff");
  });

  it("opens Diff from a successful Convert result", async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string) => url === "/health"
      ? response({ status: "alive" })
      : response({ success: true, source_sql: "SELECT 1", target_sql: "SELECT 1", source_dialect: "mysql", target_dialect: "postgres", warnings: [], compatibility_notes: [], transformations: [], target_validation_state: "target_valid" }));
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter initialEntries={["/convert?source=mysql&target=postgres"]}><LocationProbe /><AppProvider><ConvertPage /></AppProvider></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: "Convert SQL" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Open Diff" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Open Diff" }));
    expect(readDiffHandoff()).toMatchObject({ sourceDialect: "mysql", targetDialect: "postgres" });
    expect(screen.getByTestId("location")).toHaveTextContent("/diff?source=mysql&target=postgres");
  });

  it("keeps NL2SQL Convert and adds Diff handoff", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ success: true, input_text: "list users", sql: "SELECT id FROM users", dialect: "postgres", explanation: "", confidence: 1, suggestions: [] }));
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter initialEntries={["/nl2sql"]}><LocationProbe /><Nl2SqlPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Natural language"), { target: { value: "list users" } });
    fireEvent.click(screen.getByRole("button", { name: "Generate SQL" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Use in Diff" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Use in Convert" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Use in Diff" }));
    expect(readDiffHandoff()).toMatchObject({ sourceSql: "SELECT id FROM users", sourceDialect: "postgres", targetDialect: "mysql" });
    expect(readConvertHandoff()).toBeNull();
    expect(screen.getByTestId("location")).toHaveTextContent("/diff?source=postgres&target=mysql");
  });
});
