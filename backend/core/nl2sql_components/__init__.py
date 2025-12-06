#!/usr/bin/env python3
"""NL2SQL Components Package - Modular components for NL2SQL generation.

This package provides modular components for natural language to SQL generation:
- Tokenizer: Smart tokenization with Chinese and English support
- QueryTemplate: Pattern-based SQL generation using prioritized templates
- Mappings: Language mappings for tables, columns, and SQL operations

Example:
    from backend.core.nl2sql_components import Tokenizer, KEYWORDS
    
    tokens = Tokenizer.tokenize("查询所有用户")
    print(tokens)  # ['查询', '所有', '用户']
"""

# Import main components for convenient access
from .tokenizer import Tokenizer, JIEBA_AVAILABLE
from .templates import QueryTemplate, DEFAULT_QUERY_TEMPLATES
from .mappings import KEYWORDS, TABLE_PATTERNS, COLUMN_PATTERNS

__all__ = [
    "Tokenizer",
    "JIEBA_AVAILABLE",
    "QueryTemplate", 
    "DEFAULT_QUERY_TEMPLATES",
    "KEYWORDS",
    "TABLE_PATTERNS",
    "COLUMN_PATTERNS",
]
