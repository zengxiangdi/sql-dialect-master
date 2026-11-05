import type {
  CompositeSchemaRelationship,
  LegacySchemaRelationship,
  SchemaColumnPair,
  SchemaDefinition,
  SchemaRelationship,
} from "./types";
import { describe, expect, it } from "vitest";

describe("schema relationship types", () => {
  it("accepts legacy and composite relationship definitions", () => {
    const legacy: SchemaRelationship = {
      from_table: "orders",
      from_column: "user_id",
      to_table: "users",
      to_column: "id",
    } satisfies LegacySchemaRelationship;
    const pair: SchemaColumnPair = {
      from_column: "tenant_id",
      to_column: "tenant_id",
    };
    const composite: SchemaRelationship = {
      from_table: "orders",
      to_table: "users",
      columns: [pair, { from_column: "user_id", to_column: "id" }],
    } satisfies CompositeSchemaRelationship;
    const schema: SchemaDefinition = {
      tables: [{ name: "orders" }, { name: "users" }],
      relationships: [legacy, composite],
    };
    expect(schema.relationships).toHaveLength(2);
  });

  it("rejects mixed and partial relationship shapes at compile time", () => {
    // @ts-expect-error legacy and composite fields are mutually exclusive
    const mixed: SchemaRelationship = {
      from_table: "orders",
      from_column: "user_id",
      to_table: "users",
      to_column: "id",
      columns: [{ from_column: "tenant_id", to_column: "tenant_id" }],
    };
    // @ts-expect-error composite relationships require a columns array
    const partial: SchemaRelationship = {
      from_table: "orders",
      to_table: "users",
    };
    expect(mixed).toBeDefined();
    expect(partial).toBeDefined();
  });
});
