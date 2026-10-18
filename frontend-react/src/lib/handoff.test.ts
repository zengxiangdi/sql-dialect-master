import { afterEach, describe, expect, it, vi } from "vitest";
import {
  readAnalysisHandoff,
  readConvertHandoff,
  readDiffHandoff,
  writeAnalysisHandoff,
  writeConvertHandoff,
  writeDiffHandoff,
} from "./handoff";
import { DRAFT_MAX_CHARS, safeGetItem } from "./storage";

describe("workspace handoff storage", () => {
  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("round-trips valid handoff payloads", () => {
    expect(writeConvertHandoff({ sql: "SELECT 1", sourceDialect: "mysql", targetDialect: "postgres" })).toBe(true);
    expect(readConvertHandoff()).toEqual({ sql: "SELECT 1", sourceDialect: "mysql", targetDialect: "postgres" });
    expect(writeDiffHandoff({ sourceSql: "SELECT 1", targetSql: "SELECT 1", sourceDialect: "postgres", targetDialect: "mysql" })).toBe(true);
    expect(readDiffHandoff()?.targetDialect).toBe("mysql");
    expect(writeAnalysisHandoff({ sql: "SELECT 1", dialect: "postgres" })).toBe(true);
    expect(readAnalysisHandoff()?.dialect).toBe("postgres");
  });

  it("rejects malformed, incomplete, and unknown-dialect payloads", () => {
    localStorage.setItem("sdm.handoff.convert", "{");
    expect(readConvertHandoff()).toBeNull();
    localStorage.setItem("sdm.handoff.convert", JSON.stringify({ sql: "SELECT 1", sourceDialect: "invalid", targetDialect: "mysql" }));
    expect(readConvertHandoff()).toBeNull();
    localStorage.setItem("sdm.handoff.diff", JSON.stringify({ sourceSql: "SELECT 1", sourceDialect: "postgres", targetDialect: "mysql" }));
    expect(readDiffHandoff()).toBeNull();
  });

  it("fails safely on quota errors and rejects oversized SQL", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("full", "QuotaExceededError");
    });
    expect(writeAnalysisHandoff({ sql: "SELECT 1", dialect: "postgres" })).toBe(false);
    expect(safeGetItem("sdm.handoff.analysis")).toBeNull();

    vi.restoreAllMocks();
    expect(writeAnalysisHandoff({ sql: "x".repeat(DRAFT_MAX_CHARS + 1), dialect: "postgres" })).toBe(false);
    expect(readAnalysisHandoff()).toBeNull();
  });
});
