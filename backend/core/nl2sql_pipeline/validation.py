#!/usr/bin/env python3
"""P8 NL2SQL pipeline: AST validation (moved UNCHANGED from nl2sql_legacy).

Validates generated SQL against the target-dialect sqlglot parser and
returns the confidence adjustment (+0.15 / -0.2 / 0.0).
"""
import sqlglot
import re

from ..p1_sql_scanner import mask_non_executable


_BIND_PARAMETER_PATTERNS = {
    "postgres": re.compile(r"(?<![A-Za-z0-9_$])\$\d+(?![A-Za-z0-9_$])"),
    "redshift": re.compile(r"(?<![A-Za-z0-9_$])\$\d+(?![A-Za-z0-9_$])"),
    "oracle": re.compile(r"(?<![A-Za-z0-9_$]):\d+(?![A-Za-z0-9_$])"),
    "tsql": re.compile(r"(?<![A-Za-z0-9_$])@[A-Za-z_][A-Za-z0-9_]*(?![A-Za-z0-9_$])"),
    "mysql": re.compile(r"(?<![A-Za-z0-9_$])%s(?![A-Za-z0-9_$])"),
    "hive": re.compile(r"(?<![A-Za-z0-9_$])\?(?![A-Za-z0-9_$])"),
    "spark": re.compile(r"(?<![A-Za-z0-9_$])\?(?![A-Za-z0-9_$])"),
    "trino": re.compile(r"(?<![A-Za-z0-9_$])\?(?![A-Za-z0-9_$])"),
    "snowflake": re.compile(r"(?<![A-Za-z0-9_$])\?(?![A-Za-z0-9_$])"),
    "clickhouse": re.compile(r"(?<![A-Za-z0-9_$])\?(?![A-Za-z0-9_$])"),
    "duckdb": re.compile(r"(?<![A-Za-z0-9_$])\?(?![A-Za-z0-9_$])"),
    "databricks": re.compile(r"(?<![A-Za-z0-9_$])\?(?![A-Za-z0-9_$])"),
}


def _replace_bind_parameters(sql: str, dialect: str) -> str:
    """Replace driver bind markers with NULL for parser compatibility.

    Some sqlglot dialect readers (currently Oracle in particular) do not
    accept native bind syntax even though the generated SQL is executable by
    the database driver.  Validation should check statement structure while
    preserving the native marker in the returned SQL.
    """
    pattern = _BIND_PARAMETER_PATTERNS.get((dialect or "").lower())
    if pattern is None:
        return sql
    masked = mask_non_executable(sql)
    replacements = []
    for match in pattern.finditer(masked):
        replacements.append((match.start(), match.end()))
    if not replacements:
        return sql
    output = sql
    for start, end in reversed(replacements):
        output = output[:start] + "NULL" + output[end:]
    return output


def validate_sql(sql: str, dialect: str) -> float:
    """Validate generated SQL syntax and return confidence adjustment.

    Strips comment lines, parses the executable payload with the target
    dialect's sqlglot reader, and returns:
        +0.15  parser accepted
        -0.2   parser rejected
         0.0   nothing to validate (empty after stripping comments)
    """
    try:
        sql_to_validate = "\n".join(
            line for line in sql.split("\n") if not line.strip().startswith("--")
        )
        if sql_to_validate.strip():
            try:
                sqlglot.parse_one(sql_to_validate, read=dialect)
            except Exception:
                normalized = _replace_bind_parameters(sql_to_validate, dialect)
                if normalized == sql_to_validate:
                    raise
                sqlglot.parse_one(normalized, read=dialect)
            return 0.15
    except Exception:
        return -0.2
    return 0.0
