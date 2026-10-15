import { describe, expect, it } from "vitest";
import { ALL_DIALECTS, DIALECT_LABELS } from "./types";

describe("dialect registry", () => {
  it("exposes the complete twelve-dialect matrix", () => {
    expect(ALL_DIALECTS).toHaveLength(12);
    expect(new Set(ALL_DIALECTS).size).toBe(12);
    expect(ALL_DIALECTS.every((dialect) => DIALECT_LABELS[dialect])).toBe(true);
  });
});
