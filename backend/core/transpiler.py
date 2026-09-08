#!/usr/bin/env python3
"""SQL Transpiler - Convert SQL between different database dialects.

Provides enterprise-grade SQL conversion with:
- 12 database dialects support
- Rule-based post-processing
- Compatibility notes and warnings
- Batch conversion with concurrency control
- Security validation
- Result caching with TTL
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import sqlglot
import asyncio

from .config import (
    SUPPORTED_DIALECTS,
    get_compatibility_notes,
    settings,
    DANGEROUS_SQL_PATTERNS,
    WARNING_SQL_PATTERNS,
)
from .post_processor import PostProcessor
from .cache import TTLCache
from .exceptions import (
    TranspileError,
    UnsupportedDialectError,
    SecurityViolationError,
    ValidationError
)

# Configure module logger
logger = logging.getLogger(__name__)


@dataclass
class TranspileResult:
    """Result of SQL transpilation."""
    success: bool
    source_sql: str
    target_sql: Optional[str] = None
    source_dialect: str = ""
    target_dialect: str = ""
    error: Optional[str] = None
    compatibility_notes: List[str] = field(default_factory=list)
    transformations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "source_sql": self.source_sql,
            "target_sql": self.target_sql,
            "source_dialect": self.source_dialect,
            "target_dialect": self.target_dialect,
            "error": self.error,
            "compatibility_notes": self.compatibility_notes,
            "transformations": self.transformations,
            "warnings": self.warnings
        }


class SQLTranspiler:
    """SQL Transpiler using sqlglot with post-processing for edge cases."""

    def __init__(self):
        """Initialize transpiler with post-processor and cache."""
        self.post_processor = PostProcessor()
        self._cache_enabled = settings.cache_enabled
        self._cache = TTLCache(
            max_size=settings.cache_max_size,
            ttl=settings.cache_ttl
        )
        self._security_enabled = settings.security_check_enabled

    def transpile(
        self,
        sql: str,
        source: str,
        target: str,
        pretty: bool = True,
        validate: bool = True,
        skip_security: bool = False
    ) -> TranspileResult:
        """Transpile SQL from source dialect to target dialect."""
        source = source.lower()
        target = target.lower()

        logger.info(f"Transpiling SQL: {source} -> {target}, length={len(sql)}")
        logger.debug(f"Input SQL: {sql[:200]}{'...' if len(sql) > 200 else ''}")

        if self._security_enabled and not skip_security:
            security_result = self._validate_security(sql)
            if security_result["blocked"]:
                logger.warning(f"SQL blocked by security check: {security_result['reason']}")
                return TranspileResult(
                    success=False,
                    source_sql=sql,
                    source_dialect=source,
                    target_dialect=target,
                    error=f"Security check failed: {security_result['reason']}",
                    warnings=security_result["warnings"]
                )

        if self._cache_enabled:
            cache_key = f"{sql}|{source}|{target}|{pretty}"
            cached = self._cache.get(cache_key)
            if cached:
                logger.info("Returning cached result")
                return TranspileResult(**cached)

        if source not in SUPPORTED_DIALECTS:
            return TranspileResult(
                success=False,
                source_sql=sql,
                source_dialect=source,
                target_dialect=target,
                error=f"Unsupported source dialect: {source}. Supported: {', '.join(SUPPORTED_DIALECTS)}"
            )

        if target not in SUPPORTED_DIALECTS:
            return TranspileResult(
                success=False,
                source_sql=sql,
                source_dialect=source,
                target_dialect=target,
                error=f"Unsupported target dialect: {target}. Supported: {', '.join(SUPPORTED_DIALECTS)}"
            )

        if len(sql) > settings.transpiler_max_sql_length:
            return TranspileResult(
                success=False,
                source_sql=sql[:100] + "...",
                source_dialect=source,
                target_dialect=target,
                error=f"SQL exceeds maximum length of {settings.transpiler_max_sql_length} characters"
            )

        if not sql or not sql.strip():
            return TranspileResult(
                success=False,
                source_sql=sql,
                source_dialect=source,
                target_dialect=target,
                error="Empty SQL statement"
            )

        try:
            logger.debug("Step 1: Transpiling with sqlglot")
            transpiled = sqlglot.transpile(
                sql,
                read=source,
                write=target,
                pretty=pretty
            )[0]

            logger.debug("Step 2: Applying post-processing rules")
            final_sql, transformations = self.post_processor.process(
                transpiled, source, target
            )

            compat_notes = self._get_compatibility_notes(source, target, sql)
            warnings = self._generate_warnings(sql, source, target)

            # A malformed target is a conversion failure, not a successful
            # conversion carrying only a warning.
            if validate:
                validation_warning = self._validate_output(final_sql, target)
                if validation_warning:
                    logger.error(
                        f"Output SQL validation failed: {source} -> {target}: "
                        f"{validation_warning}"
                    )
                    return TranspileResult(
                        success=False,
                        source_sql=sql,
                        source_dialect=source,
                        target_dialect=target,
                        error=validation_warning,
                        compatibility_notes=compat_notes,
                        transformations=transformations,
                        warnings=warnings
                    )

            if self._security_enabled and not skip_security:
                security_result = self._validate_security(sql)
                warnings.extend(security_result["warnings"])

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
                cache_key = f"{sql}|{source}|{target}|{pretty}"
                self._cache.set(cache_key, result.to_dict())

            return result

        except Exception as e:
            logger.error(f"Transpile failed: {source} -> {target}, error={str(e)}")
            return TranspileResult(
                success=False,
                source_sql=sql,
                source_dialect=source,
                target_dialect=target,
                error=str(e)
            )

    def _get_compatibility_notes(self, source: str, target: str, sql: str = "") -> List[str]:
        """Get compatibility notes for source→target conversion."""
        notes = []
        notes.extend(get_compatibility_notes(source, target))
        sql_upper = sql.upper()

        if "LIMIT" in sql_upper and target == "oracle":
            notes.append("Oracle uses FETCH FIRST n ROWS ONLY (12c+) or ROWNUM for LIMIT")
        if "AUTO_INCREMENT" in sql_upper and target not in ["mysql"]:
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

    def _generate_warnings(self, sql: str, source: str, target: str) -> List[str]:
        """Generate warnings for potential issues."""
        warnings = []
        sql_upper = sql.upper()

        if "DROP TABLE" in sql_upper or "TRUNCATE" in sql_upper:
            warnings.append("⚠️ Dangerous operation detected: DROP/TRUNCATE")
        if "DELETE" in sql_upper and "WHERE" not in sql_upper:
            warnings.append("⚠️ DELETE without WHERE clause - will delete all rows")
        if "UPDATE" in sql_upper and "WHERE" not in sql_upper:
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
        """Validate output SQL syntax."""
        try:
            sqlglot.parse_one(sql, read=dialect)
            return None
        except Exception as e:
            return f"⚠️ Output SQL may have syntax issues: {str(e)[:100]}"

    def _validate_security(self, sql: str) -> Dict[str, Any]:
        """Validate SQL for security issues."""
        result = {
            "blocked": False,
            "reason": None,
            "warnings": []
        }

        for pattern, message in DANGEROUS_SQL_PATTERNS:
            if pattern.search(sql):
                logger.warning(f"Dangerous SQL pattern detected: {message}")
                if settings.security_block_dangerous:
                    result["blocked"] = True
                    result["reason"] = message
                    return result
                result["warnings"].append(f"🔒 Security: {message}")

        for pattern, message in WARNING_SQL_PATTERNS:
            if pattern.search(sql):
                result["warnings"].append(f"⚠️ {message}")

        return result

    def batch_transpile(
        self,
        statements: List[str],
        source: str,
        target: str,
        pretty: bool = True
    ) -> List[TranspileResult]:
        """Transpile multiple SQL statements."""
        if len(statements) > settings.max_batch_size:
            statements = statements[:settings.max_batch_size]

        return [
            self.transpile(sql, source, target, pretty)
            for sql in statements
        ]

    async def batch_transpile_async(
        self,
        statements: List[str],
        source: str,
        target: str,
        pretty: bool = True,
        max_concurrent: int = 10
    ) -> List[TranspileResult]:
        """Transpile multiple SQL statements asynchronously."""
        if len(statements) > settings.max_batch_size:
            statements = statements[:settings.max_batch_size]

        semaphore = asyncio.Semaphore(max_concurrent)

        async def limited_transpile(sql: str) -> TranspileResult:
            async with semaphore:
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(
                    None,
                    lambda: self.transpile(sql, source, target, pretty)
                )

        tasks = [limited_transpile(sql) for sql in statements]
        return await asyncio.gather(*tasks)

    def get_supported_dialects(self) -> List[str]:
        """Get list of supported dialects."""
        return SUPPORTED_DIALECTS.copy()

    def get_stats(self) -> Dict[str, Any]:
        """Get transpiler statistics."""
        return {
            "supported_dialects": len(SUPPORTED_DIALECTS),
            "dialects": SUPPORTED_DIALECTS,
            "post_processor": self.post_processor.get_stats(),
            "cache": self._cache.get_stats() if self._cache_enabled else {"enabled": False},
            "security": {
                "enabled": self._security_enabled,
                "block_dangerous": settings.security_block_dangerous
            },
            "settings": {
                "cache_enabled": self._cache_enabled,
                "max_batch_size": settings.max_batch_size,
                "max_sql_length": settings.transpiler_max_sql_length
            }
        }

    def clear_cache(self) -> None:
        """Clear the transpile cache."""
        if self._cache_enabled:
            self._cache.clear()
            logger.info("Transpile cache cleared")
