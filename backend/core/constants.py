#!/usr/bin/env python3
"""Application constants for SQL Dialect Master.

Centralizes all magic numbers and hardcoded values for better maintainability.
"""

# =============================================================================
# UI Constants
# =============================================================================

# SQL Editor
SQL_INPUT_HEIGHT = 220
SQL_BATCH_INPUT_HEIGHT = 120
SQL_LINEAGE_INPUT_HEIGHT = 180
SQL_EXPLAIN_INPUT_HEIGHT = 120

# Preview lengths (for truncating display)
SQL_PREVIEW_LENGTH = 200
HISTORY_PREVIEW_LENGTH = 40
FAVORITE_LABEL_LENGTH = 25

# Limits
MAX_HISTORY_DISPLAY = 5
MAX_FAVORITES_DISPLAY = 5
MAX_FUNCTION_SEARCH_RESULTS = 30
MAX_OUTPUT_COLUMNS_LINEAGE = 6

# =============================================================================
# API Constants
# =============================================================================

MAX_SQL_LENGTH = 100000  # Maximum SQL input length
MAX_BATCH_SIZE = 100     # Maximum statements in batch conversion
DEFAULT_SEARCH_LIMIT = 20

# =============================================================================
# Cache Constants
# =============================================================================

TRANSPILE_CACHE_MAX_SIZE = 1000
TRANSPILE_CACHE_TTL = 300  # 5 minutes

FUNCTION_CACHE_MAX_SIZE = 500
FUNCTION_CACHE_TTL = 600  # 10 minutes

TYPE_CACHE_MAX_SIZE = 200
TYPE_CACHE_TTL = 600  # 10 minutes

# =============================================================================
# NL2SQL Constants
# =============================================================================

NL2SQL_HIGH_CONFIDENCE_THRESHOLD = 0.7
NL2SQL_MEDIUM_CONFIDENCE_THRESHOLD = 0.5

# =============================================================================
# Security Constants
# =============================================================================

# Patterns that indicate potentially dangerous SQL
DANGEROUS_PATTERNS = [
    r'\bDROP\s+DATABASE\b',
    r'\bDROP\s+TABLE\b',
    r'\bTRUNCATE\b',
    r'\bDELETE\s+FROM\s+\w+\s*;?\s*$',  # DELETE without WHERE
    r'\bUPDATE\s+\w+\s+SET\s+.*(?!WHERE)',  # UPDATE without WHERE
    r';\s*--',  # SQL injection pattern
    r'\bEXEC\s*\(',
    r'\bxp_cmdshell\b',
]

# =============================================================================
# Version Info
# =============================================================================

VERSION = "1.0.0"
APP_NAME = "SQL Dialect Master"
APP_DESCRIPTION = "Enterprise-grade multi-database SQL conversion platform"
