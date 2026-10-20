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

export interface SchemaColumn {
  name: string;
  type?: string | null;
}

export interface SchemaTable {
  name: string;
  columns?: SchemaColumn[];
}

export interface SchemaRelationship {
  from_table: string;
  from_column: string;
  to_table: string;
  to_column: string;
}

export interface SchemaDefinition {
  tables?: SchemaTable[];
  relationships?: SchemaRelationship[];
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
  provider?: "deterministic" | "llm";
  model?: string | null;
  fallback_reason?: string | null;
  schema_used?: boolean;
}

export interface ParseResponse {
  success: boolean;
  dialect: Dialect;
  elements: {
    query_type?: string;
    tables?: Array<{ name: string; alias?: string | null; schema?: string | null; catalog?: string | null }>;
    columns?: Array<{ name: string; table?: string | null; alias?: string | null }>;
    functions?: Array<{ name: string }>;
    joins?: Array<{ type: string; table: string; on_condition?: string | null }>;
    has_cte?: boolean;
    has_window?: boolean;
    has_aggregation?: boolean;
    has_order_by?: boolean;
    has_limit?: boolean;
  };
}

export interface SemanticDifference {
  category: string;
  severity: string;
  source_fragment: string;
  target_fragment: string;
  explanation: string;
  confidence: number;
  evidence?: string | null;
}

export interface DiffResponse {
  success: boolean;
  equivalent: boolean;
  status: "equivalent" | "different" | "unknown" | "parse_error";
  source_normalized?: string | null;
  target_normalized?: string | null;
  differences: string[];
  difference_categories: string[];
  structured_differences: SemanticDifference[];
  semantic_classification?: string;
  confidence: number;
  evidence?: string | null;
  parse_error?: string | null;
  error?: string;
}

export interface FunctionItem {
  name: string;
  category: string;
  description?: string;
  syntax?: string;
  dialects?: Record<string, string>;
  parameters?: FunctionParameter[];
}

export interface FunctionParameter {
  name: string;
  type: string;
  required: boolean;
  description: string;
}

export interface FunctionDetail {
  name: string;
  category: string;
  description?: string;
  parameters?: FunctionParameter[];
  dialects: Record<string, string>;
  examples?: Record<string, string>;
  notes?: string;
}

export interface FunctionComparison {
  name: string;
  description: string | null;
  category: string;
  parameters: FunctionParameter[];
  examples: Record<string, string>;
  notes: string;
  dialects: Record<string, string>;
  availability: {
    supported: string[];
    not_supported: string[];
    coverage: string;
  };
}

export interface FunctionDetailResponse {
  success: boolean;
  function: FunctionDetail;
  comparison: FunctionComparison;
}

export interface FunctionCategory {
  name: string;
  count: number;
  description?: string;
  icon?: string;
}

export interface TypeMapping {
  type: string;
  source?: string;
  target?: string;
  notes?: string;
  category?: string;
}

export interface TypeMappingsResponse {
  success?: boolean;
  mappings: TypeMapping[];
  dialects?: Dialect[];
  type_count: number;
  precision_warnings?: unknown;
}

export interface HistoryItem {
  id: string;
  source: string;
  target: string;
  sourceDialect: Dialect;
  targetDialect: Dialect;
  createdAt: string;
  status: Status;
  truncated?: boolean;
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
