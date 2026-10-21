import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppProvider, useApp } from "./app-context";
import { HISTORY_STORAGE_KEY } from "./storage";
import type { HistoryItem } from "./types";

function item(id: string, favorite?: boolean): HistoryItem {
  return {
    id,
    source: `SELECT ${id}`,
    target: `SELECT ${id}`,
    sourceDialect: "mysql",
    targetDialect: "postgres",
    createdAt: "2026-10-21T00:00:00Z",
    status: "success",
    ...(favorite === undefined ? {} : { favorite }),
  };
}

function HistoryConsumer() {
  const { history, addHistory, toggleFavorite } = useApp();
  return <div>
    <button onClick={() => addHistory(item("new"))}>Add history</button>
    <output aria-label="History count">{history.length}</output>
    {history.map((entry) => <button
      key={entry.id}
      aria-label={`Toggle favorite ${entry.source}`}
      aria-pressed={Boolean(entry.favorite)}
      onClick={() => toggleFavorite(entry.id)}
    >{entry.source}</button>)}
  </div>;
}

function renderHistory() {
  return render(<AppProvider><HistoryConsumer /></AppProvider>);
}

function storedHistory(): HistoryItem[] {
  return JSON.parse(localStorage.getItem(HISTORY_STORAGE_KEY) || "[]") as HistoryItem[];
}

describe("history favorites in app context", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("reads true, false, and absent favorite fields from existing history", () => {
    localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify([
      item("starred", true), item("unstarred", false), item("legacy"),
    ]));

    renderHistory();

    expect(screen.getByLabelText("History count")).toHaveTextContent("3");
    expect(screen.getByRole("button", { name: "Toggle favorite SELECT starred" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Toggle favorite SELECT unstarred" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Toggle favorite SELECT legacy" })).toHaveAttribute("aria-pressed", "false");
    expect(storedHistory().map((entry) => entry.favorite)).toEqual([true, false, undefined]);
  });

  it.each(["true", 1, null, {}])("rejects invalid persisted favorite=%j without rejecting valid history", (favorite) => {
    localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify([
      item("valid", true), { ...item("invalid"), favorite },
    ]));

    renderHistory();

    expect(screen.getByLabelText("History count")).toHaveTextContent("1");
    expect(screen.queryByRole("button", { name: "Toggle favorite SELECT invalid" })).not.toBeInTheDocument();
    expect(storedHistory()).toEqual([item("valid", true)]);
  });

  it("toggles and persists favorites across provider remounts", () => {
    localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify([item("first"), item("second", true)]));
    const firstRender = renderHistory();

    fireEvent.click(screen.getByRole("button", { name: "Toggle favorite SELECT first" }));

    expect(screen.getByRole("button", { name: "Toggle favorite SELECT first" })).toHaveAttribute("aria-pressed", "true");
    expect(storedHistory()).toEqual([item("first", true), item("second", true)]);
    firstRender.unmount();
    renderHistory();
    expect(screen.getByRole("button", { name: "Toggle favorite SELECT first" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "Toggle favorite SELECT first" }));

    expect(storedHistory()).toEqual([item("first", false), item("second", true)]);
  });

  it("keeps favorite toggles usable in memory when storage writes exceed quota", () => {
    localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify([item("saved")]));
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("full", "QuotaExceededError");
    });
    renderHistory();

    fireEvent.click(screen.getByRole("button", { name: "Toggle favorite SELECT saved" }));
    expect(screen.getByRole("button", { name: "Toggle favorite SELECT saved" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Toggle favorite SELECT saved" }));
    expect(screen.getByRole("button", { name: "Toggle favorite SELECT saved" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByLabelText("History count")).toHaveTextContent("1");
  });

  it("can create and favorite in-memory history when storage reads fail", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    renderHistory();
    expect(screen.getByLabelText("History count")).toHaveTextContent("0");

    fireEvent.click(screen.getByRole("button", { name: "Add history" }));
    fireEvent.click(screen.getByRole("button", { name: "Toggle favorite SELECT new" }));

    expect(screen.getByLabelText("History count")).toHaveTextContent("1");
    expect(screen.getByRole("button", { name: "Toggle favorite SELECT new" })).toHaveAttribute("aria-pressed", "true");
  });
});
