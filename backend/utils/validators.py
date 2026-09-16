#!/usr/bin/env python3
"""Input validation utilities for SQL Dialect Master.

Provides validation functions for SQL, dialects, and other inputs.
"""
import re
from typing import Tuple, List

from backend.core.config import SUPPORTED_DIALECTS, settings
from backend.core.exceptions import (
    ValidationError,
    UnsupportedDialectError,
    SecurityViolationError
)


def validate_dialect(dialect: str, param_name: str = "dialect") -> str:
    """Validate SQL dialect.
    
    Args:
        dialect: Dialect to validate
        param_name: Parameter name for error messages
        
    Returns:
        Normalized dialect name (lowercase)
        
    Raises:
        UnsupportedDialectError: If dialect is not supported
    """
    if not dialect:
        raise ValidationError(f"{param_name} is required", field=param_name)
    
    dialect_lower = dialect.lower().strip()
    
    if dialect_lower not in SUPPORTED_DIALECTS:
        raise UnsupportedDialectError(dialect, SUPPORTED_DIALECTS)
    
    return dialect_lower


def validate_sql(sql: str, max_length: int = None) -> str:
    """Validate SQL input.
    
    Args:
        sql: SQL to validate
        max_length: Maximum allowed length
        
    Returns:
        Validated SQL string
        
    Raises:
        ValidationError: If SQL is invalid
    """
    if not sql:
        raise ValidationError("SQL statement is required", field="sql")
    
    sql = sql.strip()
    
    if not sql:
        raise ValidationError("SQL statement cannot be empty", field="sql")
    
    max_len = max_length or settings.transpiler_max_sql_length
    if len(sql) > max_len:
        raise ValidationError(
            f"SQL exceeds maximum length of {max_len} characters",
            field="sql",
            value=f"{len(sql)} characters"
        )
    
    return sql


def validate_sql_security(sql: str, block_dangerous: bool = None) -> Tuple[bool, List[str]]:
    """Validate SQL for security issues.
    
    Args:
        sql: SQL to validate
        block_dangerous: Whether to block dangerous patterns
        
    Returns:
        Tuple of (is_safe, list_of_warnings)
        
    Raises:
        SecurityViolationError: If dangerous pattern detected and blocking enabled
    """
    block = block_dangerous if block_dangerous is not None else settings.security_block_dangerous
    warnings = []
    
    # Dangerous patterns that may be blocked
    dangerous_patterns = [
        (r";\s*(DROP|DELETE|TRUNCATE|ALTER|CREATE|INSERT|UPDATE)\s+", 
         "Multiple statements with dangerous operations"),
        (r"UNION\s+(ALL\s+)?SELECT\s+.*(FROM\s+information_schema|@@version|user\(\))",
         "Potential SQL injection pattern"),
        (r"(xp_cmdshell|sp_executesql|EXEC\s*\(|EXECUTE\s+IMMEDIATE)",
         "Command execution attempt"),
        (r"(INTO\s+OUTFILE|INTO\s+DUMPFILE|LOAD_FILE|UTL_FILE)",
         "File operation detected"),
    ]
    
    # Warning patterns (never blocked)
    warning_patterns = [
        (r"DELETE\s+FROM\s+\w+\s*(?!WHERE)", 
         "DELETE without WHERE clause"),
        (r"UPDATE\s+\w+\s+SET\s+.*(?!WHERE)",
         "UPDATE without WHERE clause"),
        (r"DROP\s+(TABLE|DATABASE|SCHEMA|INDEX|VIEW)",
         "DROP operation - data loss risk"),
        (r"TRUNCATE\s+TABLE",
         "TRUNCATE operation - data loss risk"),
    ]
    
    # Check dangerous patterns
    for pattern, message in dangerous_patterns:
        if re.search(pattern, sql, re.IGNORECASE | re.MULTILINE):
            if block:
                raise SecurityViolationError(message, pattern=pattern)
            warnings.append(f"🔒 Security: {message}")
    
    # Check warning patterns
    for pattern, message in warning_patterns:
        if re.search(pattern, sql, re.IGNORECASE | re.MULTILINE):
            warnings.append(f"⚠️ {message}")
    
    return len(warnings) == 0, warnings


def validate_batch_size(size: int, max_size: int = None) -> int:
    """Validate batch size.
    
    Args:
        size: Requested batch size
        max_size: Maximum allowed size
        
    Returns:
        Validated batch size
        
    Raises:
        ValidationError: If size is invalid
    """
    max_allowed = max_size or settings.max_batch_size
    
    if size <= 0:
        raise ValidationError("Batch size must be positive", field="batch_size", value=str(size))
    
    if size > max_allowed:
        return max_allowed
    
    return size


def validate_type_name(type_name: str) -> str:
    """Validate data type name.
    
    Args:
        type_name: Type name to validate
        
    Returns:
        Normalized type name (uppercase)
        
    Raises:
        ValidationError: If type name is invalid
    """
    if not type_name:
        raise ValidationError("Type name is required", field="type_name")
    
    return type_name.upper().strip()


def validate_function_name(func_name: str) -> str:
    """Validate function name.
    
    Args:
        func_name: Function name to validate
        
    Returns:
        Normalized function name (uppercase)
        
    Raises:
        ValidationError: If function name is invalid
    """
    if not func_name:
        raise ValidationError("Function name is required", field="function_name")
    
    return func_name.upper().strip()


def sanitize_table_name(name: str) -> str:
    """Sanitize table name for safe use in SQL.
    
    Args:
        name: Table name to sanitize
        
    Returns:
        Sanitized table name
        
    Raises:
        ValidationError: If name contains invalid characters
    """
    if not name:
        raise ValidationError("Table name is required", field="table_name")
    
    # Allow only alphanumeric, underscore, and dot (for schema.table)
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_\.]*$', name):
        raise ValidationError(
            "Table name contains invalid characters",
            field="table_name",
            value=name
        )
    
    return name


def sanitize_column_name(name: str) -> str:
    """Sanitize column name for safe use in SQL.
    
    Args:
        name: Column name to sanitize
        
    Returns:
        Sanitized column name
        
    Raises:
        ValidationError: If name is invalid
    """
    if not name:
        raise ValidationError("Column name is required", field="column_name")
    
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
        raise ValidationError(
            "Column name contains invalid characters",
            field="column_name",
            value=name
        )
    
    return name





def split_sql_statements(sql: str, dialect: str = "postgres") -> list[str]:
    """Split SQL text into individual statements, preserving original text exactly.

    Pure lexical splitter — no AST parsing, no re-rendering, no semantic analysis.
    Finds statement boundaries by tracking quote/comment states so semicolons
    inside literals/comments are not mistaken for separators.

    Handles:
    - Single-quoted strings with escaped quotes ('')
    - Double-quoted identifiers
    - Backtick identifiers (MySQL)
    - Line comments (-- comment\n)
    - Block comments (/* ... */)
    - PostgreSQL dollar-quoted strings ($$...$$ or $tag$...$tag$)
    - Empty statements and trailing semicolons filtered out

    Args:
        sql: SQL text potentially containing multiple statements
        dialect: SQL dialect hint (not used for splitting logic)

    Returns:
        List of individual SQL statement strings (original text preserved)
    """
    if not sql or not sql.strip():
        return []

    statements: list[str] = []
    stmt_chars: list[str] = []
    i = 0
    n = len(sql)
    in_single = False
    in_double = False
    in_backtick = False

    # Sentinel values to distinguish "inside $$" from "not in dollar quote"
    _IN_DOLLAR_EMPTY = object()  # inside $$...$$
    _NOT_IN_DOLLAR = None        # not inside any dollar quote
    dollar_tag = _NOT_IN_DOLLAR

    while i < n:
        ch = sql[i]

        # ── Dollar-quoted string content ──
        if dollar_tag is not _NOT_IN_DOLLAR:
            # We're inside a dollar-quoted string
            if dollar_tag is _IN_DOLLAR_EMPTY:
                # Looking for closing $$
                if sql[i:i+2] == "$$":
                    stmt_chars.append("$$")
                    i += 2
                    dollar_tag = _NOT_IN_DOLLAR
                else:
                    stmt_chars.append(ch)
                    i += 1
                continue
            else:
                # Looking for closing $tag$
                end_tag = "$" + dollar_tag + "$"
                if sql[i:i + len(end_tag)] == end_tag:
                    stmt_chars.append(end_tag)
                    i += len(end_tag)
                    dollar_tag = _NOT_IN_DOLLAR
                else:
                    stmt_chars.append(ch)
                    i += 1
                continue

        # ── Start of dollar-quoted string ──
        if ch == "$" and not in_single and not in_double and not in_backtick:
            # Check for $$ (empty tag)
            if i + 1 < n and sql[i + 1] == "$":
                stmt_chars.append("$$")
                dollar_tag = _IN_DOLLAR_EMPTY
                i += 2
                continue
            # Check for $tag$ format
            if i + 1 < n:
                next_ch = sql[i + 1]
                if next_ch.isalnum() or next_ch == "_":
                    j = i + 1
                    while j < n and sql[j] != "$":
                        j += 1
                    if j < n and sql[j] == "$":
                        tag = sql[i + 1:j]
                        if tag:
                            # Append the opening $tag$ to preserve it
                            stmt_chars.append("$" + tag + "$")
                            dollar_tag = tag
                            i = j + 1
                            continue
            # Not a dollar-quote start
            stmt_chars.append(ch)
            i += 1
            continue

        # ── Single-quoted strings ──
        if ch == "'" and not in_double and not in_backtick:
            if i + 1 < n and sql[i + 1] == "'":
                stmt_chars.append("''")
                i += 2
                continue
            in_single = not in_single
            stmt_chars.append(ch)
            i += 1
            continue

        # ── Double-quoted identifiers ──
        if ch == '"' and not in_single and not in_backtick:
            in_double = not in_double
            stmt_chars.append(ch)
            i += 1
            continue

        # ── Backtick identifiers (MySQL) ──
        if ch == "`" and not in_single and not in_double:
            in_backtick = not in_backtick
            stmt_chars.append(ch)
            i += 1
            continue

        # ── Line comments ──
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            stmt_chars.append(ch)
            i += 1
            while i < n and sql[i] != "\n":
                stmt_chars.append(sql[i])
                i += 1
            continue

        # ── Block comments ──
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            stmt_chars.append("/*")
            i += 2
            while i + 1 < n:
                if sql[i] == "*" and sql[i + 1] == "/":
                    stmt_chars.append("*/")
                    i += 2
                    break
                stmt_chars.append(sql[i])
                i += 1
            else:
                # Unterminated block comment
                while i < n:
                    stmt_chars.append(sql[i])
                    i += 1
            continue

        # ── Statement terminator ──
        if ch == ";" and not in_single and not in_double and not in_backtick:
            statement = "".join(stmt_chars).strip()
            if statement:
                statements.append(statement)
            stmt_chars = []
            i += 1
            continue

        # ── Normal character ──
        stmt_chars.append(ch)
        i += 1

    # Last statement without trailing semicolon
    last = "".join(stmt_chars).strip()
    if last:
        statements.append(last)

    return statements
