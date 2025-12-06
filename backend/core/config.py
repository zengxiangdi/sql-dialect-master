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
from dataclasses import dataclass, field
from enum import Enum


# =============================================================================
# Environment Variable Helpers
# =============================================================================

def _load_dotenv() -> None:
    """Load .env file if it exists."""
    env_file = Path(__file__).parent.parent.parent / ".env"
    if env_file.exists():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key not in os.environ:  # Don't override existing env vars
                            os.environ[key] = value
        except Exception:
            pass  # Silently ignore .env parsing errors


def _get_env(key: str, default: Any, type_cast: type = str) -> Any:
    """Get environment variable with type casting.
    
    Args:
        key: Environment variable name (without SDM_ prefix)
        default: Default value if not set
        type_cast: Type to cast the value to
        
    Returns:
        Configuration value
    """
    env_key = f"SDM_{key.upper()}"
    value = os.environ.get(env_key)
    
    if value is None:
        return default
    
    try:
        if type_cast == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif type_cast == int:
            return int(value)
        elif type_cast == float:
            return float(value)
        else:
            return value
    except (ValueError, TypeError):
        return default


# Load .env file on module import
_load_dotenv()


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
    
    # Create formatter
    formatter = logging.Formatter(format_string, datefmt="%Y-%m-%d %H:%M:%S")
    
    # Get root logger for our package
    root_logger = logging.getLogger("backend")
    root_logger.setLevel(level)
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    return root_logger


# Initialize default logger
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

@dataclass
class DialectInfo:
    """Information about a SQL dialect."""
    id: str
    name: str
    icon: str
    category: DialectCategory
    color: str
    description: str = ""

# Dialect metadata with icons and categories
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
    compatibility_notes: List[str]
    transformations: List[str]
    warnings: List[str]

# =============================================================================
# Application Settings
# =============================================================================

@dataclass
class AppSettings:
    """Application settings with defaults.
    
    All settings can be overridden via environment variables with SDM_ prefix.
    Example: SDM_CACHE_ENABLED=false, SDM_MAX_BATCH_SIZE=50
    """
    # API settings
    api_version: str = field(default_factory=lambda: _get_env("API_VERSION", "1.0.0"))
    api_title: str = field(default_factory=lambda: _get_env("API_TITLE", "SQL Dialect Master API"))
    max_batch_size: int = field(default_factory=lambda: _get_env("MAX_BATCH_SIZE", 100, int))
    request_timeout: int = field(default_factory=lambda: _get_env("REQUEST_TIMEOUT", 30, int))
    
    # Cache settings
    cache_enabled: bool = field(default_factory=lambda: _get_env("CACHE_ENABLED", True, bool))
    cache_ttl: int = field(default_factory=lambda: _get_env("CACHE_TTL", 300, int))
    cache_max_size: int = field(default_factory=lambda: _get_env("CACHE_MAX_SIZE", 1000, int))
    
    # Rate limiting
    rate_limit_enabled: bool = field(default_factory=lambda: _get_env("RATE_LIMIT_ENABLED", True, bool))
    rate_limit_requests: int = field(default_factory=lambda: _get_env("RATE_LIMIT_REQUESTS", 100, int))
    rate_limit_window: int = field(default_factory=lambda: _get_env("RATE_LIMIT_WINDOW", 60, int))
    
    # NL2SQL settings
    nl2sql_confidence_threshold: float = field(default_factory=lambda: _get_env("NL2SQL_CONFIDENCE_THRESHOLD", 0.6, float))
    nl2sql_max_suggestions: int = field(default_factory=lambda: _get_env("NL2SQL_MAX_SUGGESTIONS", 5, int))
    
    # Transpiler settings
    transpiler_pretty_default: bool = field(default_factory=lambda: _get_env("TRANSPILER_PRETTY_DEFAULT", True, bool))
    transpiler_max_sql_length: int = field(default_factory=lambda: _get_env("TRANSPILER_MAX_SQL_LENGTH", 100000, int))
    
    # Function encyclopedia
    function_search_limit: int = field(default_factory=lambda: _get_env("FUNCTION_SEARCH_LIMIT", 50, int))
    function_fuzzy_threshold: float = field(default_factory=lambda: _get_env("FUNCTION_FUZZY_THRESHOLD", 0.4, float))
    
    # Security settings
    security_check_enabled: bool = field(default_factory=lambda: _get_env("SECURITY_CHECK_ENABLED", True, bool))
    security_block_dangerous: bool = field(default_factory=lambda: _get_env("SECURITY_BLOCK_DANGEROUS", False, bool))
    
    # Logging settings
    log_level: str = field(default_factory=lambda: _get_env("LOG_LEVEL", "INFO"))
    log_file: str = field(default_factory=lambda: _get_env("LOG_FILE", ""))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert settings to dictionary."""
        return {
            "api_version": self.api_version,
            "api_title": self.api_title,
            "max_batch_size": self.max_batch_size,
            "request_timeout": self.request_timeout,
            "cache_enabled": self.cache_enabled,
            "cache_ttl": self.cache_ttl,
            "cache_max_size": self.cache_max_size,
            "rate_limit_enabled": self.rate_limit_enabled,
            "rate_limit_requests": self.rate_limit_requests,
            "rate_limit_window": self.rate_limit_window,
            "nl2sql_confidence_threshold": self.nl2sql_confidence_threshold,
            "nl2sql_max_suggestions": self.nl2sql_max_suggestions,
            "transpiler_pretty_default": self.transpiler_pretty_default,
            "transpiler_max_sql_length": self.transpiler_max_sql_length,
            "function_search_limit": self.function_search_limit,
            "function_fuzzy_threshold": self.function_fuzzy_threshold,
            "security_check_enabled": self.security_check_enabled,
            "security_block_dangerous": self.security_block_dangerous,
            "log_level": self.log_level,
            "log_file": self.log_file,
        }


# Global settings instance
settings = AppSettings()


# =============================================================================
# Security Patterns for SQL Validation
# =============================================================================

# Patterns that indicate potentially dangerous SQL
DANGEROUS_SQL_PATTERNS: List[tuple] = [
    # Multiple statements (SQL injection risk)
    (r";\s*(DROP|DELETE|TRUNCATE|ALTER|CREATE|INSERT|UPDATE)\s+", 
     "Multiple statements with dangerous operations detected"),
    # Comments that might hide malicious code
    (r"--\s*.*\s*(DROP|DELETE|TRUNCATE)", 
     "SQL comment may hide dangerous operation"),
    # UNION-based injection patterns
    (r"UNION\s+(ALL\s+)?SELECT\s+.*(FROM\s+information_schema|FROM\s+sys\.|@@version|user\(\))",
     "Potential SQL injection pattern detected"),
    # System table access
    (r"(information_schema|sys\.tables|sysobjects|pg_catalog|all_tables)",
     "System table access detected"),
    # Command execution attempts
    (r"(xp_cmdshell|sp_executesql|EXEC\s*\(|EXECUTE\s+IMMEDIATE)",
     "Command execution attempt detected"),
    # File operations
    (r"(INTO\s+OUTFILE|INTO\s+DUMPFILE|LOAD_FILE|UTL_FILE)",
     "File operation detected"),
]

# Patterns that warrant warnings but aren't blocked
WARNING_SQL_PATTERNS: List[tuple] = [
    # DELETE/UPDATE without WHERE
    (r"DELETE\s+FROM\s+\w+\s*(?!WHERE)", 
     "DELETE without WHERE clause - will affect all rows"),
    (r"UPDATE\s+\w+\s+SET\s+.*(?!WHERE)",
     "UPDATE without WHERE clause - will affect all rows"),
    # DROP operations
    (r"DROP\s+(TABLE|DATABASE|SCHEMA|INDEX|VIEW)",
     "DROP operation detected - data loss risk"),
    # TRUNCATE
    (r"TRUNCATE\s+TABLE",
     "TRUNCATE operation detected - data loss risk"),
    # Grant/Revoke
    (r"(GRANT|REVOKE)\s+",
     "Permission modification detected"),
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
    # Hive conversions
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
    # Oracle conversions
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
    # MySQL conversions
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
    # SQL Server conversions
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
    # PostgreSQL conversions
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
    # Spark conversions
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
    # Snowflake conversions
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
    # Trino conversions
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
    # ClickHouse conversions
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
    # Redshift conversions
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
    # DuckDB conversions
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
    # Databricks conversions
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
