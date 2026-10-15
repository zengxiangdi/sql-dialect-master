import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AppRoutes } from "./routes";
import { AppProvider } from "../lib/app-context";

describe("React workspace shell", () => {
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
    expect(screen.getByText("mysql")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /clear local history/i }));
    expect(screen.getByText("No local history yet")).toBeInTheDocument();
    expect(localStorage.getItem("sdm.history")).toBe("[]");
  });
});
