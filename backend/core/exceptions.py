#!/usr/bin/env python3
"""Custom exceptions for SQL Dialect Master.

Provides a hierarchy of exceptions for better error handling and debugging.
"""


class SDMException(Exception):
    """Base exception for SQL Dialect Master."""
    
    def __init__(self, message: str, details: dict = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
    
    def to_dict(self) -> dict:
        """Convert exception to dictionary for API responses."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "details": self.details
        }


class UnsupportedDialectError(SDMException):
    """Raised when an unsupported SQL dialect is specified."""
    
    def __init__(self, dialect: str, supported: list = None):
        message = f"Unsupported dialect: {dialect}"
        if supported:
            message += f". Supported: {', '.join(supported)}"
        super().__init__(message, {"dialect": dialect, "supported": supported})


class TranspileError(SDMException):
    """Raised when SQL transpilation fails."""
    
    def __init__(self, message: str, source_sql: str = None, source_dialect: str = None, target_dialect: str = None):
        details = {
            "source_sql": source_sql[:200] if source_sql else None,
            "source_dialect": source_dialect,
            "target_dialect": target_dialect
        }
        super().__init__(message, details)


class ParseError(SDMException):
    """Raised when SQL parsing fails."""
    
    def __init__(self, message: str, sql: str = None, dialect: str = None):
        details = {"sql": sql[:200] if sql else None, "dialect": dialect}
        super().__init__(message, details)


class SecurityViolationError(SDMException):
    """Raised when SQL contains potentially dangerous patterns."""
    
    def __init__(self, message: str, pattern: str = None):
        details = {"pattern": pattern}
        super().__init__(message, details)


class ValidationError(SDMException):
    """Raised when input validation fails."""
    
    def __init__(self, message: str, field: str = None, value: str = None):
        details = {"field": field, "value": value}
        super().__init__(message, details)


class CacheError(SDMException):
    """Raised when cache operations fail."""
    pass


class ConfigurationError(SDMException):
    """Raised when configuration is invalid."""
    pass


class RuleConflictError(SDMException):
    """Raised when transformation rules conflict."""
    
    def __init__(self, message: str, rule1: str = None, rule2: str = None):
        details = {"rule1": rule1, "rule2": rule2}
        super().__init__(message, details)
