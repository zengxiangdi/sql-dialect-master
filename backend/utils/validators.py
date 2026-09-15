#!/usr/bin/env python3
"""Input validation utilities for SQL Dialect Master.

Provides validation functions for SQL, dialects, and other inputs.
"""
import re

from backend.core.config import SUPPORTED_DIALECTS, settings
from backend.core.exceptions import (
    SecurityViolationError,
    UnsupportedDialectError,
    ValidationError,
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


def validate_sql_security(sql: str, block_dangerous: bool = None) -> tuple[bool, list[str]]:
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


def split_sql_statements(sql: str) -> list[str]:
    """Split SQL text into individual statements respecting string literals and comments.

    This is a pure parsing utility — no semantic analysis.
    Handles:
    - Semicolons inside single-quoted strings ('...;...')
    - Semicolons inside double-quoted identifiers ("...;...")
    - Semicolons inside block comments (-- line comment; ... or /* ... */)
    - Dollar-quoted strings ($$...$$ or $tag$...$tag$)
    - Empty statements are filtered out

    Args:
        sql: SQL text potentially containing multiple statements

    Returns:
        List of individual SQL statement strings
    """
    if not sql or not sql.strip():
        return []

    import sqlglot

    statements = []
    try:
        parsed = sqlglot.parse(sql, dialect="postgres")
        for stmt in parsed:
            if stmt is not None:
                rendered = stmt.sql(pretty=False)
                if rendered.strip():
                    statements.append(rendered)
    except Exception:  # noqa: BLE001 — malformed SQL fallback
        # Fallback: state-machine aware splitter
        stmt_lines: list[str] = []
        in_single_quote = False
        in_double_quote = False
        i = 0
        text = sql
        while i < len(text):
            ch = text[i]
            if ch == "'" and not in_double_quote:
                # Check for escaped quote ''
                if i + 1 < len(text) and text[i + 1] == "'":
                    stmt_lines.append(ch)
                    i += 2
                    continue
                in_single_quote = not in_single_quote
                stmt_lines.append(ch)
            elif ch == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
                stmt_lines.append(ch)
            elif ch == ";" and not in_single_quote and not in_double_quote:
                # Check for line comment starting with ;
                statement = "".join(stmt_lines).strip()
                if statement:
                    statements.append(statement)
                stmt_lines = []
            elif ch == "-" and i + 1 < len(text) and text[i + 1] == "-":
                # Line comment — consume until newline
                stmt_lines.append(ch)
                i += 1
                while i < len(text) and text[i] != "\n":
                    stmt_lines.append(text[i])
                    i += 1
                continue
            elif ch == "/" and i + 1 < len(text) and text[i + 1] == "*":
                # Block comment — consume until */
                stmt_lines.append(ch)
                i += 1
                while i + 1 < len(text):
                    if text[i] == "*" and text[i + 1] == "/":
                        stmt_lines.append("*/")
                        i += 2
                        break
                    stmt_lines.append(text[i])
                    i += 1
                else:
                    i += 1
                continue
            else:
                stmt_lines.append(ch)
            i += 1

        # Last statement (no trailing semicolon)
        last = "".join(stmt_lines).strip()
        if last:
            statements.append(last)

    return statements
