#!/usr/bin/env python3
"""P8 NL2SQL pipeline: AST validation (moved UNCHANGED from nl2sql_legacy).

Validates generated SQL against the target-dialect sqlglot parser and
returns the confidence adjustment (+0.15 / -0.2 / 0.0).
"""
import sqlglot


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
            sqlglot.parse_one(sql_to_validate, read=dialect)
            return 0.15
    except Exception:
        return -0.2
    return 0.0
