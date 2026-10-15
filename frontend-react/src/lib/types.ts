export type Dialect =
  | "hive" | "mysql" | "oracle" | "tsql" | "postgres" | "spark"
  | "trino" | "snowflake" | "redshift" | "clickhouse" | "duckdb" | "databricks";

export type Theme = "dark" | "light";
export type Status = "success" | "warning" | "error" | "neutral";

export interface DialectDetail {
  id: Dialect;
  name: string;
  icon: string;
  category?: string;
}

export interface DialectsResponse {
  success: boolean;
  dialects: Dialect[];
  details: Record<string, { name: string; icon: string; category: string }>;
  by_category: Record<string, DialectDetail[]>;
}

export interface ConvertResponse {
  success: boolean;
  source_sql: string;
  target_sql: string | null;
  source_dialect: Dialect;
  target_dialect: Dialect;
  error: string | null;
  error_code: string | null;
  compatibility_notes: string[];
  transformations: string[];
  warnings: string[];
  target_validation_state: "target_valid" | "generic_only" | "invalid";
  timestamp?: string;
}

export interface Nl2SqlResponse {
  success: boolean;
  input_text: string;
  sql: string | null;
  dialect: Dialect;
  explanation: string;
  confidence: number;
  suggestions: string[];
  parameter_style?: string | null;
  parameters?: string[];
  evidence?: Record<string, unknown> | null;
}

export interface ParseResponse {
  success: boolean;
  dialect: Dialect;
  elements: {
    query_type?: string;
    tables?: Array<{ name: string; alias?: string | null }>;
    columns?: Array<{ name: string; table?: string | null }>;
    functions?: Array<{ name: string }>;
    joins?: Array<{ type: string; table: string; on_condition?: string }>;
    has_cte?: boolean;
    has_window?: boolean;
    has_aggregation?: boolean;
    has_order_by?: boolean;
    has_limit?: boolean;
  };
}

export interface FunctionItem {
  name: string;
  category: string;
  description?: string;
  syntax?: string;
  dialects?: Record<string, string>;
}

export interface TypeMapping {
  type_name?: string;
  canonical_type?: string;
  [dialect: string]: unknown;
}

export interface HistoryItem {
  id: string;
  source: string;
  target: string;
  sourceDialect: Dialect;
  targetDialect: Dialect;
  createdAt: string;
  status: Status;
}

export const DIALECT_LABELS: Record<Dialect, string> = {
  mysql: "MySQL", postgres: "PostgreSQL", oracle: "Oracle", tsql: "SQL Server",
  hive: "Hive", spark: "Spark SQL", trino: "Trino", snowflake: "Snowflake",
  redshift: "Redshift", clickhouse: "ClickHouse", duckdb: "DuckDB", databricks: "Databricks",
};

export const DIALECT_ICONS: Record<Dialect, string> = {
  mysql: "🐬", postgres: "🐘", oracle: "🔴", tsql: "▣", hive: "🐝", spark: "⚡",
  trino: "◇", snowflake: "❄", redshift: "◆", clickhouse: "⌂", duckdb: "🦆", databricks: "▦",
};

export const ALL_DIALECTS = Object.keys(DIALECT_LABELS) as Dialect[];
