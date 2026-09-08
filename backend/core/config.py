#!/usr/bin/env python3
"""Centralized configuration for SQL Dialect Master.

All configuration constants and settings are defined here for consistency
across all modules.

Supports configuration via:
- Environment variables (prefix: SDM_)
- .env file in project root
- Default values
"""
import logging
import os
import sys
from pathlib import Path
from typing import List, Dict, Any, TypedDict, Optional
from enum import Enum
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# =============================================================================
# Logging Configuration
# =============================================================================

def setup_logging(
    level: int = logging.INFO,
    format_string: str = None,
    log_file: str = None
) -> logging.Logger:
    """Configure logging for SQL Dialect Master.
    
    Args:
        level: Logging level (default: INFO)
        format_string: Custom format string
        log_file: Optional file path for logging
        
    Returns:
        Root logger for the package
    """
    if format_string is None:
        format_string = (
            "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s"
        )
    
    formatter = logging.Formatter(format_string, datefmt="%Y-%m-%d %H:%M:%S")
    root_logger = logging.getLogger("backend")
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    return root_logger


logger = logging.getLogger(__name__)

# =============================================================================
# Supported Dialects - Single Source of Truth
# =============================================================================

SUPPORTED_DIALECTS: List[str] = [
    "hive", "mysql", "oracle", "tsql", "postgres", "spark",
    "trino", "snowflake", "redshift", "clickhouse", "duckdb", "databricks"
]

class DialectCategory(Enum):
    """Database dialect categories."""
    RDBMS = "RDBMS"
    BIG_DATA = "Big Data"
    CLOUD_DW = "Cloud DW"
    OLAP = "OLAP"
    EMBEDDED = "Embedded"

from dataclasses import dataclass

@dataclass
class DialectInfo:
    """Information about a SQL dialect."""
    id: str
    name: str
    icon: str
    category: DialectCategory
    color: str
    description: str = ""

DIALECT_METADATA: Dict[str, DialectInfo] = {
    "hive": DialectInfo("hive", "Apache Hive", "🐝", DialectCategory.BIG_DATA, "#FDEE21", "Hadoop data warehouse"),
    "mysql": DialectInfo("mysql", "MySQL", "🐬", DialectCategory.RDBMS, "#00758F", "Popular open-source RDBMS"),
    "oracle": DialectInfo("oracle", "Oracle Database", "🔴", DialectCategory.RDBMS, "#F80000", "Enterprise RDBMS"),
    "tsql": DialectInfo("tsql", "SQL Server (T-SQL)", "🟦", DialectCategory.RDBMS, "#CC2927", "Microsoft SQL Server"),
    "postgres": DialectInfo("postgres", "PostgreSQL", "🐘", DialectCategory.RDBMS, "#336791", "Advanced open-source RDBMS"),
    "spark": DialectInfo("spark", "Apache Spark SQL", "⚡", DialectCategory.BIG_DATA, "#E25A1C", "Distributed SQL engine"),
    "trino": DialectInfo("trino", "Trino (Presto)", "🔷", DialectCategory.BIG_DATA, "#DD00A1", "Distributed SQL query engine"),
    "snowflake": DialectInfo("snowflake", "Snowflake", "❄️", DialectCategory.CLOUD_DW, "#29B5E8", "Cloud data platform"),
    "redshift": DialectInfo("redshift", "Amazon Redshift", "🔶", DialectCategory.CLOUD_DW, "#8C4FFF", "AWS data warehouse"),
    "clickhouse": DialectInfo("clickhouse", "ClickHouse", "🏠", DialectCategory.OLAP, "#FFCC00", "Column-oriented OLAP"),
    "duckdb": DialectInfo("duckdb", "DuckDB", "🦆", DialectCategory.EMBEDDED, "#FFF000", "In-process analytical DB"),
    "databricks": DialectInfo("databricks", "Databricks SQL", "🧱", DialectCategory.BIG_DATA, "#FF3621", "Unified analytics platform"),
}


def get_dialect_ui_info() -> Dict[str, Dict[str, str]]:
    """Get dialect info formatted for UI display."""
    return {
        d.id: {"icon": d.icon, "name": d.name, "color": d.color}
        for d in DIALECT_METADATA.values()
    }


def get_dialect_api_info() -> Dict[str, Dict[str, str]]:
    """Get dialect info formatted for API responses."""
    return {
        d.id: {"icon": d.icon, "name": d.name, "category": d.category.value}
        for d in DIALECT_METADATA.values()
    }


def get_dialect_label(dialect: str) -> str:
    """Get formatted dialect label with icon for display."""
    info = DIALECT_METADATA.get(dialect)
    if info:
        return f"{info.icon} {dialect.upper()}"
    return f"📄 {dialect.upper()}"


# =============================================================================
# Type Definitions for Type Safety
# =============================================================================

class FunctionParameter(TypedDict):
    """Function parameter definition."""
    name: str
    type: str
    required: bool
    description: str

class FunctionInfo(TypedDict, total=False):
    """SQL function information."""
    name: str
    category: str
    description: str
    parameters: List[FunctionParameter]
    dialects: Dict[str, str]
    examples: Dict[str, str]
    notes: str

class TypeMappingInfo(TypedDict, total=False):
    """Type mapping information."""
    hive: str
    mysql: str
    oracle: str
    tsql: str
    postgres: str
    spark: str
    trino: str
    snowflake: str
    redshift: str
    clickhouse: str
    duckdb: str
    databricks: str
    notes: str

class TranspileResultDict(TypedDict, total=False):
    """Transpile result dictionary."""
    success: bool
    source_sql: str
    target_sql: Optional[str]
    source_dialect: str
    target_dialect: str
    error: Optional[str]
    error_code: Optional[str]
    compatibility_notes: List[str]
    transformations: List[str]
    warnings: List[str]


# =============================================================================
# Application Settings (Pydantic)
# =============================================================================

class AppSettings(BaseSettings):
    """Application settings using Pydantic.
    
    All settings can be overridden via environment variables with SDM_ prefix.
    Example: SDM_CACHE_ENABLED=false
    """
    model_config = SettingsConfigDict(
        env_prefix="SDM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # API settings
    api_version: str = "1.0.1"
    api_title: str = "SQL Dialect Master API"
    allowed_origins: str = (
        "http://localhost:8501,http://localhost:8000,"
        "http://127.0.0.1:8501,http://127.0.0.1:8000"
    )
    max_batch_size: int = 100
    request_timeout: int = 30
    
    # Cache settings
    cache_enabled: bool = True
    cache_ttl: int = 300
    cache_max_size: int = Field(1000, gt=0)
    
    # Rate limiting
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 100
    rate_limit_window: int = 60
    
    # NL2SQL settings
    nl2sql_confidence_threshold: float = 0.6
    nl2sql_max_suggestions: int = 5
    
    # Transpiler settings
    transpiler_pretty_default: bool = True
    transpiler_max_sql_length: int = 100000
    
    # Function encyclopedia
    function_search_limit: int = 50
    function_fuzzy_threshold: float = 0.4
    
    # Security settings
    security_check_enabled: bool = True
    security_block_dangerous: bool = False
    
    # Logging settings
    log_level: str = "INFO"
    log_file: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert settings to dictionary."""
        return self.model_dump()


settings = AppSettings()


# =============================================================================
# Security Patterns for SQL Validation
# =============================================================================

import re

_DANGEROUS_SQL_PATTERNS_RAW: List[tuple] = [
    (r";\s*(DROP|DELETE|TRUNCATE|ALTER|CREATE|INSERT|UPDATE)\s+", 
     "Multiple statements with dangerous operations detected"),
    (r"--\s*.*\s*(DROP|DELETE|TRUNCATE)", 
     "SQL comment may hide dangerous operation"),
    (r"UNION\s+(ALL\s+)?SELECT\s+.*(FROM\s+information_schema|FROM\s+sys\.|@@version|user\(\))",
     "Potential SQL injection pattern detected"),
    (r"(information_schema|sys\.tables|sysobjects|pg_catalog|all_tables)",
     "System table access detected"),
    (r"(xp_cmdshell|sp_executesql|EXEC\s*\(|EXECUTE\s+IMMEDIATE)",
     "Command execution attempt detected"),
    (r"(INTO\s+OUTFILE|INTO\s+DUMPFILE|LOAD_FILE|UTL_FILE)",
     "File operation detected"),
    (r"\bOR\s+['\"]?1['\"]?\s*=\s*['\"]?1['\"]?",
     "Classic OR 1=1 injection pattern detected"),
    (r"\bOR\s+['\"][\w]+['\"]\s*=\s*['\"][\w]+['\"]",
     "OR string comparison injection pattern detected"),
    (r"\b(AND|OR)\s+\d+\s*=\s*\d+",
     "Tautology attack pattern detected"),
    (r"0x[0-9a-fA-F]{8,}",
     "Suspicious hex-encoded value detected"),
    (r";\s*SELECT\s+",
     "Stacked query injection pattern detected"),
    (r"(SLEEP\s*\(\s*\d+\s*\)|BENCHMARK\s*\(|WAITFOR\s+DELAY|PG_SLEEP)",
     "Timing-based attack pattern detected"),
    (r"(SHOW\s+DATABASES|SHOW\s+TABLES|DESCRIBE\s+|SP_COLUMNS)",
     "Database enumeration attempt detected"),
]

_WARNING_SQL_PATTERNS_RAW: List[tuple] = [
    (r"DELETE\s+FROM\s+\w+\s*(?!WHERE)", 
     "DELETE without WHERE clause - will affect all rows"),
    (r"UPDATE\s+\w+\s+SET\s+.*(?!WHERE)",
     "UPDATE without WHERE clause - will affect all rows"),
    (r"DROP\s+(TABLE|DATABASE|SCHEMA|INDEX|VIEW)",
     "DROP operation detected - data loss risk"),
    (r"TRUNCATE\s+TABLE",
     "TRUNCATE operation detected - data loss risk"),
    (r"(GRANT|REVOKE)\s+",
     "Permission modification detected"),
    (r"LIMIT\s+\d{6,}",
     "Very large LIMIT value may impact performance"),
    (r"SELECT\s+\*\s+FROM",
     "SELECT * detected - consider specifying columns explicitly"),
]

DANGEROUS_SQL_PATTERNS: List[tuple] = [
    (re.compile(pattern, re.IGNORECASE | re.MULTILINE), message)
    for pattern, message in _DANGEROUS_SQL_PATTERNS_RAW
]

WARNING_SQL_PATTERNS: List[tuple] = [
    (re.compile(pattern, re.IGNORECASE | re.MULTILINE), message)
    for pattern, message in _WARNING_SQL_PATTERNS_RAW
]

# =============================================================================
# Function Categories
# =============================================================================

FUNCTION_CATEGORIES: List[str] = [
    "string", "date", "math", "aggregate", "window",
    "conditional", "conversion", "json", "array", "system", "geo"
]

CATEGORY_DESCRIPTIONS: Dict[str, str] = {
    "string": "String manipulation functions (CONCAT, SUBSTRING, TRIM, etc.)",
    "date": "Date and time functions (DATE_ADD, DATEDIFF, NOW, etc.)",
    "math": "Mathematical functions (ABS, ROUND, FLOOR, etc.)",
    "aggregate": "Aggregation functions (SUM, COUNT, AVG, etc.)",
    "window": "Window functions (ROW_NUMBER, RANK, LAG, etc.)",
    "conditional": "Conditional functions (CASE, IF, COALESCE, etc.)",
    "conversion": "Type conversion functions (CAST, CONVERT, etc.)",
    "json": "JSON manipulation functions (JSON_EXTRACT, etc.)",
    "array": "Array functions (EXPLODE, COLLECT_LIST, etc.)",
    "system": "System functions (VERSION, DATABASE, etc.)",
    "geo": "Geospatial functions (ST_DISTANCE, ST_CONTAINS, etc.)"
}

# =============================================================================
# Type Categories
# =============================================================================

TYPE_CATEGORIES: Dict[str, List[str]] = {
    "String Types": ["STRING", "VARCHAR", "CHAR", "TEXT", "MEDIUMTEXT", "LONGTEXT"],
    "Numeric Types": ["BIGINT", "INT", "SMALLINT", "TINYINT", "DOUBLE", "FLOAT", "DECIMAL", "MONEY", "SERIAL"],
    "Boolean & Bit": ["BOOLEAN", "BIT"],
    "Date/Time Types": ["DATE", "TIME", "TIMESTAMP", "TIMESTAMP_TZ", "INTERVAL", "YEAR"],
    "Complex Types": ["ARRAY", "MAP", "STRUCT", "JSON", "JSONB", "XML"],
    "Binary Types": ["BINARY"],
    "Special Types": ["UUID", "INET", "GEOMETRY", "GEOGRAPHY", "ENUM", "SET"]
}

# =============================================================================
# Compatibility Notes Database
# =============================================================================

COMPATIBILITY_NOTES: Dict[tuple, List[str]] = {
    ("hive", "mysql"): [
        "Hive ARRAY/MAP types converted to JSON",
        "LATERAL VIEW EXPLODE may need manual adjustment",
        "Hive STRING maps to VARCHAR(65535) or TEXT"
    ],
    ("hive", "oracle"): [
        "Hive ARRAY/MAP types converted to JSON/VARRAY",
        "LATERAL VIEW EXPLODE → JSON_TABLE transformation",
        "Hive STRING maps to CLOB or VARCHAR2(4000)"
    ],
    ("hive", "postgres"): [
        "LATERAL VIEW EXPLODE → UNNEST transformation",
        "Hive MAP → JSONB recommended",
        "COLLECT_LIST → ARRAY_AGG"
    ],
    ("hive", "tsql"): [
        "Hive ARRAY → JSON or table-valued parameter",
        "LIMIT → TOP or OFFSET FETCH",
        "Hive STRING → NVARCHAR(MAX)"
    ],
    ("hive", "snowflake"): [
        "LATERAL VIEW EXPLODE → LATERAL FLATTEN",
        "Hive STRUCT → OBJECT type",
        "DATE_ADD syntax differs"
    ],
    ("hive", "spark"): [
        "Most syntax compatible",
        "Check UDF compatibility",
        "Spark may have additional optimizations"
    ],
    ("oracle", "hive"): [
        "LISTAGG → ARRAY_JOIN(COLLECT_LIST()) transformation",
        "CONNECT BY → WITH RECURSIVE transformation",
        "Oracle NUMBER → Hive DECIMAL with precision check"
    ],
    ("oracle", "mysql"): [
        "NVL → IFNULL or COALESCE",
        "DECODE → CASE WHEN",
        "ROWNUM → LIMIT"
    ],
    ("oracle", "postgres"): [
        "NVL → COALESCE",
        "SYSDATE → CURRENT_TIMESTAMP",
        "DECODE → CASE WHEN"
    ],
    ("mysql", "postgres"): [
        "GROUP_CONCAT → STRING_AGG transformation",
        "IFNULL → COALESCE transformation",
        "AUTO_INCREMENT → SERIAL/IDENTITY"
    ],
    ("mysql", "oracle"): [
        "LIMIT → FETCH FIRST or ROWNUM",
        "NOW() → SYSDATE",
        "IFNULL → NVL"
    ],
    ("mysql", "hive"): [
        "AUTO_INCREMENT not supported in Hive",
        "JSON functions syntax differs",
        "DATE_FORMAT patterns differ"
    ],
    ("tsql", "mysql"): [
        "STRING_AGG → GROUP_CONCAT transformation",
        "TOP → LIMIT transformation",
        "GETDATE() → NOW() transformation"
    ],
    ("tsql", "postgres"): [
        "TOP → LIMIT",
        "GETDATE() → CURRENT_TIMESTAMP",
        "ISNULL → COALESCE"
    ],
    ("tsql", "hive"): [
        "TOP → LIMIT",
        "CROSS/OUTER APPLY → LATERAL VIEW",
        "STRING_AGG → CONCAT_WS(COLLECT_LIST())"
    ],
    ("postgres", "mysql"): [
        "STRING_AGG → GROUP_CONCAT transformation",
        "ARRAY types → JSON transformation",
        "SERIAL → AUTO_INCREMENT"
    ],
    ("postgres", "oracle"): [
        "ARRAY_AGG → LISTAGG",
        "CURRENT_TIMESTAMP → SYSDATE",
        "LIMIT → FETCH FIRST"
    ],
    ("postgres", "hive"): [
        "ARRAY_AGG → COLLECT_LIST",
        "UNNEST → LATERAL VIEW EXPLODE",
        "STRING_AGG → CONCAT_WS(COLLECT_LIST())"
    ],
    ("spark", "hive"): [
        "Most syntax compatible",
        "Check Spark-specific functions",
        "DataFrame operations need conversion"
    ],
    ("spark", "snowflake"): [
        "EXPLODE → LATERAL FLATTEN",
        "COLLECT_LIST → ARRAY_AGG",
        "Spark UDFs not supported"
    ],
    ("spark", "trino"): [
        "Most syntax compatible",
        "COLLECT_LIST → ARRAY_AGG",
        "Check function availability"
    ],
    ("snowflake", "postgres"): [
        "FLATTEN → UNNEST",
        "VARIANT → JSONB",
        "PARSE_JSON → ::JSONB cast"
    ],
    ("snowflake", "hive"): [
        "FLATTEN → LATERAL VIEW EXPLODE",
        "VARIANT → STRING (JSON)",
        "OBJECT → STRUCT"
    ],
    ("trino", "postgres"): [
        "ROW → composite type",
        "ARRAY syntax compatible",
        "Check function names"
    ],
    ("trino", "hive"): [
        "ROW → STRUCT",
        "Most syntax compatible",
        "Check UDF availability"
    ],
    ("clickhouse", "postgres"): [
        "Array JOIN → UNNEST",
        "groupArray → ARRAY_AGG",
        "ClickHouse-specific functions need alternatives"
    ],
    ("clickhouse", "mysql"): [
        "Array JOIN → JSON_TABLE",
        "groupArray → JSON_ARRAYAGG",
        "DateTime64 → DATETIME(6)"
    ],
    ("redshift", "postgres"): [
        "SUPER → JSONB",
        "GETDATE → CURRENT_TIMESTAMP",
        "Most syntax compatible"
    ],
    ("redshift", "snowflake"): [
        "SUPER → VARIANT",
        "Similar cloud DW syntax",
        "Check function availability"
    ],
    ("duckdb", "postgres"): [
        "LIST → ARRAY",
        "Most syntax compatible",
        "Check extension functions"
    ],
    ("duckdb", "hive"): [
        "LIST → ARRAY",
        "STRUCT syntax similar",
        "Check function availability"
    ],
    ("databricks", "spark"): [
        "Fully compatible",
        "Databricks-specific features may not transfer",
        "Unity Catalog references need adjustment"
    ],
    ("databricks", "hive"): [
        "Most syntax compatible",
        "Delta Lake features not supported",
        "Check function availability"
    ],
}


def get_compatibility_notes(source: str, target: str) -> List[str]:
    """Get compatibility notes for a dialect pair."""
    return COMPATIBILITY_NOTES.get((source.lower(), target.lower()), [])
