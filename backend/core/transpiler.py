#!/usr/bin/env python3
"""SQL Transpiler - Convert SQL between different database dialects."""
import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import sqlglot

from .cache import TTLCache
from .config import (
    DANGEROUS_SQL_PATTERNS,
    SUPPORTED_DIALECTS,
    WARNING_SQL_PATTERNS,
    get_compatibility_notes,
    settings,
)
from .exceptions import ErrorCode, ValidationError
from .p1_sql_scanner import mask_non_executable
from .post_processor import PostProcessor

logger = logging.getLogger(__name__)
_DANGEROUS_OPERATION_PATTERN = re.compile(
    r"\b(DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE)\b", re.IGNORECASE
)


def _contains_sql_keyword(sql: str, keyword: str) -> bool:
    """Return true when a keyword appears as a standalone SQL token."""
    return re.search(rf"\b{re.escape(keyword)}\b", sql, re.IGNORECASE) is not None


@dataclass
class TranspileResult:
    """Result of SQL transpilation."""
    success: bool
    source_sql: str
    target_sql: Optional[str] = None
    source_dialect: str = ""
    target_dialect: str = ""
    error: Optional[str] = None
    error_code: Optional[str] = None
    compatibility_notes: List[str] = field(default_factory=list)
    transformations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "source_sql": self.source_sql,
            "target_sql": self.target_sql,
            "source_dialect": self.source_dialect,
            "target_dialect": self.target_dialect,
            "error": self.error,
            "error_code": self.error_code,
            "compatibility_notes": self.compatibility_notes,
            "transformations": self.transformations,
            "warnings": self.warnings
        }


class SQLTranspiler:
    """SQL Transpiler using sqlglot with post-processing for edge cases."""

    def __init__(self):
        self.post_processor = PostProcessor()
        self._cache_enabled = settings.cache_enabled
        self._cache = TTLCache(max_size=settings.cache_max_size, ttl=settings.cache_ttl)
        self._security_enabled = settings.security_check_enabled

    def transpile(
        self,
        sql: str,
        source: str,
        target: str,
        pretty: bool = True,
        validate: bool = True,
    ) -> TranspileResult:
        if not isinstance(sql, str):
            return TranspileResult(
                success=False,
                source_sql=str(sql),
                source_dialect=source if isinstance(source, str) else str(source),
                target_dialect=target if isinstance(target, str) else str(target),
                error="sql must be a string",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )
        if not isinstance(source, str):
            return TranspileResult(
                success=False,
                source_sql=sql,
                source_dialect=str(source),
                target_dialect=target if isinstance(target, str) else str(target),
                error="source must be a string",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )
        if not isinstance(target, str):
            return TranspileResult(
                success=False,
                source_sql=sql,
                source_dialect=source,
                target_dialect=str(target),
                error="target must be a string",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )

        if len(sql) > settings.transpiler_max_sql_length:
            return TranspileResult(
                success=False,
                source_sql=sql[:100] + "...",
                source_dialect=source.strip().lower(),
                target_dialect=target.strip().lower(),
                error=f"SQL exceeds maximum length of {settings.transpiler_max_sql_length} characters",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )

        source = source.strip().lower()
        target = target.strip().lower()

        logger.info(f"Transpiling SQL: {source} -> {target}, length={len(sql)}")
        logger.debug(f"Input SQL: {sql[:200]}{'...' if len(sql) > 200 else ''}")

        security_warnings: List[str] = []
        multiple_statements: Optional[bool] = None
        executable_sql: Optional[str] = None
        security_enabled = settings.security_check_enabled
        self._security_enabled = security_enabled
        if security_enabled:
            executable_sql = mask_non_executable(sql)
            security_result = self._validate_security(sql, executable_sql)
            security_warnings = list(security_result["warnings"])
            multiple_statements = security_result.get("multiple_statements")
            if security_result["blocked"]:
                logger.warning(f"SQL blocked by security check: {security_result['reason']}")
                return TranspileResult(
                    success=False,
                    source_sql=sql,
                    source_dialect=source,
                    target_dialect=target,
                    error=f"Security check failed: {security_result['reason']}",
                    error_code=ErrorCode.SECURITY_VIOLATION.value,
                    warnings=security_warnings
                )

        if multiple_statements is None:
            multiple_statements = self._has_multiple_statements(sql)
        if multiple_statements:
            return TranspileResult(
                success=False,
                source_sql=sql,
                source_dialect=source,
                target_dialect=target,
                error="Multiple SQL statements are not supported; submit one statement per request",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )

        if source not in SUPPORTED_DIALECTS:
            return TranspileResult(
                success=False, source_sql=sql, source_dialect=source, target_dialect=target,
                error=f"Unsupported source dialect: {source}. Supported: {', '.join(SUPPORTED_DIALECTS)}",
                error_code=ErrorCode.UNSUPPORTED_DIALECT.value
            )

        if target not in SUPPORTED_DIALECTS:
            return TranspileResult(
                success=False, source_sql=sql, source_dialect=source, target_dialect=target,
                error=f"Unsupported target dialect: {target}. Supported: {', '.join(SUPPORTED_DIALECTS)}",
                error_code=ErrorCode.UNSUPPORTED_DIALECT.value
            )

        if not sql.strip():
            return TranspileResult(
                success=False, source_sql=sql, source_dialect=source, target_dialect=target,
                error="Empty SQL statement", error_code=ErrorCode.VALIDATION_FAILED.value
            )

        if self._cache_enabled:
            cache_key = self._cache_key(sql, source, target, pretty, validate)
            cached = self._cache.get(cache_key)
            if cached:
                logger.info("Returning cached result")
                return TranspileResult(**cached)

        try:
            transpiled = sqlglot.transpile(sql, read=source, write=target, pretty=pretty)[0]
            final_sql, transformations = self.post_processor.process(transpiled, source, target)
            compat_notes = self._get_compatibility_notes(source, target, sql)
            warnings = security_warnings + self._generate_warnings(sql, source, target, executable_sql)

            if validate:
                validation_error, validation_warning = self._validate_output_detailed(final_sql, target)
                if validation_warning:
                    warnings.append(validation_warning)
                if validation_error:
                    logger.error(f"Output SQL validation failed: {source} -> {target}: {validation_error}")
                    return TranspileResult(
                        success=False, source_sql=sql, source_dialect=source, target_dialect=target,
                        error=validation_error, error_code=ErrorCode.VALIDATION_FAILED.value,
                        compatibility_notes=compat_notes, transformations=transformations, warnings=warnings
                    )

            result = TranspileResult(
                success=True,
                source_sql=sql,
                target_sql=final_sql,
                source_dialect=source,
                target_dialect=target,
                compatibility_notes=compat_notes,
                transformations=transformations,
                warnings=warnings
            )

            if self._cache_enabled:
                self._cache.set(cache_key, result.to_dict())
            return result
        except Exception as e:
            logger.error(f"Transpile failed: {source} -> {target}, error={str(e)}")
            return TranspileResult(
                success=False, source_sql=sql, source_dialect=source, target_dialect=target,
                error=str(e), error_code=ErrorCode.TRANSPILE_FAILED.value
            )

    @staticmethod
    def _has_multiple_statements(sql: str) -> bool:
        """Return true when SQL contains more than one parsed statement."""
        if not isinstance(sql, str) or not sql.strip():
            return False
        try:
            return len(sqlglot.parse(sql)) > 1
        except Exception:
            return False

    def _cache_key(self, sql: str, source: str, target: str, pretty: bool, validate: bool = True,) -> str:
        rule_payload = "\n".join(
            "|".join([
                rule.name, rule.source, rule.target, rule.pattern, rule.replacement,
                rule.note, rule.category.value, str(rule.priority), str(rule.enabled),
            ])
            for rule in self.post_processor.engine.rules
        )
        rule_version = hashlib.sha256(rule_payload.encode("utf-8")).hexdigest()[:16]
        security_version = f"{settings.security_check_enabled}|{settings.security_block_dangerous}"
        return f"v4|{rule_version}|{security_version}|{sql}|{source}|{target}|{pretty}|{validate}"

    def _get_compatibility_notes(self, source: str, target: str, sql: str = "") -> List[str]:
        notes = list(get_compatibility_notes(source, target))
        sql_upper = sql.upper()
        if "LIMIT" in sql_upper and target == "oracle":
            notes.append("Oracle uses FETCH FIRST n ROWS ONLY (12c+) or ROWNUM for LIMIT")
        if "AUTO_INCREMENT" in sql_upper and target != "mysql":
            notes.append("AUTO_INCREMENT syntax varies by database")
        if "LATERAL VIEW" in sql_upper and target not in ["hive", "spark", "databricks"]:
            notes.append("LATERAL VIEW is Hive/Spark specific, converted to UNNEST/JSON_TABLE")
        if "CONNECT BY" in sql_upper and target != "oracle":
            notes.append("CONNECT BY is Oracle specific, converted to WITH RECURSIVE")
        if "MERGE" in sql_upper:
            notes.append("MERGE syntax varies significantly between databases")
        if "PIVOT" in sql_upper or "UNPIVOT" in sql_upper:
            notes.append("PIVOT/UNPIVOT syntax varies by database")
        return notes

    def _generate_warnings(self, sql: str, source: str, target: str, masked_sql: Optional[str] = None) -> List[str]:
        sql_upper = (masked_sql if masked_sql is not None else mask_non_executable(sql)).upper()
        warnings = []
        if "DROP TABLE" in sql_upper or "TRUNCATE" in sql_upper:
            warnings.append("⚠️ Dangerous operation detected: DROP/TRUNCATE")
        if _contains_sql_keyword(sql_upper, "DELETE") and not _contains_sql_keyword(sql_upper, "WHERE"):
            warnings.append("⚠️ DELETE without WHERE clause - will delete all rows")
        if _contains_sql_keyword(sql_upper, "UPDATE") and not _contains_sql_keyword(sql_upper, "WHERE"):
            warnings.append("⚠️ UPDATE without WHERE clause - will update all rows")
        if "SELECT *" in sql_upper:
            warnings.append("💡 Consider specifying columns instead of SELECT *")
        if "CROSS JOIN" in sql_upper:
            warnings.append("💡 CROSS JOIN can produce large result sets")
        if sql_upper.count("JOIN") > 5:
            warnings.append("💡 Query has many JOINs - consider query optimization")
        if source == "hive" and target in ["mysql", "postgres", "oracle"]:
            if "DISTRIBUTE BY" in sql_upper or "CLUSTER BY" in sql_upper:
                warnings.append("⚠️ DISTRIBUTE BY/CLUSTER BY are Hive-specific hints, removed in target")
            if "SORT BY" in sql_upper:
                warnings.append("⚠️ SORT BY is Hive-specific, converted to ORDER BY")
        if source in ["hive", "spark"] and target in ["mysql", "postgres"]:
            if "COLLECT_LIST" in sql_upper or "COLLECT_SET" in sql_upper:
                warnings.append("💡 Array aggregation converted - verify result format")
        return warnings

    def _validate_output(self, sql: str, dialect: str) -> Optional[str]:
        """Validate target SQL, preserving the original error-only interface."""
        error, _ = self._validate_output_detailed(sql, dialect)
        return error

    def _validate_output_detailed(
        self, sql: str, dialect: str
    ) -> tuple[Optional[str], Optional[str]]:
        """Validate target SQL with a generic-parser compatibility fallback."""
        try:
            sqlglot.parse_one(sql, read=dialect)
            return None, None
        except Exception as target_error:
            target_message = str(target_error)[:100]
            try:
                sqlglot.parse_one(sql)
            except Exception:
                return f"⚠️ Output SQL may have syntax issues: {target_message}", None

            warning = (
                "⚠️ Target dialect parser rejected the output, but the generic "
                "SQL parser accepted it; retaining the conversion with a "
                f"compatibility warning. Target parser error: {target_message}"
            )
            logger.warning("Generic parser fallback used for %s output: %s", dialect, target_message)
            return None, warning

    def _validate_security(self, sql: str, masked_sql: Optional[str] = None) -> Dict[str, Any]:
        result = {"blocked": False, "reason": None, "warnings": []}
        executable_sql = masked_sql if masked_sql is not None else mask_non_executable(sql)
        dangerous_operation = _DANGEROUS_OPERATION_PATTERN.search(executable_sql)
        if dangerous_operation:
            message = f"Dangerous SQL operation detected: {dangerous_operation.group(1).upper()}"
            if settings.security_block_dangerous:
                result["blocked"] = True
                result["reason"] = message
                return result
            result["warnings"].append(f"🔒 Security: {message}")
        try:
            parsed_statements = sqlglot.parse(sql)
            result["multiple_statements"] = len(parsed_statements) > 1
            if result["multiple_statements"]:
                message = "Multiple SQL statements detected"
                if settings.security_block_dangerous:
                    result["blocked"] = True
                    result["reason"] = message
                    return result
                result["warnings"].append(f"🔒 Security: {message}")
        except Exception as exc:
            logger.debug("SQL statement parsing failed during security validation: %s", exc)
        for pattern, message in DANGEROUS_SQL_PATTERNS:
            if pattern.search(executable_sql):
                if settings.security_block_dangerous:
                    result["blocked"] = True
                    result["reason"] = message
                    return result
                result["warnings"].append(f"🔒 Security: {message}")
        for pattern, message in WARNING_SQL_PATTERNS:
            if pattern.search(executable_sql):
                result["warnings"].append(f"⚠️ {message}")
        return result

    def batch_transpile(self, statements: List[str], source: str, target: str, pretty: bool = True) -> List[TranspileResult]:
        if not isinstance(statements, list):
            raise ValidationError("statements must be a list", field="statements", value=type(statements).__name__)
        if len(statements) > settings.max_batch_size:
            raise ValidationError(f"Batch contains {len(statements)} statements; maximum is {settings.max_batch_size}", field="statements", value=str(len(statements)))
        return [self.transpile(sql, source, target, pretty) for sql in statements]

    async def batch_transpile_async(self, statements: List[str], source: str, target: str, pretty: bool = True, max_concurrent: int = 10) -> List[TranspileResult]:
        if not isinstance(statements, list):
            raise ValidationError("statements must be a list", field="statements", value=type(statements).__name__)
        if len(statements) > settings.max_batch_size:
            raise ValidationError(f"Batch contains {len(statements)} statements; maximum is {settings.max_batch_size}", field="statements", value=str(len(statements)))
        if isinstance(max_concurrent, bool) or not isinstance(max_concurrent, int) or max_concurrent <= 0:
            raise ValidationError("max_concurrent must be a positive integer", field="max_concurrent", value=str(max_concurrent))
        semaphore = asyncio.Semaphore(max_concurrent)

        async def limited_transpile(sql: str) -> TranspileResult:
            async with semaphore:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(None, lambda: self.transpile(sql, source, target, pretty))

        return await asyncio.gather(*(limited_transpile(sql) for sql in statements))

    def get_supported_dialects(self) -> List[str]:
        return SUPPORTED_DIALECTS.copy()

    def get_stats(self) -> Dict[str, Any]:
        return {
            "supported_dialects": len(SUPPORTED_DIALECTS),
            "dialects": SUPPORTED_DIALECTS,
            "post_processor": self.post_processor.get_stats(),
            "cache": self._cache.get_stats() if self._cache_enabled else {"enabled": False},
            "security": {"enabled": self._security_enabled, "block_dangerous": settings.security_block_dangerous},
            "settings": {"cache_enabled": self._cache_enabled, "max_batch_size": settings.max_batch_size, "max_sql_length": settings.transpiler_max_sql_length}
        }

    def clear_cache(self) -> None:
        if self._cache_enabled:
            self._cache.clear()
            logger.info("Transpile cache cleared")