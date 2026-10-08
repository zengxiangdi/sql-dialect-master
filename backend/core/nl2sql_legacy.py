#!/usr/bin/env python3
"""NL2SQL Generator - Convert natural language to SQL queries.

Provides natural language to SQL conversion with:
- Chinese and English support
- Multiple SQL dialects
- Template-based pattern matching with priority scoring
- Confidence scoring with syntax validation
- Query suggestions and explanations

The implementation delegates tokenization, templates, and language mappings to
``backend.core.nl2sql_components`` so each concern has a single source of truth.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import sqlglot

from .column_hint_validation import validate_column_hints
from .nl2sql_components.boolean_conditions import extract_boolean_conditions
from .nl2sql_components.mappings import (
    COLUMN_PATTERNS as MAPPING_COLUMN_PATTERNS,
)
from .nl2sql_components.mappings import (
    KEYWORDS as MAPPING_KEYWORDS,
)
from .nl2sql_components.mappings import (
    TABLE_PATTERNS as MAPPING_TABLE_PATTERNS,
)
from .nl2sql_components.evidence import GenerationEvidence
from .nl2sql_components.templates import DEFAULT_QUERY_TEMPLATES, QueryTemplate
from .nl2sql_components.tokenizer import Tokenizer

# P8 pipeline: pure stage functions live in nl2sql_pipeline; this class
# delegates to them so existing method call-sites keep working.
from .nl2sql_pipeline import ir as _nl2sql_ir
from .nl2sql_pipeline import models as _nl2sql_models
from .nl2sql_pipeline.aggregations import extract_aggregations as _pipeline_extract_aggregations
from .nl2sql_pipeline.clause_extract import (
    check_distinct as _pipeline_check_distinct,
    extract_group_by as _pipeline_extract_group_by,
    extract_limit as _pipeline_extract_limit,
    extract_ordering as _pipeline_extract_ordering,
)
from .nl2sql_pipeline.dialect import apply_dialect_adjustments as _apply_dialect_adjustments_impl
from .nl2sql_pipeline.intent import (
    analyze_intent as _analyze_intent,
    detect_operation as _detect_operation,
    parse_text as _parse_text_impl,
)
from .nl2sql_pipeline.predicates import extract_conditions as _extract_conditions_enhanced_impl
from .nl2sql_pipeline.renderer import add_limit as _add_limit_impl
from .nl2sql_pipeline.renderer import join_sql_kind as _join_sql_kind_impl
from .nl2sql_pipeline.renderer import render_sql as _render_sql_impl
from .nl2sql_pipeline.resolution import (
    extract_columns as _pipeline_extract_columns,
    extract_joins as _pipeline_extract_joins,
    extract_table as _pipeline_extract_table,
    extract_table_subject as _pipeline_extract_table_subject,
    guess_join_key as _pipeline_guess_join_key,
    has_relational_keyword as _pipeline_has_relational_keyword,
    named_tables as _pipeline_named_tables,
)
from .nl2sql_pipeline.suggestions import (
    generate_suggestions as _pipeline_generate_suggestions,
)
from .nl2sql_pipeline.templates import (
    generate_from_template as _pipeline_generate_from_template,
    template_suggestions as _pipeline_template_suggestions,
)
from .nl2sql_pipeline.validation import validate_sql as _validate_sql_impl

logger = logging.getLogger(__name__)

# P8: canonical source moved to nl2sql_pipeline.renderer; re-exported here
# for backward compatibility with existing import sites.
_join_sql_kind = _join_sql_kind_impl

# P8: NL2SQLResult is now defined once in nl2sql_pipeline.models; this
# re-export keeps `from backend.core.nl2sql_legacy import NL2SQLResult`
# identical to `from backend.core.nl2sql import NL2SQLResult`.
NL2SQLResult = _nl2sql_models.NL2SQLResult


class NL2SQLGenerator:
    """Natural Language to SQL Generator with multi-dialect support."""

    # Canonical mappings live in nl2sql_components.mappings.
    KEYWORDS = MAPPING_KEYWORDS
    TABLE_PATTERNS = MAPPING_TABLE_PATTERNS
    COLUMN_PATTERNS = MAPPING_COLUMN_PATTERNS

    def __init__(self, default_dialect: str = "hive"):
        """Initialize generator with default dialect and template system."""
        self.default_dialect = default_dialect
        self.tokenizer = Tokenizer()
        self._init_query_templates()

    def _init_query_templates(self) -> None:
        """Initialize prioritized query templates from the canonical module."""
        self.query_templates: List[QueryTemplate] = list(DEFAULT_QUERY_TEMPLATES)
        self.query_templates.sort(key=lambda template: template.priority, reverse=True)

    def _match_templates(
        self, text: str
    ) -> Tuple[Optional[QueryTemplate], Optional[Dict[str, Any]]]:
        """Try to match input text against query templates.

        Explicit INSERT/UPDATE/DELETE requests bypass template matching and
        flow through the enhanced semantic builder instead.
        """
        operation = self._detect_operation(text)
        if operation in {"INSERT", "UPDATE", "DELETE"}:
            return None, None
        for template in self.query_templates:
            match_result = template.match(text)
            if match_result:
                logger.debug(
                    "Matched template '%s' with priority %s",
                    template.name,
                    template.priority,
                )
                return template, match_result
        return None, None

    def _tokenize_and_analyze(self, text: str) -> Dict[str, Any]:
        """Tokenize text and perform semantic analysis.

        P8: delegates to ``nl2sql_pipeline.intent.analyze_intent``.
        """
        return _analyze_intent(text)

    def _generate_from_template(
        self,
        template: QueryTemplate,
        match_groups: Dict[str, Any],
        analysis: Dict[str, Any],
        dialect: str,
        table_hint: Optional[str],
        column_hints: Optional[List[str]],
        text_lower: str = "",
        text_original: str = "",
    ) -> NL2SQLResult:
        """Generate SQL from a matched template.

        P8: implementation moved to ``nl2sql_pipeline.templates``.
        This adapter preserves the legacy call signature.
        """
        return _pipeline_generate_from_template(
            template, match_groups, analysis, dialect,
            table_hint, column_hints,
            text_lower, text_original,
            table_patterns=self.TABLE_PATTERNS,
            column_patterns=self.COLUMN_PATTERNS,
        )

    def _generate_suggestions_for_template(
        self,
        template: QueryTemplate,
        table: str,
        columns: List[str],
        dialect: str,
    ) -> List[str]:
        """Generate suggestions specific to template-based generation.

        P8: implementation moved to ``nl2sql_pipeline.templates``.
        """
        return _pipeline_template_suggestions(template, table, columns, dialect)

    def generate(
        self,
        text: str,
        dialect: str = None,
        table_hint: str = None,
        column_hints: List[str] = None,
    ) -> NL2SQLResult:
        """Generate SQL from natural language text."""
        # Validate inputs
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        normalized_dialect = (dialect or self.default_dialect).strip().lower()
        from .config import SUPPORTED_DIALECTS
        if normalized_dialect not in SUPPORTED_DIALECTS:
            raise ValueError(f"Unsupported dialect: {dialect}. Supported: {', '.join(SUPPORTED_DIALECTS)}")
        import re
        _SAFE_TABLE_HINT = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)*")
        normalized_table_hint = table_hint.strip() if isinstance(table_hint, str) else table_hint
        if normalized_table_hint and not _SAFE_TABLE_HINT.fullmatch(normalized_table_hint):
            raise ValueError("table_hint must be a simple SQL identifier or dotted identifier")
        column_hints_error = validate_column_hints(column_hints)
        if column_hints_error:
            return NL2SQLResult(
                success=False,
                input_text=text,
                dialect=normalized_dialect,
                explanation=column_hints_error,
                confidence=0.0,
                evidence=GenerationEvidence(),
            )
        # Length guard (from production_hardening)
        from .config import settings
        max_input_length = getattr(settings, "nl2sql_max_input_length", 8192)
        if len(text) > max_input_length:
            return NL2SQLResult(
                success=False,
                input_text=text[:200] + "...",
                dialect=normalized_dialect,
                explanation=f"Input text exceeds maximum length of {max_input_length} characters",
                suggestions=["Please shorten the natural-language query and try again."],
                evidence=GenerationEvidence(),
            )
        dialect = normalized_dialect
        table_hint = normalized_table_hint
        if column_hints_error:
            return NL2SQLResult(
                success=False,
                input_text=text if isinstance(text, str) else "",
                dialect=dialect,
                explanation=column_hints_error,
                confidence=0.0,
                evidence=GenerationEvidence(),
            )
        text_lower = text.lower()

        log_text = text[:50].replace("\r", "\\r").replace("\n", "\\n")
        logger.info("NL2SQL: Processing '%s...' for dialect %s", log_text, dialect)
        analysis = self._tokenize_and_analyze(text)
        logger.debug(
            "Token analysis: %d tokens, %d tables, %d columns",
            len(analysis["tokens"]),
            len(analysis["tables"]),
            len(analysis["columns"]),
        )

        boolean_conditions = extract_boolean_conditions(text_lower)
        has_explicit_null_predicate = any(
            keyword in text_lower
            for keyword in [
                "为空",
                "空值",
                "is null",
                "null",
                "empty",
                "非空",
                "不为空",
                "is not null",
                "not null",
                "not empty",
            ]
        )
        if boolean_conditions or has_explicit_null_predicate:
            parsed = self._parse_text(text_lower, text)
            parsed.update(analysis)
            operation = self._detect_operation(text_lower)
            if self._has_relational_keyword(text_lower):
                # Relational subject: 'users who have orders where price = 5'
                # must yield FROM users, not FROM orders.
                table = (
                    table_hint
                    or self._extract_table_subject(text_lower)
                    or self._extract_table(text_lower)
                )
            else:
                table = table_hint or self._extract_table(text_lower)
            columns = column_hints if column_hints else self._extract_columns(text_lower)
            conditions = self._extract_conditions_enhanced(text_lower, text)
            aggregations = self._extract_aggregations(text_lower)
            group_by = self._extract_group_by(text_lower)
            ordering = self._extract_ordering(text_lower)
            limit = self._extract_limit(text_lower)
            joins = self._extract_joins(text_lower)
            distinct = self._check_distinct(text_lower)
            sql, explanation, confidence, evidence = self._build_sql_enhanced(
                operation,
                table,
                columns,
                conditions,
                aggregations,
                group_by,
                ordering,
                limit,
                joins,
                distinct,
                dialect,
            )
            if sql is None:
                # Fail-closed: _build_sql_enhanced rejected an unresolved
                # relationship. Surface an actionable suggestion.
                suggestions = [
                    "Specify the relationship between tables, e.g., "
                    "'users.id = invoices.user_id'",
                ]
            else:
                suggestions = self._generate_suggestions(text, sql, dialect)
            return NL2SQLResult(
                success=sql is not None,
                input_text=text,
                sql=sql,
                dialect=dialect,
                explanation=explanation,
                confidence=confidence,
                evidence=evidence,
                suggestions=suggestions,
                parsed_elements=parsed,
            )

        template, match_groups = self._match_templates(text_lower)
        # If relational keywords detected (D2), bypass templates and use enhanced path
        # to ensure EXISTS/NOT EXISTS structure instead of physical JOIN
        if template and self._has_relational_keyword(text_lower):
            template = None
            logger.debug("NL2SQL: Relational keyword detected, bypassing template matching")
        if template:
            result = self._generate_from_template(
                template, match_groups, analysis, dialect, table_hint, column_hints,
                text_lower, text,
            )
            if result.success:
                logger.info(
                    "NL2SQL: Template '%s' matched with confidence %.2f",
                    template.name,
                    result.confidence,
                )
                return result

        logger.debug("NL2SQL: Falling back to keyword-based extraction")
        parsed = self._parse_text(text_lower, text)
        parsed.update(analysis)
        operation = self._detect_operation(text_lower)
        columns = column_hints if column_hints else self._extract_columns(text_lower)
        conditions = self._extract_conditions_enhanced(text_lower, text)
        aggregations = self._extract_aggregations(text_lower)
        group_by = self._extract_group_by(text_lower)
        ordering = self._extract_ordering(text_lower)
        limit = self._extract_limit(text_lower)
        joins = self._extract_joins(text_lower)
        distinct = self._check_distinct(text_lower)

        # Table-name ownership (G1): a request that mentions two or more
        # tables is a relational/join request; it only succeeds when every
        # pair between the mentioned tables has a canonical relationship.
        named_tables = self._named_tables(text_lower)
        if len(named_tables) >= 2:
            table = table_hint or named_tables[0]
            unresolved = [
                j for j in joins if j.get("condition") is None
            ]
            if unresolved:
                # Use the subject carried by each join entry so the pair
                # description is accurate even when the final table variable
                # was resolved differently.
                pair_desc = " ⟷ ".join(
                    [j.get("subject") or table for j in unresolved]
                    + [j["table"] for j in unresolved]
                )
                return NL2SQLResult(
                    success=False,
                    input_text=text,
                    sql=None,
                    dialect=dialect,
                    explanation=(
                        "Unable to safely infer the relationship between the "
                        f"table(s) involved ({pair_desc}). Please provide the join "
                        "condition or schema relationship."
                    ),
                    confidence=0.0,
                    evidence=GenerationEvidence(),
                    suggestions=[
                        "Specify the relationship between tables, e.g., "
                        "'users.id = invoices.user_id'",
                    ],
                )
        else:
            # For D2 relational queries, use table_hint if provided, else first detected table
            if self._has_relational_keyword(text_lower):
                table = table_hint or self._extract_table_subject(text_lower) or "table_name"
            else:
                table = table_hint or self._extract_table(text_lower)

        sql, explanation, confidence, evidence = self._build_sql_enhanced(
            operation,
            table,
            columns,
            conditions,
            aggregations,
            group_by,
            ordering,
            limit,
            joins,
            distinct,
            dialect,
        )
        if sql is None:
            # Fail-closed: _build_sql_enhanced rejected an unresolved
            # relationship (e.g. single-table path where the join table
            # has no canonical FK). Surface an actionable suggestion.
            suggestions = [
                "Specify the relationship between tables, e.g., "
                "'users.id = invoices.user_id'",
            ]
        else:
            suggestions = self._generate_suggestions(text, sql, dialect)

        return NL2SQLResult(
            success=sql is not None,
            input_text=text,
            sql=sql,
            dialect=dialect,
            explanation=explanation,
            confidence=confidence,
            evidence=evidence,
            suggestions=suggestions,
            parsed_elements=parsed,
        )

    def _parse_text(self, text_lower: str, original: str) -> dict:
        """Parse and extract all elements from text.

        P8: delegates to ``nl2sql_pipeline.intent.parse_text``.
        """
        return _parse_text_impl(text_lower, original)

    def _detect_operation(self, text: str) -> str:
        """Detect SQL operation type from text.

        P8: delegates to ``nl2sql_pipeline.intent.detect_operation``.
        """
        return _detect_operation(text)

    def _extract_table(self, text: str) -> str:
        """Extract table name from text.

        P8: delegates to ``nl2sql_pipeline.resolution.extract_table``.
        """
        return _pipeline_extract_table(text, self.TABLE_PATTERNS)

    def _extract_table_subject(self, text: str) -> Optional[str]:
        """Extract the subject table (first appearing in text) for D2 relational queries.

        P8: delegates to ``nl2sql_pipeline.resolution.extract_table_subject``.
        """
        return _pipeline_extract_table_subject(text, self.TABLE_PATTERNS)

    def _named_tables(self, text: str) -> list:
        """Return the distinct table names the text mentions.

        P8: delegates to ``nl2sql_pipeline.resolution.named_tables``.
        """
        return _pipeline_named_tables(text, self.TABLE_PATTERNS)

    def _extract_columns(self, text: str) -> list:
        """Extract column names from text.

        P8: delegates to ``nl2sql_pipeline.resolution.extract_columns``.
        """
        return _pipeline_extract_columns(text, self.COLUMN_PATTERNS)

    def _extract_conditions_enhanced(self, text: str, original: str) -> list:
        """Extract WHERE conditions with enhanced parsing including boolean expressions.

        P8: delegates to ``nl2sql_pipeline.predicates.extract_conditions``.
        """
        return _extract_conditions_enhanced_impl(
            text, original, self.COLUMN_PATTERNS
        )

    def _extract_aggregations(self, text: str) -> list:
        """Extract aggregation functions from text.

        P8: delegates to ``nl2sql_pipeline.aggregations.extract_aggregations``.
        """
        return _pipeline_extract_aggregations(text, self.COLUMN_PATTERNS)

    def _extract_group_by(self, text: str) -> list:
        """Extract GROUP BY columns from text.

        P8: delegates to ``nl2sql_pipeline.clause_extract.extract_group_by``.
        """
        return _pipeline_extract_group_by(text, self.COLUMN_PATTERNS, self.TABLE_PATTERNS)

    def _extract_ordering(self, text: str) -> Optional[Tuple[str, str]]:
        """Extract ORDER BY clause from text.

        P8: delegates to ``nl2sql_pipeline.clause_extract.extract_ordering``.
        """
        return _pipeline_extract_ordering(text, self.COLUMN_PATTERNS)

    def _extract_limit(self, text: str) -> Optional[int]:
        """Extract LIMIT value from text.

        P8: delegates to ``nl2sql_pipeline.clause_extract.extract_limit``.
        """
        return _pipeline_extract_limit(text)

    def _extract_joins(self, text: str) -> list:
        """Extract JOIN information from text.

        P8: delegates to ``nl2sql_pipeline.resolution.extract_joins``.
        Detects relational existence patterns (e.g., "users who have orders")
        and returns structured join contexts for EXISTS-based SQL generation.
        """
        return _pipeline_extract_joins(text, self.TABLE_PATTERNS)

    def _guess_join_key(self, table1: str, table2: str) -> Optional[str]:
        """Guess the join key between two tables.

        P8: delegates to ``nl2sql_pipeline.resolution.guess_join_key``.
        Returns None for unknown relationships instead of guessing.
        """
        return _pipeline_guess_join_key(table1, table2)

    def _check_distinct(self, text: str) -> bool:
        """Check if DISTINCT is needed.

        P8: delegates to ``nl2sql_pipeline.clause_extract.check_distinct``.
        """
        return _pipeline_check_distinct(text)

    def _has_relational_keyword(self, text: str) -> bool:
        """Check if text contains relational existence keywords (D2).

        P8: delegates to ``nl2sql_pipeline.resolution.has_relational_keyword``.
        """
        return _pipeline_has_relational_keyword(text)

    def _build_sql_enhanced(
        self,
        operation,
        table,
        columns,
        conditions,
        aggregations,
        group_by,
        ordering,
        limit,
        joins,
        distinct,
        dialect,
    ) -> tuple:
        """Build SQL statement from extracted components.

        P8: implementation moved to ``nl2sql_pipeline.renderer.render_sql``.
        This method is a thin adapter that preserves the legacy call
        signature.  Fail-closed behaviour (unresolved join → success=False)
        is enforced by ``render_sql``.
        """
        ir = _nl2sql_ir.build_ir(
            operation, table, columns, conditions, aggregations,
            group_by, ordering, limit, joins, distinct, dialect,
        )
        return _render_sql_impl(ir)

    def _validate_generated_sql(self, sql: str, dialect: str) -> float:
        """Validate generated SQL syntax and return confidence adjustment.

        P8: delegates to ``nl2sql_pipeline.validation.validate_sql``.
        """
        return _validate_sql_impl(sql, dialect)

    def _add_limit(self, sql: str, limit: int, dialect: str) -> str:
        """Add LIMIT clause with dialect-specific syntax.

        P8: delegates to ``nl2sql_pipeline.renderer.add_limit``.
        """
        return _add_limit_impl(sql, limit, dialect)

    def _apply_dialect_adjustments(self, sql: str, dialect: str) -> str:
        """Apply dialect-specific syntax adjustments.

        P8: delegates to ``nl2sql_pipeline.dialect.apply_dialect_adjustments``
        (moved unchanged — executable-region-aware regex rewriter).
        """
        return _apply_dialect_adjustments_impl(sql, dialect)

    def _generate_suggestions(self, text: str, sql: str, dialect: str) -> list:
        """Generate improvement suggestions.

        P8: delegates to ``nl2sql_pipeline.suggestions.generate_suggestions``.
        """
        return _pipeline_generate_suggestions(text, sql, dialect)

    def _extract_conditions(self, text: str) -> list:
        """Backward-compatible alias for enhanced condition extraction."""
        return self._extract_conditions_enhanced(text, text)

    def _build_sql(
        self,
        operation,
        table,
        columns,
        conditions,
        aggregations,
        ordering,
        limit,
        dialect,
    ) -> tuple:
        """Backward-compatible alias for enhanced SQL building."""
        return self._build_sql_enhanced(
            operation,
            table,
            columns,
            conditions,
            aggregations,
            [],
            ordering,
            limit,
            [],
            False,
            dialect,
        )
