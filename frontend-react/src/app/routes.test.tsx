import { render, screen } from "@testing-library/react";
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
});
