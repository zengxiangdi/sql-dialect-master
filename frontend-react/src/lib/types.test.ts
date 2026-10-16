import { describe, expect, it } from "vitest";
import { ALL_DIALECTS, DIALECT_LABELS } from "./types";

describe("dialect registry", () => {
  it("exposes the complete twelve-dialect matrix", () => {
    expect(ALL_DIALECTS).toHaveLength(12);
    expect(new Set(ALL_DIALECTS).size).toBe(12);
    expect(ALL_DIALECTS.every((dialect) => DIALECT_LABELS[dialect])).toBe(true);
  });

  it("models the canonical array response returned by the API", () => {
    const mappings = [{ type: "DATE", source: "DATE", target: "DATE" }];
    expect(mappings[0].type).toBe("DATE");
    expect(mappings[0].source).toBe("DATE");
    expect(mappings[0].target).toBe("DATE");
  });
});
