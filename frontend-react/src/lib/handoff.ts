import { ALL_DIALECTS, type Dialect } from "./types";
import {
  DRAFT_MAX_CHARS,
  safeGetJson,
  safeRemoveItem,
  safeSetJson,
} from "./storage";

export const HANDOFF_KEYS = {
  convert: "sdm.handoff.convert",
  diff: "sdm.handoff.diff",
  analysis: "sdm.handoff.analysis",
  lineage: "sdm.handoff.lineage",
} as const;

export interface ConvertHandoff {
  sql: string;
  sourceDialect: Dialect;
  targetDialect: Dialect;
}

export interface DiffHandoff {
  sourceSql: string;
  targetSql: string;
  sourceDialect: Dialect;
  targetDialect: Dialect;
}

export interface QueryHandoff {
  sql: string;
  dialect: Dialect;
}

export function isDialect(value: unknown): value is Dialect {
  return typeof value === "string" && ALL_DIALECTS.includes(value as Dialect);
}

export function dialectParam(value: string | null, fallback: Dialect): Dialect {
  return isDialect(value) ? value : fallback;
}

function isSql(value: unknown): value is string {
  return typeof value === "string" && value.length <= DRAFT_MAX_CHARS;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object");
}

function readHandoff<T>(key: string, guard: (value: unknown) => value is T): T | null {
  const value = safeGetJson<unknown>(key, null);
  return guard(value) ? value : null;
}

function writeHandoff<T>(key: string, value: T): boolean {
  return safeSetJson(key, value);
}

export function readConvertHandoff(): ConvertHandoff | null {
  return readHandoff(HANDOFF_KEYS.convert, (value): value is ConvertHandoff => Boolean(
    isRecord(value) &&
    isSql(value.sql) && isDialect(value.sourceDialect) && isDialect(value.targetDialect),
  ));
}

export function writeConvertHandoff(value: ConvertHandoff): boolean {
  return isSql(value.sql) && isDialect(value.sourceDialect) && isDialect(value.targetDialect)
    ? writeHandoff(HANDOFF_KEYS.convert, value)
    : false;
}

export function readDiffHandoff(): DiffHandoff | null {
  return readHandoff(HANDOFF_KEYS.diff, (value): value is DiffHandoff => Boolean(
    isRecord(value) &&
    isSql(value.sourceSql) && isSql(value.targetSql) &&
    isDialect(value.sourceDialect) && isDialect(value.targetDialect),
  ));
}

export function writeDiffHandoff(value: DiffHandoff): boolean {
  return isSql(value.sourceSql) && isSql(value.targetSql) &&
    isDialect(value.sourceDialect) && isDialect(value.targetDialect)
    ? writeHandoff(HANDOFF_KEYS.diff, value)
    : false;
}

function readQueryHandoff(key: string): QueryHandoff | null {
  return readHandoff(key, (value): value is QueryHandoff => Boolean(
    isRecord(value) && isSql(value.sql) && isDialect(value.dialect),
  ));
}

function writeQueryHandoff(key: string, value: QueryHandoff): boolean {
  return isSql(value.sql) && isDialect(value.dialect)
    ? writeHandoff(key, value)
    : false;
}

export const readAnalysisHandoff = () => readQueryHandoff(HANDOFF_KEYS.analysis);
export const writeAnalysisHandoff = (value: QueryHandoff) => writeQueryHandoff(HANDOFF_KEYS.analysis, value);
export const readLineageHandoff = () => readQueryHandoff(HANDOFF_KEYS.lineage);
export const writeLineageHandoff = (value: QueryHandoff) => writeQueryHandoff(HANDOFF_KEYS.lineage, value);

export function clearHandoff(key: keyof typeof HANDOFF_KEYS): boolean {
  return safeRemoveItem(HANDOFF_KEYS[key]);
}
