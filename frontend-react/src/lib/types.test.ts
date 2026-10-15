import { describe, expect, it } from "vitest";
import { ALL_DIALECTS, DIALECT_LABELS } from "./types";
import { normalizeTypeMappings } from "./api";

describe("dialect registry", () => {
  it("exposes the complete twelve-dialect matrix", () => {
    expect(ALL_DIALECTS).toHaveLength(12);
    expect(new Set(ALL_DIALECTS).size).toBe(12);
    expect(ALL_DIALECTS.every((dialect) => DIALECT_LABELS[dialect])).toBe(true);
  });

  it("normalizes the API's keyed type matrix for React consumers", () => {
    const response = normalizeTypeMappings({
      mappings: {
        VARCHAR: { type: "VARCHAR", source: "VARCHAR(n)", target: "VARCHAR(n)" },
        INT: { type: "INT", source: "INT", target: "INTEGER" },
      },
      type_count: 2,
    });
    expect(response.mappings).toHaveLength(2);
    expect(response.mappings.map((item) => item.type_name)).toEqual(["VARCHAR", "INT"]);
    expect(response.mappings[1].source).toBe("INT");
  });

  it("accepts the array shape used by older API deployments", () => {
    const response = normalizeTypeMappings({ mappings: [{ type_name: "DATE", source: "DATE", target: "DATE" }] });
    expect(response.mappings).toEqual([{ type_name: "DATE", source: "DATE", target: "DATE" }]);
    expect(response.type_count).toBe(1);
  });
});
