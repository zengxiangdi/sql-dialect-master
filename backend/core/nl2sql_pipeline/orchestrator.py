#!/usr/bin/env python3
"""P8 NL2SQL pipeline: orchestrator (moved from nl2sql_legacy).

``PipelineNL2SQLGenerator`` is the canonical base class the facade
(``backend.core.nl2sql``) extends.  It owns the three-code-path
``generate()`` dispatch:

1. boolean/null fast path
2. template path (relational-keyword bypass)
3. enhanced fallback (G1 named-tables fail-closed gate)

All per-stage logic delegates to the pure stage modules
(``intent``, ``resolution``, ``predicates``, ``aggregations``,
``clause_extract``, ``templates``, ``ir``, ``renderer``, ``dialect``,
``validation``, ``suggestions``).  Instance-method signatures are
unchanged so the facade's ``super()`` overrides resolve exactly as they
did against the legacy class.
"""
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import sqlglot

from ..column_hint_validation import validate_column_hints
from ..nl2sql_components.boolean_conditions import extract_boolean_conditions
from ..nl2sql_components.evidence import GenerationEvidence
from ..nl2sql_components.mappings import (
    COLUMN_PATTERNS as MAPPING_COLUMN_PATTERNS,
    KEYWORDS as MAPPING_KEYWORDS,
    TABLE_PATTERNS as MAPPING_TABLE_PATTERNS,
)
from ..nl2sql_components.relations import JoinSpec, parse_join_spec
from ..nl2sql_components.templates import DEFAULT_QUERY_TEMPLATES, QueryTemplate
from ..nl2sql_components.tokenizer import Tokenizer
from ..p1_sql_scanner import mask_non_executable
from ..nl2sql_schema import (
    SchemaContext,
    SchemaTableContext,
    SchemaValidationError,
    validate_schema_references,
)
from ..sql_statements import parse_single_sql
from . import ir as _nl2sql_ir
from .aggregations import extract_aggregations as _pipeline_extract_aggregations
from .clause_extract import (
    check_distinct as _pipeline_check_distinct,
    extract_group_by as _pipeline_extract_group_by,
    extract_limit as _pipeline_extract_limit,
    extract_ordering as _pipeline_extract_ordering,
)
from .dialect import apply_dialect_adjustments as _apply_dialect_adjustments_impl
from .intent import (
    analyze_intent as _analyze_intent,
    detect_operation as _detect_operation,
    parse_text as _parse_text_impl,
)
from .models import NL2SQLResult
from .predicates import extract_conditions as _extract_conditions_enhanced_impl
from .renderer import add_limit as _add_limit_impl
from .renderer import render_sql as _render_sql_impl
from .resolution import (
    extract_columns as _pipeline_extract_columns,
    extract_joins as _pipeline_extract_joins,
    extract_table as _pipeline_extract_table,
    extract_table_subject as _pipeline_extract_table_subject,
    guess_join_key as _pipeline_guess_join_key,
    has_relational_keyword as _pipeline_has_relational_keyword,
    named_tables as _pipeline_named_tables,
)
from .suggestions import generate_suggestions as _pipeline_generate_suggestions
from .templates import (
    generate_from_template as _pipeline_generate_from_template,
    template_suggestions as _pipeline_template_suggestions,
)
from .validation import validate_sql as _validate_sql_impl

logger = logging.getLogger(__name__)

# Canonical table_hint identifier rule, shared by the orchestrator (which
# raises ValueError for direct callers) and the API boundary (which
# converts the violation into a 4xx validation error before generation).
SAFE_TABLE_HINT = re.compile(
    r"[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)*"
)
_UNSUPPORTED_DDL = re.compile(
    r"(?<![\w$])(drop|create|alter|truncate|grant|revoke)(?![\w$])",
    re.IGNORECASE,
)
_UNSUPPORTED_CN_DDL = re.compile(
    r"(?:删除|移除|清空|清除|截断|创建|新建|建立|修改|变更|更改)"
    r"\s*[^\s,，。;；]{0,32}?(?:数据库|数据表|索引|视图|表)"
)
_DATE_INTERVAL = re.compile(
    r"(?:最近|过去|(?<![\w$])(?:last|past)(?![\w$]))\s*(-?\d+)\s*"
    r"(天|日|周|星期|月|年|days?(?![\w$])|weeks?(?![\w$])|"
    r"months?(?![\w$])|years?(?![\w$]))",
    re.IGNORECASE,
)
MAX_NL2SQL_DATE_INTERVAL_DAYS = 36525


class PipelineNL2SQLGenerator:
    """NL2SQL pipeline base class.

    Identical in behaviour to the legacy ``NL2SQLGenerator`` — it merely
    delegates every per-stage concern to a pure function in the
    ``nl2sql_pipeline`` package so the class body reads as an explicit
    orchestration of the target stages:

        Intent → Entity Resolution → Relation Resolution →
        Predicate Resolution → Query IR → Dialect Renderer →
        AST Validation → Evidence/Confidence
    """

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

        Delegates to ``nl2sql_pipeline.intent.analyze_intent``.
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

        Delegates to ``nl2sql_pipeline.templates.generate_from_template``.
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

        Delegates to ``nl2sql_pipeline.templates.template_suggestions``.
        """
        return _pipeline_template_suggestions(template, table, columns, dialect)

    def generate(
        self,
        text: str,
        dialect: str = None,
        table_hint: str = None,
        column_hints: List[str] = None,
        schema: SchemaContext | None = None,
    ) -> NL2SQLResult:
        """Generate SQL from natural language text."""
        # Validate inputs
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        if not text.strip():
            return self._apply_confidence_policy(NL2SQLResult(
                success=False,
                input_text=text,
                dialect=(dialect or self.default_dialect).strip().lower(),
                explanation="Natural-language input cannot be empty",
                suggestions=["Describe the query you want to generate."],
                evidence=GenerationEvidence(),
            ))
        normalized_dialect = (dialect or self.default_dialect).strip().lower()
        from ..config import SUPPORTED_DIALECTS
        if normalized_dialect not in SUPPORTED_DIALECTS:
            raise ValueError(
                f"Unsupported dialect: {dialect}. "
                f"Supported: {', '.join(SUPPORTED_DIALECTS)}"
            )
        normalized_table_hint = (
            table_hint.strip() if isinstance(table_hint, str) else table_hint
        )
        if normalized_table_hint and not SAFE_TABLE_HINT.fullmatch(normalized_table_hint):
            raise ValueError(
                "table_hint must be a simple SQL identifier or dotted identifier"
            )
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
        from ..config import settings
        max_input_length = getattr(settings, "nl2sql_max_input_length", 8192)
        if len(text) > max_input_length:
            return NL2SQLResult(
                success=False,
                input_text=text[:200] + "...",
                dialect=normalized_dialect,
                explanation=(
                    f"Input text exceeds maximum length of "
                    f"{max_input_length} characters"
                ),
                suggestions=["Please shorten the natural-language query and try again."],
                evidence=GenerationEvidence(),
            )
        executable_intent = mask_non_executable(text)
        ddl_match = _UNSUPPORTED_DDL.search(executable_intent)
        cn_ddl_match = _UNSUPPORTED_CN_DDL.search(executable_intent)
        if ddl_match or cn_ddl_match:
            operation = ddl_match.group(1).upper() if ddl_match else cn_ddl_match.group(0)
            return NL2SQLResult(
                success=False,
                input_text=text,
                dialect=normalized_dialect,
                explanation=f"DDL operation {operation} is not supported by NL2SQL",
                confidence=0.0,
                suggestions=["Use SELECT, INSERT, UPDATE, or DELETE explicitly."],
                evidence=GenerationEvidence(),
            )
        max_interval_days = getattr(
            settings, "nl2sql_max_date_interval_days", MAX_NL2SQL_DATE_INTERVAL_DAYS,
        )
        for interval_match in _DATE_INTERVAL.finditer(executable_intent):
            raw_value, unit = interval_match.groups()
            if raw_value.startswith("-"):
                return NL2SQLResult(
                    success=False, input_text=text, dialect=normalized_dialect,
                    explanation="Date interval cannot be negative", confidence=0.0,
                    suggestions=["Use a non-negative date interval."], evidence=GenerationEvidence(),
                )
            # Keep the lexical representation bounded too: downstream stages
            # parse this number again. Normal leading zeros are valid, while
            # thousands of zero digits cannot reach an unbounded int().
            if len(raw_value) > 64:
                return NL2SQLResult(
                    success=False, input_text=text, dialect=normalized_dialect,
                    explanation="Date interval representation exceeds the maximum supported length",
                    confidence=0.0, suggestions=["Use a shorter date interval number."],
                    evidence=GenerationEvidence(),
                )
            normalized_amount = raw_value.lstrip("0") or "0"
            amount = (
                max_interval_days + 1
                if len(normalized_amount) > len(str(max_interval_days))
                else int(normalized_amount)
            )
            unit_lower = unit.lower()
            multiplier = 1
            if unit_lower in {"周", "星期", "week", "weeks"}:
                multiplier = 7
            elif unit_lower in {"月", "month", "months"}:
                multiplier = 31
            elif unit_lower in {"年", "year", "years"}:
                multiplier = 366
            if amount * multiplier > max_interval_days:
                return NL2SQLResult(
                    success=False, input_text=text, dialect=normalized_dialect,
                    explanation=(
                        "Date interval exceeds the maximum supported range of "
                        f"{max_interval_days} days"
                    ), confidence=0.0,
                    suggestions=["Use a shorter date interval."], evidence=GenerationEvidence(),
                )
        # Validate an explicitly requested row limit before the extraction
        # stage.  This turns huge numeric literals into a controlled failed
        # generation instead of an uncaught int-conversion exception (500 at
        # the API boundary), and prevents silently dropping the limit.
        try:
            self._extract_limit(text)
        except ValueError as exc:
            return NL2SQLResult(
                success=False,
                input_text=text,
                dialect=normalized_dialect,
                explanation=str(exc),
                confidence=0.0,
                suggestions=["Use a LIMIT value no greater than 1000000."],
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
        # Fail closed for text with no recognized intent, entity, predicate,
        # or time expression.  This prevents arbitrary words from becoming
        # ``SELECT * FROM table_name`` while preserving useful bare period
        # requests such as ``last 7 days`` and ``today``.
        recognized_time = bool(
            re.search(
                r"(?:今天|昨天|前天|明天|本周|本月|本年|"
                r"(?<![\w$])(?:today|yesterday|tomorrow|last|past|recent|"
                r"week|month|year|day)(?![\w$]))",
                executable_intent.lower(),
                re.IGNORECASE,
            )
        )
        recognized_intent = bool(
            analysis.get("tables")
            or analysis.get("columns")
            or analysis.get("operations")
            or extract_boolean_conditions(text_lower)
            or recognized_time
        )
        if schema is not None:
            if not schema.is_valid:
                return self._schema_failure(
                    text, dialect, "The provided schema is invalid."
                )
            schema_tables = self._schema_table_mentions(text, schema)
            recognized_intent = recognized_intent or bool(schema_tables)
        if not recognized_intent:
            return NL2SQLResult(
                success=False,
                input_text=text,
                dialect=dialect,
                explanation="Unable to recognize a SQL intent or supported entity",
                confidence=0.0,
                suggestions=["Mention an operation and table, e.g. 'show all users'."],
                evidence=GenerationEvidence(),
            )

        if schema is not None:
            return self._generate_with_schema(
                text,
                text_lower,
                dialect,
                table_hint,
                column_hints,
                analysis,
                schema,
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
            cn_rel_table = self._cn_relation_table(text_lower)
            if self._has_relational_keyword(text_lower):
                # Relational subject: 'users who have orders where price = 5'
                # must yield FROM users, not FROM orders.
                table = (
                    table_hint
                    or self._extract_table_subject(text_lower, cn_rel_table)
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
                operation, table, columns, conditions, aggregations,
                group_by, ordering, limit, joins, distinct, dialect,
            )
            if sql is None:
                suggestions = [
                    "Specify the relationship between tables, e.g., "
                    "'users.id = invoices.user_id'",
                ]
            else:
                suggestions = self._generate_suggestions(text, sql, dialect)
            return self._apply_confidence_policy(NL2SQLResult(
                success=sql is not None,
                input_text=text,
                sql=sql,
                dialect=dialect,
                explanation=explanation,
                confidence=confidence,
                evidence=evidence,
                suggestions=suggestions,
                parsed_elements=parsed,
            ))

        template, match_groups = self._match_templates(text_lower)
        # If relational keywords detected (D2), bypass templates and use
        # the enhanced path to ensure EXISTS/NOT EXISTS structure instead
        # of a physical JOIN.
        if template and self._has_relational_keyword(text_lower):
            template = None
            logger.debug("NL2SQL: Relational keyword detected, bypassing template matching")
        # A select/simpler template that captures a request naming two
        # tables via Chinese connectives (用户 和 发票) must route to the
        # enhanced path too: the select_with_columns / simple_select
        # templates would silently drop the second table's relationship
        # instead of failing closed.
        elif template and template.name in ("select_with_columns", "simple_select"):
            if len(self._named_tables(text_lower)) >= 2:
                template = None
                logger.debug("NL2SQL: multi-table select captured by select template, bypassing")
        if template:
            result = self._generate_from_template(
                template, match_groups, analysis, dialect,
                table_hint, column_hints, text_lower, text,
            )
            result = self._apply_confidence_policy(result)
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
        cn_rel_table = self._cn_relation_table(text_lower)
        if len(named_tables) >= 2:
            # Relational subject-table resolution: when the request carries
            # a relational connective (D2/CN 有<relation>的<subject>), the
            # outer FROM is the subject table, not the relation table the
            # connective names.
            table = (
                table_hint
                or (
                    self._extract_table_subject(text_lower, cn_rel_table)
                    if self._has_relational_keyword(text_lower)
                    else named_tables[0]
                )
            )
            unresolved = [j for j in joins if j.get("condition") is None]
            if unresolved:
                pair_desc = " ⟷ ".join(
                    [j.get("subject") or table for j in unresolved]
                    + [j["table"] for j in unresolved]
                )
                return self._apply_confidence_policy(NL2SQLResult(
                    success=False,
                    input_text=text,
                    sql=None,
                    dialect=dialect,
                    explanation=(
                        "Unable to safely infer the relationship between the "
                        f"table(s) involved ({pair_desc}). Please provide the "
                        "join condition or schema relationship."
                    ),
                    confidence=0.0,
                    evidence=GenerationEvidence(),
                    suggestions=[
                        "Specify the relationship between tables, e.g., "
                        "'users.id = invoices.user_id'",
                    ],
                ))
        else:
            cn_rel_table = self._cn_relation_table(text_lower)
            if self._has_relational_keyword(text_lower):
                table = (
                    table_hint
                    or self._extract_table_subject(text_lower, cn_rel_table)
                    or "table_name"
                )
            else:
                table = table_hint or self._extract_table(text_lower)

        sql, explanation, confidence, evidence = self._build_sql_enhanced(
            operation, table, columns, conditions, aggregations,
            group_by, ordering, limit, joins, distinct, dialect,
        )
        if sql is None:
            suggestions = [
                "Specify the relationship between tables, e.g., "
                "'users.id = invoices.user_id'",
            ]
        else:
            suggestions = self._generate_suggestions(text, sql, dialect)

        return self._apply_confidence_policy(NL2SQLResult(
            success=sql is not None,
            input_text=text,
            sql=sql,
            dialect=dialect,
            explanation=explanation,
            confidence=confidence,
            evidence=evidence,
            suggestions=suggestions,
            parsed_elements=parsed,
        ))

    @staticmethod
    def _schema_failure(text: str, dialect: str, explanation: str) -> NL2SQLResult:
        return NL2SQLResult(
            success=False,
            input_text=text,
            dialect=dialect,
            sql=None,
            explanation=explanation,
            confidence=0.0,
            suggestions=["Provide an unambiguous table, column, or schema relationship."],
            evidence=GenerationEvidence(),
            schema_used=False,
        )

    @staticmethod
    def _schema_text_match(text: str, pattern: str) -> Optional[re.Match]:
        if pattern.isascii():
            return re.search(
                r"(?<![\w$])" + re.escape(pattern) + r"(?![\w$])",
                text,
                re.IGNORECASE,
            )
        return re.search(re.escape(pattern), text, re.IGNORECASE)

    def _schema_table_mentions(
        self, text: str, schema: SchemaContext
    ) -> list[SchemaTableContext]:
        """Find exact schema names and uniquely mapped existing aliases."""
        found: dict[str, tuple[int, SchemaTableContext]] = {}
        for table in schema.tables:
            match = self._schema_text_match(text, table.name)
            if match:
                found.setdefault(table.key, (match.start(), table))
        for pattern, mapped_name in self.TABLE_PATTERNS.items():
            if pattern == "order" and re.search(r"\border\b\s+by\b", text, re.IGNORECASE):
                continue
            candidates = schema.table_candidates(mapped_name)
            if len(candidates) != 1:
                continue
            match = self._schema_text_match(text, pattern)
            if match:
                table = candidates[0]
                found.setdefault(table.key, (match.start(), table))
        return [table for _, table in sorted(found.values(), key=lambda item: item[0])]

    def _schema_unknown_table_patterns(
        self, text: str, schema: SchemaContext
    ) -> list[str]:
        """Return mapped table names mentioned by the request but absent in schema."""
        unknown: list[str] = []
        for pattern, mapped in self.TABLE_PATTERNS.items():
            if pattern == "order" and re.search(r"\border\b\s+by\b", text, re.IGNORECASE):
                continue
            if not self._schema_text_match(text, pattern):
                continue
            if schema.table_candidates(mapped):
                continue
            if mapped in {"table", "data"}:
                continue
            unknown.append(mapped)
        return sorted(set(unknown))

    def _schema_resolve_table(
        self,
        text: str,
        table_hint: Optional[str],
        schema: SchemaContext,
    ) -> SchemaTableContext:
        if table_hint:
            candidates = schema.table_candidates(table_hint)
            if len(candidates) == 1:
                return candidates[0]
            raise SchemaValidationError("table hint is not a unique schema table")
        candidates = self._schema_table_mentions(text, schema)
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            if len(schema.tables) == 1:
                return schema.tables[0]
            raise SchemaValidationError("no schema table matched the request")
        raise SchemaValidationError("multiple schema tables matched the request")

    def _schema_resolve_columns(
        self,
        text: str,
        table: SchemaTableContext,
        column_hints: Optional[List[str]],
        schema: SchemaContext,
    ) -> list[str]:
        if column_hints:
            resolved: list[str] = []
            for hint in column_hints:
                parts = hint.split(".")
                target_table = table
                if len(parts) > 1:
                    table_candidates = schema.table_candidates(".".join(parts[:-1]))
                    if len(table_candidates) != 1 or table_candidates[0].key != table.key:
                        raise SchemaValidationError("column hint table is not the selected schema table")
                    target_table = table_candidates[0]
                column_name = parts[-1]
                canonical = schema.canonical_column(target_table, column_name)
                if target_table.has_column_metadata and canonical is None:
                    raise SchemaValidationError("column hint is outside the schema")
                canonical = canonical or column_name
                resolved.append(
                    f"{target_table.name}.{canonical}" if len(parts) > 1 else canonical
                )
            return resolved

        projection_text = mask_non_executable(self._schema_projection_text(text))
        candidates: list[tuple[int, int, str]] = []
        column_names = list(table.columns)
        for column in column_names:
            variants = [column]
            if not column.casefold().endswith("s"):
                variants.append(column + "s")
            for variant in variants:
                pattern = re.escape(variant)
                if not re.search(r"[\u4e00-\u9fff]", variant):
                    pattern = rf"(?<![\w$]){pattern}(?![\w$])"
                for match in re.finditer(pattern, projection_text, re.IGNORECASE):
                    candidates.append((match.start(), match.end(), column))
                qualified = re.escape(table.name) + r"\." + re.escape(variant)
                for match in re.finditer(qualified, projection_text, re.IGNORECASE):
                    candidates.append((match.start(), match.end(), column))

        mapped_columns = self._extract_columns(projection_text)
        if mapped_columns != ["*"]:
            for mapped_column in mapped_columns:
                canonical = schema.canonical_column(table, mapped_column)
                if canonical is None:
                    raise SchemaValidationError("mapped projection column is outside the schema")
                aliases = [
                    alias for alias, value in self.COLUMN_PATTERNS.items()
                    if value.casefold() == mapped_column.casefold()
                ] + [canonical]
                for alias in aliases:
                    pattern = re.escape(alias)
                    if not re.search(r"[\u4e00-\u9fff]", alias):
                        pattern = rf"(?<![\w$]){pattern}(?![\w$])"
                    for match in re.finditer(pattern, projection_text, re.IGNORECASE):
                        candidates.append((match.start(), match.end(), canonical))

        selected: list[tuple[int, int, str]] = []
        for candidate in sorted(candidates, key=lambda item: (item[0], -(item[1] - item[0]))):
            if any(candidate[0] < existing[1] and existing[0] < candidate[1] for existing in selected):
                continue
            selected.append(candidate)
        if selected:
            deduplicated: list[str] = []
            seen_columns: set[str] = set()
            for _, _, column in selected:
                key = column.casefold()
                if key in seen_columns:
                    continue
                seen_columns.add(key)
                deduplicated.append(column)
            return deduplicated

        columns = self._extract_columns(text)
        if columns == ["*"]:
            for candidate in table.columns:
                if self._schema_text_match(text, candidate):
                    columns.append(candidate)
            if len(columns) > 1:
                columns.remove("*")
        if not table.has_column_metadata:
            return columns
        resolved = []
        for column in columns:
            if column == "*":
                resolved.append(column)
                continue
            canonical = schema.canonical_column(table, column)
            if canonical is None:
                raise SchemaValidationError("column is outside the schema")
            resolved.append(canonical)
        return resolved

    @staticmethod
    def _schema_projection_text(text: str) -> str:
        """Mask explicit ordering clauses so their columns are not projected."""
        match = re.search(
            r"\b(?:order(?:ed)?|sort(?:ed)?)\s+by\b",
            text,
            re.IGNORECASE,
        )
        if match is None:
            return text
        return text[:match.start()] + " " * (len(text) - match.start())

    def _schema_resolve_ordering(
        self,
        text: str,
        table: SchemaTableContext,
        schema: SchemaContext,
    ) -> Optional[Tuple[str, str]]:
        """Resolve one explicit schema-aware ORDER BY target."""
        match = re.search(
            r"\b(?:order(?:ed)?|sort(?:ed)?)\s+by\s+"
            r"([A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)?)"
            r"(.*)$",
            text,
            re.IGNORECASE,
        )
        if match is None:
            return self._extract_ordering(text)
        raw_column, tail = match.groups()
        direction = "ASC"
        direction_match = re.match(
            r"\s+(ascending|descending|asc|desc|升序|降序)\b",
            tail,
            re.IGNORECASE,
        )
        if direction_match:
            direction = "DESC" if direction_match.group(1).casefold() in {"descending", "desc", "降序"} else "ASC"
            tail = tail[direction_match.end():]
        if tail.strip(" \t\r\n,.;，。；"):
            raise SchemaValidationError("multiple schema-aware ordering columns are unsupported")
        parts = raw_column.split(".")
        column_name = parts[-1]
        if len(parts) > 1:
            candidates = schema.table_candidates(".".join(parts[:-1]))
            if len(candidates) != 1 or candidates[0].key != table.key:
                raise SchemaValidationError("ordering column table is not the selected schema table")
        canonical = schema.canonical_column(table, column_name)
        if canonical is None:
            raise SchemaValidationError("ordering column is outside the schema")
        return canonical, direction

    @staticmethod
    def _schema_has_explicit_ordering(text: str) -> bool:
        lowered = text.lower()
        phrases = (
            "order by", "ordered by", "sort by", "sorted by",
            "ascending", "descending", "asc", "desc", "sort", "sorted",
            "top", "highest", "lowest", "max", "min",
            "升序", "降序", "排序", "最大", "最小", "最多", "最少",
        )
        for phrase in phrases:
            if phrase.isascii():
                if re.search(r"(?<![\w$])" + re.escape(phrase) + r"(?![\w$])", lowered):
                    return True
            elif phrase in text:
                return True
        return False

    def _schema_resolve_conditions(
        self,
        text: str,
        conditions: list,
        table: SchemaTableContext,
        schema: SchemaContext,
    ) -> list:
        if not conditions or not table.has_column_metadata:
            return conditions
        resolved: list[str] = []
        for condition in conditions:
            rewritten = condition
            if schema.canonical_column(table, "date") is None:
                created_at = schema.canonical_column(table, "created_at")
                if created_at is not None:
                    segments = re.split(r"('(?:''|[^'])*')", rewritten)
                    for index in range(0, len(segments), 2):
                        segments[index] = re.sub(
                            r"(?<![\w$])date(?![\w$])",
                            created_at,
                            segments[index],
                            flags=re.IGNORECASE,
                        )
                    rewritten = "".join(segments)
            resolved.append(rewritten)
        return resolved

    def _schema_resolve_joins(
        self,
        text: str,
        table_hint: Optional[str],
        schema: SchemaContext,
    ) -> tuple[SchemaTableContext, list[dict]]:
        mentions = self._schema_table_mentions(text, schema)
        if len(mentions) < 2:
            return self._schema_resolve_table(text, table_hint, schema), []

        if table_hint:
            subject_candidates = schema.table_candidates(table_hint)
            if len(subject_candidates) != 1:
                raise SchemaValidationError("table hint is not a unique schema table")
            subject = subject_candidates[0]
        else:
            cn_relation = self._cn_relation_table(text.lower())
            if cn_relation:
                relation_candidates = schema.table_candidates(cn_relation)
                subject_candidates = [
                    table for table in mentions
                    if not relation_candidates or table.key != relation_candidates[0].key
                ]
                if len(subject_candidates) != 1:
                    raise SchemaValidationError("relationship subject is ambiguous")
                subject = subject_candidates[0]
            else:
                subject = mentions[0]

        relational = self._has_relational_keyword(text.lower())
        lowered = text.lower()
        unsupported_outer = (
            re.search(r"\bouter\s+join\b", lowered)
            and not re.search(r"\b(?:left|right)\s+outer\s+join\b", lowered)
        )
        unsupported_qualifier = (
            re.search(
                r"\bnatural\s+(?:(?:left|right|inner|outer)\s+){0,2}join\b",
                lowered,
            )
            or re.search(r"\b(?:left|right|inner)?\s*(?:semi|anti)\s+join\b", lowered)
            or re.search(r"\blateral\s+join\b", lowered)
            or any(phrase in text for phrase in ("自然连接", "半连接", "反连接", "横向连接"))
        )
        if (
            re.search(r"\bfull(?:\s+outer)?\s+join\b", lowered)
            or unsupported_outer
            or re.search(r"\bcross\s+join\b", lowered)
            or unsupported_qualifier
            or any(phrase in text for phrase in ("全连接", "交叉连接"))
        ):
            raise SchemaValidationError("unsupported schema-aware join type")
        join_spec = parse_join_spec(text)
        if not relational and join_spec is None:
            raise SchemaValidationError("multiple tables lack explicit relationship intent")
        if relational:
            if any(
                keyword in text.lower()
                for keyword in ["without", "not have", "no ", "没有任何", "没有"]
            ):
                join_type = "NOT EXISTS"
            else:
                join_type = "EXISTS"
        else:
            if re.search(r"\bleft\s+outer\s+join\b", lowered):
                join_type = "LEFT"
                join_spec = JoinSpec(kind="LEFT", matched_text="left outer join")
            elif re.search(r"\bright\s+outer\s+join\b", lowered):
                join_type = "RIGHT"
                join_spec = JoinSpec(kind="RIGHT", matched_text="right outer join")
            else:
                if join_spec.kind not in {"JOIN", "INNER", "LEFT", "RIGHT"}:
                    raise SchemaValidationError("unsupported schema-aware join type")
                join_type = "INNER" if join_spec.kind == "JOIN" else join_spec.kind

        joins: list[dict] = []
        for related in mentions:
            if related.key == subject.key:
                continue
            candidates = schema.relationship_candidates(subject.name, related.name)
            condition = None
            if len(candidates) == 1:
                relationship = candidates[0]
                condition = (
                    f"{relationship.from_table}.{relationship.from_column} = "
                    f"{relationship.to_table}.{relationship.to_column}"
                )
            joins.append({
                "type": join_type,
                "table": related.name,
                "subject": subject.name,
                "condition": condition,
                "relational": relational,
                "join_spec": join_spec,
            })
        return subject, joins

    def _schema_finalize(
        self, result: NL2SQLResult, schema: SchemaContext
    ) -> NL2SQLResult:
        if not result.success or not result.sql:
            result.schema_used = False
            return result
        try:
            statement = parse_single_sql(result.sql, result.dialect)
            validate_schema_references(
                statement,
                schema,
                reject_ambiguous_unqualified=True,
            )
        except (SchemaValidationError, sqlglot.errors.SqlglotError, ValueError):
            return self._schema_failure(
                result.input_text,
                result.dialect,
                "Generated SQL could not be validated against the provided schema.",
            )
        result.schema_used = True
        return result

    def _generate_with_schema(
        self,
        text: str,
        text_lower: str,
        dialect: str,
        table_hint: Optional[str],
        column_hints: Optional[List[str]],
        analysis: dict,
        schema: SchemaContext,
    ) -> NL2SQLResult:
        """Generate through the enhanced path with strict schema resolution."""
        try:
            unknown_tables = self._schema_unknown_table_patterns(text, schema)
            if unknown_tables:
                return self._schema_failure(
                    text,
                    dialect,
                    "The request references tables outside the provided schema.",
                )
            table_context, joins = self._schema_resolve_joins(text, table_hint, schema)
            columns = self._schema_resolve_columns(
                text_lower, table_context, column_hints, schema
            )
            conditions = self._schema_resolve_conditions(
                text_lower,
                self._extract_conditions_enhanced(text_lower, text),
                table_context,
                schema,
            )
            parsed = self._parse_text(text_lower, text)
            parsed.update(analysis)
            operation = self._detect_operation(text_lower)
            aggregations = self._extract_aggregations(text_lower)
            group_by = self._extract_group_by(text_lower)
            ordering = (
                self._schema_resolve_ordering(text_lower, table_context, schema)
                if self._schema_has_explicit_ordering(text_lower)
                else None
            )
            limit = self._extract_limit(text_lower)
            distinct = self._check_distinct(text_lower)
            sql, explanation, confidence, evidence = self._build_sql_enhanced(
                operation,
                table_context.name,
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
            result = self._apply_confidence_policy(NL2SQLResult(
                success=sql is not None,
                input_text=text,
                sql=sql,
                dialect=dialect,
                explanation=explanation,
                confidence=confidence,
                evidence=evidence,
                suggestions=(
                    self._generate_suggestions(text, sql, dialect)
                    if sql is not None else []
                ),
                parsed_elements=parsed,
            ))
            return self._schema_finalize(result, schema)
        except (SchemaValidationError, ValueError):
            return self._schema_failure(
                text,
                dialect,
                "The request could not be resolved unambiguously against the provided schema.",
            )

    @staticmethod
    def _parameter_metadata(sql: Optional[str], dialect: str) -> tuple[str | None, list[str]]:
        """Return the placeholder style and ordered placeholders in DML SQL."""
        if not sql:
            return None, []
        executable_sql = mask_non_executable(sql, dialect=dialect)
        if not re.match(r"\s*(?:INSERT|UPDATE|DELETE)\b", executable_sql, re.IGNORECASE):
            return None, []
        patterns = {
            "postgres": (r"(?<![\w$])\$\d+(?![\w$])", "numeric"),
            "redshift": (r"(?<![\w$])\$\d+(?![\w$])", "numeric"),
            "oracle": (r"(?<![\w$]):\d+(?![\w$])", "numeric"),
            "tsql": (r"(?<![\w$])@p\d+(?![\w$])", "named"),
            "mysql": (r"(?<![\w$])%s(?![\w$])", "format"),
        }
        pattern, style = patterns.get(dialect, (r"\?", "qmark"))
        placeholders = re.findall(pattern, executable_sql, re.IGNORECASE)
        return (style if placeholders else None), placeholders

    def _apply_confidence_policy(self, result: NL2SQLResult) -> NL2SQLResult:
        """Make the configured confidence threshold affect success status."""
        from ..config import settings

        if result.success and result.confidence < settings.nl2sql_confidence_threshold:
            result.success = False
            result.sql = None
            result.explanation = (
                f"Generated SQL confidence {result.confidence:.2f} is below the "
                f"configured threshold {settings.nl2sql_confidence_threshold:.2f}. "
                + result.explanation
            )
        result.parameter_style, result.parameters = self._parameter_metadata(
            result.sql, result.dialect
        )
        return result

    def _parse_text(self, text_lower: str, original: str) -> dict:
        """Parse and extract all elements from text.

        Delegates to ``nl2sql_pipeline.intent.parse_text``.
        """
        return _parse_text_impl(text_lower, original)

    def _detect_operation(self, text: str) -> str:
        """Detect SQL operation type from text.

        Delegates to ``nl2sql_pipeline.intent.detect_operation``.
        """
        return _detect_operation(text)

    def _extract_table(self, text: str) -> str:
        """Extract table name from text.

        Delegates to ``nl2sql_pipeline.resolution.extract_table``.
        """
        return _pipeline_extract_table(text, self.TABLE_PATTERNS)

    def _extract_table_subject(
        self, text: str, relational_context: str = ""
    ) -> Optional[str]:
        """Extract the subject table (first appearing in text) for D2 relational queries.

        Delegates to ``nl2sql_pipeline.resolution.extract_table_subject``;
        ``relational_context`` excludes the already-resolved relation table
        from the subject slot so '查询有订单的用户' returns 'users', not
        'orders'.
        """
        return _pipeline_extract_table_subject(
            text, self.TABLE_PATTERNS, relational_context
        )

    def _named_tables(self, text: str) -> list:
        """Return the distinct table names the text mentions.

        Delegates to ``nl2sql_pipeline.resolution.named_tables``.
        """
        return _pipeline_named_tables(text, self.TABLE_PATTERNS)

    def _extract_columns(self, text: str) -> list:
        """Extract column names from text.

        Delegates to ``nl2sql_pipeline.resolution.extract_columns``.
        """
        return _pipeline_extract_columns(text, self.COLUMN_PATTERNS)

    def _extract_conditions_enhanced(self, text: str, original: str) -> list:
        """Extract WHERE conditions with enhanced parsing including boolean expressions.

        Delegates to ``nl2sql_pipeline.predicates.extract_conditions``.
        """
        return _extract_conditions_enhanced_impl(text, original, self.COLUMN_PATTERNS)

    def _extract_aggregations(self, text: str) -> list:
        """Extract aggregation functions from text.

        Delegates to ``nl2sql_pipeline.aggregations.extract_aggregations``.
        """
        return _pipeline_extract_aggregations(text, self.COLUMN_PATTERNS)

    def _extract_group_by(self, text: str) -> list:
        """Extract GROUP BY columns from text.

        Delegates to ``nl2sql_pipeline.clause_extract.extract_group_by``.
        """
        return _pipeline_extract_group_by(text, self.COLUMN_PATTERNS, self.TABLE_PATTERNS)

    def _extract_ordering(self, text: str) -> Optional[Tuple[str, str]]:
        """Extract ORDER BY clause from text.

        Delegates to ``nl2sql_pipeline.clause_extract.extract_ordering``.
        """
        return _pipeline_extract_ordering(text, self.COLUMN_PATTERNS)

    def _extract_limit(self, text: str) -> Optional[int]:
        """Extract LIMIT value from text.

        Delegates to ``nl2sql_pipeline.clause_extract.extract_limit``.
        """
        return _pipeline_extract_limit(text)

    def _extract_joins(self, text: str) -> list:
        """Extract JOIN information from text.

        Delegates to ``nl2sql_pipeline.resolution.extract_joins``.
        Detects relational existence patterns (e.g., "users who have orders")
        and returns structured join contexts for EXISTS-based SQL generation.
        """
        return _pipeline_extract_joins(text, self.TABLE_PATTERNS)

    def _cn_relation_table(self, text: str) -> str:
        """Return the CN relational connective's table (orders, products, ...)
        when present in ``text``; otherwise ""."""
        import re as _re
        from ..nl2sql_components.relations import _CN_REL_TABLES
        for modifier, rel_table in _CN_REL_TABLES.items():
            if _re.search(r"(?:有|没有任何|没有)" + _re.escape(modifier), text):
                return rel_table
        return ""

    def _guess_join_key(self, table1: str, table2: str) -> Optional[str]:
        """Guess the join key between two tables.

        Delegates to ``nl2sql_pipeline.resolution.guess_join_key``.
        Returns None for unknown relationships instead of guessing.
        """
        return _pipeline_guess_join_key(table1, table2)

    def _check_distinct(self, text: str) -> bool:
        """Check if DISTINCT is needed.

        Delegates to ``nl2sql_pipeline.clause_extract.check_distinct``.
        """
        return _pipeline_check_distinct(text)

    def _has_relational_keyword(self, text: str) -> bool:
        """Check if text contains relational existence keywords (D2).

        Delegates to ``nl2sql_pipeline.resolution.has_relational_keyword``.
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

        Delegates to ``nl2sql_pipeline.renderer.render_sql``.
        Fail-closed behaviour (unresolved join → success=False) is
        enforced by ``render_sql``.
        """
        ir = _nl2sql_ir.build_ir(
            operation, table, columns, conditions, aggregations,
            group_by, ordering, limit, joins, distinct, dialect,
        )
        return _render_sql_impl(ir)

    def _validate_generated_sql(self, sql: str, dialect: str) -> float:
        """Validate generated SQL syntax and return confidence adjustment.

        Delegates to ``nl2sql_pipeline.validation.validate_sql``.
        """
        return _validate_sql_impl(sql, dialect)

    def _add_limit(self, sql: str, limit: int, dialect: str) -> str:
        """Add LIMIT clause with dialect-specific syntax.

        Delegates to ``nl2sql_pipeline.renderer.add_limit``.
        """
        return _add_limit_impl(sql, limit, dialect)

    def _apply_dialect_adjustments(self, sql: str, dialect: str) -> str:
        """Apply dialect-specific syntax adjustments.

        Delegates to ``nl2sql_pipeline.dialect.apply_dialect_adjustments``
        (moved unchanged — executable-region-aware regex rewriter).
        """
        return _apply_dialect_adjustments_impl(sql, dialect)

    def _generate_suggestions(self, text: str, sql: str, dialect: str) -> list:
        """Generate improvement suggestions.

        Delegates to ``nl2sql_pipeline.suggestions.generate_suggestions``.
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
            operation, table, columns, conditions, aggregations,
            [], ordering, limit, [], False, dialect,
        )
