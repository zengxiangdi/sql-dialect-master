import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppProvider } from "../lib/app-context";
import { HISTORY_STORAGE_KEY } from "../lib/storage";
import type { HistoryItem } from "../lib/types";
import { HistoryPage } from "./HistoryPage";

function historyItems(count = 25): HistoryItem[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `history-${index + 1}`,
    source: `SELECT source_${String(index + 1).padStart(2, "0")}`,
    target: `SELECT target_${String(index + 1).padStart(2, "0")}`,
    sourceDialect: "postgres",
    targetDialect: "mysql",
    createdAt: new Date(Date.UTC(2026, 9, 21, 0, 0, count - index)).toISOString(),
    status: "success",
  }));
}

function renderHistory(items?: HistoryItem[]) {
  if (items !== undefined) localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(items));
  return render(<MemoryRouter initialEntries={["/history"]}><AppProvider><HistoryPage /></AppProvider></MemoryRouter>);
}

function storedHistory(): HistoryItem[] {
  return JSON.parse(localStorage.getItem(HISTORY_STORAGE_KEY) || "[]") as HistoryItem[];
}

describe("history favorites and pagination", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("shows 25 records in pages of 10, 10, and 5 with bounded Prev and Next actions", async () => {
    const items = historyItems();
    const user = userEvent.setup();
    renderHistory(items);

    expect(screen.getByRole("button", { name: "All", pressed: true })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Favorites", pressed: false })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Use in Convert" })).toHaveLength(10);
    expect(screen.getByText(items[0].source)).toBeInTheDocument();
    expect(screen.getByText(items[9].source)).toBeInTheDocument();
    expect(screen.queryByText(items[10].source)).not.toBeInTheDocument();
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
    expect(screen.getByText("Showing 1–10 of 25")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Prev" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getAllByRole("button", { name: "Use in Convert" })).toHaveLength(10);
    expect(screen.getByText(items[10].source)).toBeInTheDocument();
    expect(screen.getByText(items[19].source)).toBeInTheDocument();
    expect(screen.queryByText(items[0].source)).not.toBeInTheDocument();
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();
    expect(screen.getByText("Showing 11–20 of 25")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getAllByRole("button", { name: "Use in Convert" })).toHaveLength(5);
    expect(screen.getByText(items[20].source)).toBeInTheDocument();
    expect(screen.getByText(items[24].source)).toBeInTheDocument();
    expect(screen.getByText("Page 3 of 3")).toBeInTheDocument();
    expect(screen.getByText("Showing 21–25 of 25")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Prev" }));
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Use in Convert" })).toHaveLength(10);
  });

  it.each([10, 11])("handles the page boundary for %i records", async (count) => {
    const user = userEvent.setup();
    renderHistory(historyItems(count));

    expect(screen.getAllByRole("button", { name: "Use in Convert" })).toHaveLength(10);
    expect(screen.getByText(`Page 1 of ${count === 10 ? 1 : 2}`)).toBeInTheDocument();
    if (count === 10) {
      expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    } else {
      await user.click(screen.getByRole("button", { name: "Next" }));
      expect(screen.getAllByRole("button", { name: "Use in Convert" })).toHaveLength(1);
      expect(screen.getByText("Showing 11–11 of 11")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    }
  });

  it("adds and removes a favorite, persists its state, and restores it after remount", async () => {
    const user = userEvent.setup();
    const view = renderHistory(historyItems());
    const favorite = screen.getAllByRole("button", { name: "Add to favorites" })[0];
    expect(favorite).toHaveAttribute("aria-pressed", "false");
    await user.click(favorite);

    expect(screen.getByRole("button", { name: "Remove from favorites", pressed: true })).toBeInTheDocument();
    expect(storedHistory()[0].favorite).toBe(true);
    expect(storedHistory()).toHaveLength(25);
    view.unmount();
    renderHistory();

    await user.click(screen.getByRole("button", { name: "Remove from favorites", pressed: true }));
    expect(screen.queryByRole("button", { name: "Remove from favorites" })).not.toBeInTheDocument();
    expect(storedHistory()[0].favorite).toBe(false);
    expect(storedHistory()[0].source).toBe("SELECT source_01");
    expect(storedHistory()[0].target).toBe("SELECT target_01");
  });

  it("filters favorites and resets to page one when the search or filter changes", async () => {
    const items = historyItems().map((item, index) => ({ ...item, favorite: index < 12 }));
    const user = userEvent.setup();
    renderHistory(items);
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Favorites" }));

    expect(screen.getByRole("button", { name: "Favorites", pressed: true })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All", pressed: false })).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 2")).toBeInTheDocument();
    expect(screen.getByText("Showing 1–10 of 12")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Page 2 of 2")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Remove from favorites" })).toHaveLength(2);
    expect(screen.queryByText(items[12].source)).not.toBeInTheDocument();

    const search = screen.getByRole("textbox", { name: "Search conversion history" });
    await user.type(search, "source_12");
    expect(screen.getByText("Page 1 of 1")).toBeInTheDocument();
    expect(screen.getByText("Showing 1–1 of 1")).toBeInTheDocument();
    expect(screen.getByText(items[11].source)).toBeInTheDocument();
    await user.clear(search);
    expect(screen.getByText("Page 1 of 2")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "All" }));
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
    expect(screen.getByText("Showing 1–10 of 25")).toBeInTheDocument();
  });

  it("keeps the current All page when a favorite is toggled", async () => {
    const user = userEvent.setup();
    renderHistory(historyItems());
    const search = screen.getByRole("textbox", { name: "Search conversion history" });
    await user.type(search, "source_");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getAllByRole("button", { name: "Add to favorites" })[0]);

    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();
    expect(search).toHaveValue("source_");
    expect(screen.getByText("SELECT source_11")).toBeInTheDocument();
    expect(storedHistory()[10].favorite).toBe(true);
    await user.click(screen.getByRole("button", { name: "Remove from favorites" }));
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();
    expect(storedHistory()[10].favorite).toBe(false);
  });

  it("keeps the Favorites filter and current page when unfavoriting leaves the page in range", async () => {
    const user = userEvent.setup();
    renderHistory(historyItems().map((item) => ({ ...item, favorite: true })));
    await user.click(screen.getByRole("button", { name: "Favorites" }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getAllByRole("button", { name: "Remove from favorites" })[0]);

    expect(screen.getByRole("button", { name: "Favorites", pressed: true })).toBeInTheDocument();
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();
    expect(screen.getByText("Showing 11–20 of 24")).toBeInTheDocument();
    expect(screen.getByText("SELECT source_12")).toBeInTheDocument();
    expect(screen.queryByText("SELECT source_11")).not.toBeInTheDocument();
  });

  it("clamps an emptied final Favorites page without changing the active filter", async () => {
    const user = userEvent.setup();
    renderHistory(historyItems(11).map((item) => ({ ...item, favorite: true })));
    await user.click(screen.getByRole("button", { name: "Favorites" }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Remove from favorites" }));

    expect(screen.getByRole("button", { name: "Favorites", pressed: true })).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 1")).toBeInTheDocument();
    expect(screen.getByText("Showing 1–10 of 10")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Use in Convert" })).toHaveLength(10);
    expect(storedHistory()).toHaveLength(11);
    expect(storedHistory()[10].favorite).toBe(false);
  });

  it("clamps the current page after deleting its final record", async () => {
    const user = userEvent.setup();
    renderHistory(historyItems(11));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Remove" }));

    expect(screen.getByText("Page 1 of 1")).toBeInTheDocument();
    expect(screen.getByText("Showing 1–10 of 10")).toBeInTheDocument();
    expect(screen.getByText("SELECT source_01")).toBeInTheDocument();
    expect(storedHistory()).toHaveLength(10);
  });

  it("clears all history from a later page and remains empty after remount", async () => {
    const user = userEvent.setup();
    const view = renderHistory(historyItems());
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Clear local history" }));

    expect(screen.getByText("No local history yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear local history" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Use in Convert" })).not.toBeInTheDocument();
    expect(storedHistory()).toEqual([]);
    view.unmount();
    renderHistory();
    expect(screen.getByText("No local history yet")).toBeInTheDocument();
  });

  it("distinguishes missing history, missing favorites, and search results without matches", async () => {
    const user = userEvent.setup();
    const empty = renderHistory([]);
    expect(screen.getByText("No local history yet")).toBeInTheDocument();
    empty.unmount();
    renderHistory(historyItems());
    await user.click(screen.getByRole("button", { name: "Favorites" }));
    expect(screen.getByText("No favorites yet")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "All" }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    const search = screen.getByRole("textbox", { name: "Search conversion history" });
    await user.type(search, "no-such-record");
    expect(screen.getByText("No matching history")).toBeInTheDocument();
    await user.clear(search);
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
  });

  it("allows starring truncated previews while keeping copy and workspace actions disabled", async () => {
    const user = userEvent.setup();
    renderHistory(historyItems(1).map((item) => ({ ...item, truncated: true })));

    expect(screen.getByRole("button", { name: "Copy" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Use in Convert" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Use in Diff" })).toBeDisabled();
    expect(screen.getByText("Preview truncated; actions disabled")).toBeInTheDocument();
    const favorite = screen.getByRole("button", { name: "Add to favorites" });
    expect(favorite).toBeEnabled();
    await user.click(favorite);

    expect(screen.getByRole("button", { name: "Remove from favorites", pressed: true })).toBeEnabled();
    expect(storedHistory()[0]).toMatchObject({ favorite: true, truncated: true });
    expect(screen.getByRole("button", { name: "Copy" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Use in Convert" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Use in Diff" })).toBeDisabled();
  });

  it.each(["QuotaExceededError", "SecurityError"])("keeps favorites and pagination usable when persistence fails with %s", async (errorName) => {
    localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(historyItems()));
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("Storage unavailable", errorName); });
    const user = userEvent.setup();
    renderHistory();
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getAllByRole("button", { name: "Add to favorites" })[0]);

    expect(screen.getByRole("button", { name: "Remove from favorites", pressed: true })).toBeInTheDocument();
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Page 3 of 3")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Favorites" }));
    expect(screen.getByText("SELECT source_11")).toBeInTheDocument();
    expect(screen.getByText("Showing 1–1 of 1")).toBeInTheDocument();
  });

  it("renders safely when browser storage cannot be read", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new DOMException("Storage unavailable", "SecurityError"); });
    renderHistory();

    expect(screen.getByText("No local history yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear local history" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Favorites" }));
    expect(screen.getByRole("button", { name: "Favorites", pressed: true })).toBeInTheDocument();
  });
});
