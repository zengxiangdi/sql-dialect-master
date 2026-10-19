import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Nl2SqlPage } from "./Nl2SqlPage";

function renderPage() {
  return render(<MemoryRouter initialEntries={["/nl2sql"]}><Nl2SqlPage /></MemoryRouter>);
}

describe("natural language query form", () => {
  afterEach(() => {
    cleanup();
    localStorage.clear();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("fills the editable natural-language field from an example without generating a request", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderPage();

    const input = screen.getByRole("textbox", { name: "Natural language" });
    const generate = screen.getByRole("button", { name: "Generate SQL" });
    expect(input).toHaveClass("nl-input");
    expect(input).toHaveValue("");
    expect(generate).toBeDisabled();

    const example = screen.getByRole("button", { name: "Find the top 10 customers by revenue" });
    expect(example).toHaveClass("example-chip");
    await user.click(example);
    expect(input).toHaveValue("Find the top 10 customers by revenue");
    expect(generate).toBeEnabled();

    await user.clear(input);
    await user.type(input, "   ");
    expect(generate).toBeDisabled();
    await user.clear(input);
    await user.type(input, "List paid orders");
    expect(input).toHaveValue("List paid orders");
    expect(generate).toBeEnabled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("preserves dialect and hints in the request and displays generated SQL, explanation, and evidence", async () => {
    const result = {
      success: true,
      input_text: "List paid orders by id",
      sql: "SELECT id FROM orders WHERE status = 'paid'",
      dialect: "mysql",
      explanation: "Select paid orders using the supplied table and column hints.",
      confidence: 0.93,
      suggestions: [],
      evidence: { matched_columns: ["orders.id", "orders.status"] },
      parameters: [],
      parameter_style: null,
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, headers: new Headers(), json: async () => result,
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "Find the top 10 customers by revenue" }));
    const input = screen.getByRole("textbox", { name: "Natural language" });
    await user.clear(input);
    await user.type(input, result.input_text);
    await user.selectOptions(screen.getByRole("combobox", { name: "Target dialect" }), "mysql");
    await user.type(screen.getByRole("textbox", { name: /Table hint/ }), "orders");
    await user.type(screen.getByRole("textbox", { name: "Column hints" }), " orders.id, , orders.status ");
    await user.click(screen.getByRole("button", { name: "Generate SQL" }));

    const output = await screen.findByRole("textbox", { name: "Generated SQL" });
    expect(output).toHaveValue(result.sql);
    expect(output).toHaveAttribute("readonly");
    expect(output).toHaveClass("code-editor");
    expect(output.closest(".nl-result-card")).toBeInTheDocument();
    expect(screen.getByText(result.explanation)).toBeInTheDocument();
    expect(screen.getByText("93% confidence")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use in Convert" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use in Diff" })).toBeInTheDocument();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, request] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/nl2sql");
    expect(request.method).toBe("POST");
    expect(request.signal).toBeInstanceOf(AbortSignal);
    expect(JSON.parse(request.body as string)).toEqual({
      text: result.input_text,
      dialect: "mysql",
      table_hint: "orders",
      column_hints: ["orders.id", "orders.status"],
    });

    const evidence = screen.getByText("Evidence and parameters");
    await user.click(evidence);
    const details = evidence.closest("details");
    expect(details).toHaveAttribute("open");
    const json = details?.querySelector(".json-block");
    expect(json).toBeInTheDocument();
    expect(JSON.parse(json?.textContent || "")).toEqual({
      evidence: result.evidence,
      parameters: result.parameters,
      parameter_style: result.parameter_style,
    });
  });
});
