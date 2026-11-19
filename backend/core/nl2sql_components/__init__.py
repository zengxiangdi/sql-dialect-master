"""NL2SQL Components Package - Modular components for NL2SQL generation.

This package provides modular components for natural language to SQL
generation:
- Tokenizer: Smart tokenization with Chinese and English support
- QueryTemplate: Pattern-based SQL generation using prioritized templates
- Mappings: Language mappings for tables, columns, and SQL operations
- CoreExtract: Operation, table, column, limit, distinct extraction
- Relations: Join extraction, join-key inference, relational keywords
- Aggregations: SQL aggregate function extraction

Example:
    from backend.core.nl2sql_components import Tokenizer, KEYWORDS

    tokens = Tokenizer.tokenize("查询所有用户")
    print(tokens)  # ['查询', '所有', '用户']
"""

# Import main components for convenient access
from .aggregations import extract_aggregations
from .boolean_conditions import extract_boolean_conditions
from .core_extract import (
    check_distinct,
    detect_operation,
    extract_columns,
    extract_limit,
    extract_table,
    extract_table_subject,
    named_tables,
)
from .mappings import COLUMN_PATTERNS, KEYWORDS, TABLE_PATTERNS
from .relations import (
    JoinSpec,
    extract_joins,
    guess_join_key,
    has_relational_keyword,
    parse_join_spec,
)
from .templates import DEFAULT_QUERY_TEMPLATES, QueryTemplate
from .tokenizer import JIEBA_AVAILABLE, Tokenizer

__all__ = [
    "COLUMN_PATTERNS",
    "DEFAULT_QUERY_TEMPLATES",
    "JIEBA_AVAILABLE",
    "KEYWORDS",
    "TABLE_PATTERNS",
    "JoinSpec",
    "QueryTemplate",
    "Tokenizer",
    "check_distinct",
    "detect_operation",
    "extract_aggregations",
    "extract_boolean_conditions",
    "extract_columns",
    "extract_joins",
    "extract_limit",
    "extract_table",
    "extract_table_subject",
    "guess_join_key",
    "has_relational_keyword",
    "named_tables",
    "parse_join_spec",
]
