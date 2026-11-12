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
from dataclasses import dataclass, replace
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
_SCHEMA_WHOSE_PREFIX = re.compile(
    r"\bwhose\s+"
    r"([A-Za-z_][A-Za-z0-9_$]*|"
    r"[A-Za-z_][A-Za-z0-9_$]*\.[A-Za-z_][A-Za-z0-9_$]*|"
    r"[A-Za-z_][A-Za-z0-9_$]*\.[A-Za-z_][A-Za-z0-9_$]*\.[A-Za-z_][A-Za-z0-9_$]*)\s+"
    r"(is\s+not|isn't|is|equals|<>|!=|>=|<=|=|>|<)\s*",
    re.IGNORECASE,
)
_SCHEMA_ZERO_COUNT_PATTERNS = (
    re.compile(r"\b(?:including|include)\s+zero(?:s)?\b", re.IGNORECASE),
    re.compile(r"\bwith\s+zero\s+[A-Za-z_][A-Za-z0-9_$]*\b", re.IGNORECASE),
    re.compile(
        r"\b(?:including|include)\s+(?:users|those)\s+with\s+no\s+[A-Za-z_][A-Za-z0-9_$]*\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:including|include)\s+(?:users|those)\s+with\s+zero\s+[A-Za-z_][A-Za-z0-9_$]*\b",
        re.IGNORECASE,
    ),
    re.compile(r"含\s*[0０零]"),
    re.compile(r"(?:包括|包含)\s*没有[\u4e00-\u9fff]{1,12}的用户"),
    re.compile(r"没有[\u4e00-\u9fff]{1,12}的用户也(?:包括|包含)"),
)
_SCHEMA_WHOSE_REJECTED_VALUES = {
    "and", "or", "not", "is", "null", "true", "false", "unknown",
    "select", "from", "where", "group", "order", "by", "limit",
    "current_date", "current_timestamp", "now",
}
_SCHEMA_WHOSE_CJK_CONNECTORS = {"和", "或", "且", "并", "与", "跟", "及"}


@dataclass(frozen=True)
class _SchemaWhoseParsed:
    """Schema-safe lexical result for one whose predicate."""

    raw_column: str
    operator: str
    literal: str
    span: tuple[int, int]


_SCHEMA_JOINED_ON_PREFIX = re.compile(
    r"\b(?:(inner|left|right)\s+)?joined\s+on\b",
    re.IGNORECASE,
)
_SCHEMA_JOINED_ON_OPERAND = re.compile(
    r"[A-Za-z_][A-Za-z0-9_$]*\.[A-Za-z_][A-Za-z0-9_$]*"
    r"(?:\.[A-Za-z_][A-Za-z0-9_$]*)?"
)
_SCHEMA_JOINED_WITH_PREFIX = re.compile(
    r"\b(?:(inner|left|right)\s+)?joined\s+with\s+"
    r"([A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)?)\b",
    re.IGNORECASE,
)
_SCHEMA_DIAGNOSTIC_VALUES = {
    "active", "inactive", "enabled", "disabled", "valid", "invalid",
    "completed", "pending", "paid", "unpaid", "done", "true", "false",
}
_SCHEMA_DIAGNOSTIC_KEYWORDS = {
    "and", "or", "not", "is", "where", "with", "by", "group", "grouped",
    "order", "ordered", "sort", "sorted", "asc", "desc", "ascending",
    "descending", "users", "user", "show", "list", "find", "display",
}
_SCHEMA_DIAGNOSTIC_COLUMN_ALLOWLIST = {
    "password", "nickname", "token", "hash", "bio", "avatar",
}
_SCHEMA_GROUP_LABEL_COLUMNS = {
    "部门": ("department", "dept"),
    "状态": ("status",),
    "类型": ("type",),
    "分类": ("category",),
    "日期": ("date",),
    "地区": ("region",),
    "区域": ("region",),
    "品牌": ("brand",),
    "级别": ("level",),
    "优先级": ("priority",),
}


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
        self,
        text: str,
        schema: SchemaContext,
        ignored_spans: tuple[tuple[int, int], ...] = (),
    ) -> list[str]:
        """Return mapped table names mentioned by the request but absent in schema."""
        for start, end in ignored_spans:
            text = text[:start] + " " * (end - start) + text[end:]
        unknown: list[str] = []
        for pattern, mapped in self.TABLE_PATTERNS.items():
            if pattern == "order" and re.search(r"\border\b\s+by\b", text, re.IGNORECASE):
                continue
            match = self._schema_text_match(text, pattern)
            if not match:
                continue
            if schema.table_candidates(mapped):
                continue
            if mapped in {"table", "data"}:
                continue
            unknown.append(mapped)
        return sorted(set(unknown))

    def _schema_entity_counter_tables(self, text: str) -> set[str]:
        """Find entity counters without treating data words as counts."""
        return {
            mapped for pattern, mapped in self.TABLE_PATTERNS.items()
            if re.search(re.escape(pattern) + r"数(?!据|字|组)", text, re.IGNORECASE)
        }

    def _schema_aggregation_intent(self, text: str) -> bool:
        return bool(re.search(
            r"\b(?:number\s+of|count(?:\s+of)?|how\s+many|sum|average|avg|maximum|minimum|max|min)\b|"
            r"统计|数量|多少|几个|总数|个数|条数|件数|行数|人数|记录数|"
            r"平均|总和|汇总|最大|最小|最多|最少",
            text,
            re.IGNORECASE,
        )) or bool(self._schema_entity_counter_tables(text))

    def _schema_resolve_english_group_label(
        self, text: str, schema: SchemaContext
    ) -> tuple[SchemaTableContext, str, tuple[int, int]] | None:
        if not self._schema_aggregation_intent(text):
            return None
        match = re.search(
            r"\b(?:per|each)\s+([A-Za-z_][A-Za-z0-9_$]*)\b",
            text,
            re.IGNORECASE,
        )
        if match is None:
            return None
        label = match.group(1)
        tail = text[match.end():].strip(" \t\r\n,.;，。；")
        unique_count_phrase = bool(
            self._schema_unique_count_spans(text, ("count", None))
        )
        if tail and not (
            unique_count_phrase
            and re.match(
                r"^(?:where|whose|order(?:ed)?\s+by|sort(?:ed)?\s+by|limit|top\s+\d+)\b",
                tail,
                re.IGNORECASE,
            )
            or unique_count_phrase and self._schema_is_zero_count_suffix(tail)
        ):
            raise SchemaValidationError("multiple schema group labels are unsupported")
        return self._schema_resolve_group_label(
            text, label, (match.start(), match.end()), schema
        )

    def _schema_resolve_chinese_group_label(
        self, text: str, schema: SchemaContext
    ) -> tuple[SchemaTableContext, str, tuple[int, int]] | None:
        if not self._schema_aggregation_intent(text):
            return None
        match = re.search(
            r"(?:每个|各个|每位)\s*([\u4e00-\u9fff]{1,8}?)"
            r"(?=的|员工|订单|产品|客户|交易|支付|日志|记录|数量|用户|$)",
            text,
        )
        if match is None:
            return None
        if re.search(r"每个|各个|每位", text[match.end():]):
            raise SchemaValidationError("multiple schema group labels are unsupported")
        return self._schema_resolve_group_label(
            text, match.group(1), (match.start(), match.end()), schema
        )

    def _schema_resolve_group_label(
        self,
        text: str,
        label: str,
        span: tuple[int, int],
        schema: SchemaContext,
    ) -> tuple[SchemaTableContext, str, tuple[int, int]]:
        """Resolve one consumed label without treating its table as a JOIN."""
        masked = text[:span[0]] + " " * (span[1] - span[0]) + text[span[1]:]
        mentioned = self._schema_table_mentions(masked, schema)
        if len(mentioned) != 1:
            raise SchemaValidationError("schema group label subject is ambiguous")
        data_table = mentioned[0]
        column_names = (label, *_SCHEMA_GROUP_LABEL_COLUMNS.get(label, ()))
        column_keys = {name.casefold() for name in column_names}
        direct_columns = {
            column for column in data_table.columns
            if column.casefold() in column_keys
        }
        if len(direct_columns) > 1:
            raise SchemaValidationError("schema group label column is ambiguous")
        if direct_columns:
            return data_table, direct_columns.pop(), span

        label_tables = schema.table_candidates(label)
        if not label_tables:
            mapped_labels = [
                mapped for pattern, mapped in self.TABLE_PATTERNS.items()
                if pattern.casefold() == label.casefold()
            ]
            candidates = [
                candidate
                for mapped in mapped_labels
                for candidate in schema.table_candidates(mapped)
            ]
            label_tables = tuple({candidate.key: candidate for candidate in candidates}.values())
        if len(label_tables) != 1:
            raise SchemaValidationError("schema group label is not a unique table")
        label_table = label_tables[0]
        if label_table.key == data_table.key:
            raise SchemaValidationError("schema group label cannot be the subject table")

        # Only an explicitly declared data-table -> label-table relationship
        # proves that the data table carries the grouping foreign key.  The
        # relationship index also exposes synthetic reverse entries for join
        # resolution, which must not be used here: accepting one would make a
        # request such as "users per order" group users by their primary key.
        relationships = tuple(
            relationship
            for relationship in schema.relationships
            if relationship.from_table.casefold() == data_table.key
            and relationship.to_table.casefold() == label_table.key
        )
        if len(relationships) == 1:
            label_singular = (
                label[:-1] if label.casefold().endswith("s") else label
            )
            table_basename = label_table.name.rsplit(".", 1)[-1]
            table_singular = (
                table_basename[:-1]
                if table_basename.casefold().endswith("s")
                else table_basename
            )
            allowed_foreign_keys = {
                f"{label_singular}_id".casefold(),
                f"{table_singular}_id".casefold(),
                f"{table_basename}_id".casefold(),
            }
            if len(relationships[0].column_pairs) != 1:
                raise SchemaValidationError("composite group-label relationship is unsupported")
            from_column = relationships[0].column_pairs[0][0]
            if from_column.casefold() not in allowed_foreign_keys:
                raise SchemaValidationError(
                    "schema group label relationship has an unsupported foreign key"
                )
            return data_table, from_column, span
        if len(relationships) > 1:
            raise SchemaValidationError("schema group label relationship is ambiguous")

        table_basename = label_table.name.rsplit(".", 1)[-1]
        singular = (
            table_basename[:-1]
            if table_basename.casefold().endswith("s")
            else table_basename
        )
        foreign_keys = [
            column for column in data_table.columns
            if column.casefold() == (singular + "_id").casefold()
        ]
        if len(foreign_keys) > 1:
            raise SchemaValidationError("schema group label foreign key is ambiguous")
        if foreign_keys:
            return data_table, foreign_keys[0], span
        raise SchemaValidationError("schema group label relationship is missing")

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
        suppress_quantity_token: bool = False,
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

        projection_source = text
        if suppress_quantity_token:
            projection_source = re.sub(r"数量", " " * len("数量"), projection_source)
        projection_text = mask_non_executable(self._schema_projection_text(projection_source))
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

        columns = self._extract_columns(projection_text)
        if columns == ["*"]:
            for candidate in table.columns:
                if self._schema_text_match(projection_text, candidate):
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
    ) -> list[tuple[str, str]]:
        """Resolve schema-aware ORDER BY targets without changing no-schema extraction."""
        match = re.search(
            r"\b(?:order(?:ed)?|sort(?:ed)?)\s+by\s+",
            text,
            re.IGNORECASE,
        )
        if match is None:
            legacy = self._extract_ordering(text)
            return [legacy] if legacy else []
        tail = text[match.end():]
        boundary = re.search(r"\b(?:where|whose|limit)\b", tail, re.IGNORECASE)
        clause = tail[:boundary.start()] if boundary else tail
        if re.search(r"\bor\b|[()\u4e00-\u9fff]", clause, re.IGNORECASE):
            raise SchemaValidationError("unsupported multi-column ordering syntax")
        items = re.split(r"\s*,\s*|\s+and\s+", clause, flags=re.IGNORECASE)
        if not items or any(not item.strip() for item in items) or len(items) > 5:
            raise SchemaValidationError("invalid or excessive ORDER BY columns")
        resolved: list[tuple[str, str]] = []
        seen: set[str] = set()
        identifier = r"[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*){0,2}"
        item_pattern = re.compile(
            rf"^\s*({identifier})\s*(?:(ascending|descending|asc|desc)\s*)?$",
            re.IGNORECASE,
        )
        for item in items:
            item_match = item_pattern.fullmatch(item)
            if item_match is None:
                raise SchemaValidationError("invalid ORDER BY column")
            raw_column, raw_direction = item_match.groups()
            parts = raw_column.split(".")
            column_name = parts[-1]
            if len(parts) > 1:
                candidates = schema.table_candidates(".".join(parts[:-1]))
                if len(candidates) != 1 or candidates[0].key != table.key:
                    raise SchemaValidationError("ordering column table is not the selected schema table")
            canonical = schema.canonical_column(table, column_name)
            if canonical is None:
                raise SchemaValidationError("ordering column is outside the schema")
            key = canonical.casefold()
            if key in seen:
                raise SchemaValidationError("duplicate ORDER BY column")
            seen.add(key)
            direction = "DESC" if raw_direction and raw_direction.casefold() in {"descending", "desc"} else "ASC"
            resolved.append((canonical, direction))
        return resolved

    def _schema_resolve_path_ordering(
        self,
        text: str,
        table: SchemaTableContext,
        schema: SchemaContext,
        plan: _nl2sql_ir.PathDistinctCountPlan,
        *,
        parsed_whose: _SchemaWhoseParsed | None = None,
        group_span: tuple[int, int] | None = None,
    ) -> tuple[_nl2sql_ir.PathOrderingTerm, ...]:
        """Resolve explicit aggregate/group ordering for a path count."""
        executable = mask_non_executable(text)
        if parsed_whose is not None:
            executable = self._schema_mask_span(executable, parsed_whose.span)
        if group_span is not None:
            executable = self._schema_mask_span(executable, group_span)
        explicit = re.search(
            r"\b(?:order(?:ed)?|sort(?:ed)?)\s+by\s+",
            executable,
            re.IGNORECASE,
        )
        has_top = re.search(r"\btop\s+\d+\b", executable, re.IGNORECASE) is not None
        if explicit is None:
            if has_top or self._schema_has_explicit_ordering(executable):
                raise SchemaValidationError(
                    "path count requires explicit ORDER BY syntax"
                )
            return ()

        tail = executable[explicit.end():]
        boundary = re.search(
            r"\b(?:where|whose|limit|top\s+\d+)\b",
            tail,
            re.IGNORECASE,
        )
        clause = tail[:boundary.start()] if boundary else tail
        if re.search(r"\bor\b|[()\u4e00-\u9fff]", clause, re.IGNORECASE):
            raise SchemaValidationError("unsupported path ordering syntax")
        items = re.split(r"\s*,\s*|\s+and\s+", clause)
        if not items or any(not item.strip() for item in items) or len(items) > 5:
            raise SchemaValidationError("invalid or excessive path ordering")
        identifier = r"[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*){0,2}"
        item_pattern = re.compile(
            rf"^\s*({identifier})\s*(?:(ascending|descending|asc|desc)\s*)?$",
            re.IGNORECASE,
        )
        group_identity = {
            column.casefold(): column for column in plan.group_identity
        }
        terms: list[_nl2sql_ir.PathOrderingTerm] = []
        seen: set[tuple[str, str]] = set()
        for item in items:
            match = item_pattern.fullmatch(item)
            if match is None:
                raise SchemaValidationError("invalid path ordering term")
            raw_column, raw_direction = match.groups()
            direction = (
                "DESC"
                if raw_direction and raw_direction.casefold() in {"descending", "desc"}
                else "ASC"
            )
            if raw_column.casefold() == "count":
                key = ("count", "")
                if key in seen:
                    raise SchemaValidationError("duplicate path count ordering")
                seen.add(key)
                terms.append(_nl2sql_ir.PathOrderingTerm("count", None, direction))
                continue

            parts = raw_column.split(".")
            column_name = parts[-1]
            if len(parts) > 1:
                owners = schema.table_candidates(".".join(parts[:-1]))
                if len(owners) != 1 or owners[0].key != table.key:
                    raise SchemaValidationError(
                        "path ordering table is not the subject table"
                    )
            canonical = schema.canonical_column(table, column_name)
            if canonical is None or canonical.casefold() not in group_identity:
                raise SchemaValidationError(
                    "path ordering must use subject group identity"
                )
            key = ("group", canonical.casefold())
            if key in seen:
                raise SchemaValidationError("duplicate path group ordering")
            seen.add(key)
            terms.append(
                _nl2sql_ir.PathOrderingTerm("group", group_identity[canonical.casefold()], direction)
            )

        if has_top and not any(term.kind == "count" for term in terms):
            raise SchemaValidationError(
                "path TOP requires explicit count ordering"
            )
        return tuple(terms)

    def _schema_resolve_aggregate_ordering(
        self, text: str, table: SchemaTableContext, schema: SchemaContext,
        group_by: list[str], *, whose_span=None, group_span=None,
    ) -> tuple[_nl2sql_ir.AggregateOrderingTerm, ...]:
        executable = mask_non_executable(text)
        if whose_span is not None:
            executable = self._schema_mask_span(executable, whose_span)
        if group_span is not None:
            executable = self._schema_mask_span(executable, group_span)
        explicit = re.search(r"\b(?:order(?:ed)?|sort(?:ed)?)\s+by\s+", executable, re.IGNORECASE)
        has_top = re.search(r"\btop\s+\d+\b", executable, re.IGNORECASE) is not None
        if explicit is None:
            if has_top or self._schema_has_explicit_ordering(executable):
                raise SchemaValidationError("unique count requires explicit ORDER BY syntax")
            return ()
        tail = executable[explicit.end():]
        boundary = re.search(r"\b(?:where|whose|limit|top\s+\d+)\b", tail, re.IGNORECASE)
        clause = tail[:boundary.start()] if boundary else tail
        if re.search(r"\bor\b|[()\u4e00-\u9fff]", clause, re.IGNORECASE):
            raise SchemaValidationError("unsupported aggregate ordering syntax")
        items = re.split(r"\s*,\s*|\s+and\s+", clause)
        if not items or any(not item.strip() for item in items) or len(items) > 5:
            raise SchemaValidationError("invalid or excessive aggregate ordering")
        pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*){0,2})\s*(?:(ascending|descending|asc|desc)\s*)?$", re.IGNORECASE)
        group_keys = {c.casefold(): c for c in group_by}
        terms = []
        seen = set()
        for item in items:
            match = pattern.fullmatch(item)
            if match is None:
                raise SchemaValidationError("invalid aggregate ordering term")
            raw, raw_direction = match.groups()
            direction = "DESC" if raw_direction and raw_direction.casefold() in {"desc", "descending"} else "ASC"
            if raw.casefold() == "count":
                key = ("count", "")
                if key in seen: raise SchemaValidationError("duplicate aggregate ordering")
                seen.add(key); terms.append(_nl2sql_ir.AggregateOrderingTerm("count", None, direction)); continue
            parts = raw.split(".")
            if len(parts) > 1:
                owners = schema.table_candidates(".".join(parts[:-1]))
                if len(owners) != 1 or owners[0].key != table.key:
                    raise SchemaValidationError("aggregate ordering table is not selected table")
            canonical = schema.canonical_column(table, parts[-1])
            if canonical is None or canonical.casefold() not in group_keys:
                raise SchemaValidationError("aggregate ordering must use group column")
            key = ("group", canonical.casefold())
            if key in seen: raise SchemaValidationError("duplicate aggregate ordering")
            seen.add(key); terms.append(_nl2sql_ir.AggregateOrderingTerm("group", group_keys[canonical.casefold()], direction))
        if has_top and not any(t.kind == "count" for t in terms):
            raise SchemaValidationError("TOP requires explicit count ordering")
        return tuple(terms)

    def _schema_resolve_count_metric(
        self,
        text: str,
        table: SchemaTableContext,
        schema: SchemaContext,
    ) -> tuple[str, str | None] | None:
        count_intent = bool(re.search(
            r"统计|数量|多少|几个|总数|个数|条数|件数|行数|人数|记录数|"
            r"\bnumber\s+of\b|\bcount(?:\s+of)?\b|\bhow\s+many\b",
            text,
            re.IGNORECASE,
        ))
        if not count_intent:
            for mapped in self._schema_entity_counter_tables(text):
                candidates = schema.table_candidates(mapped)
                if len(candidates) == 1 and candidates[0].key == table.key:
                    count_intent = True
                    break
        measure_table: str | None = None
        if "库存数量" in text:
            measure_table = "inventory"
        elif "购买数量" in text:
            measure_table = "orders"
        if measure_table is not None:
            if table.name.rsplit(".", 1)[-1].casefold() != measure_table:
                raise SchemaValidationError("quantity measure table is not selected")
            quantity = schema.canonical_column(table, "quantity")
            if quantity is None:
                raise SchemaValidationError("quantity measure is outside the schema")
            return "sum", quantity
        if count_intent:
            return "count", None
        return None

    @staticmethod
    def _schema_unique_count_spans(
        text: str, count_metric: tuple[str, str | None] | None
    ) -> list[tuple[int, int]]:
        """Return explicit unique-count modifiers consumed by schema COUNT."""
        if count_metric is None or count_metric[0] != "count":
            return []
        executable = mask_non_executable(text)
        english = re.compile(
            r"\b(?:count(?:\s+of)?|number\s+of)\s+(?:distinct|unique)\b|"
            r"\b(?:distinct|unique)\s+(?:count(?:\s+of)?|number\s+of)\b",
            re.IGNORECASE,
        )
        spans = [match.span() for match in english.finditer(executable)]
        chinese = re.compile(
            r"(?:不同|去重|唯一)\s*(?:的\s*)?"
            r"[\u4e00-\u9fffA-Za-z0-9_$]{0,12}?"
            r"(?:数量|计数|数)",
        )
        spans.extend(match.span() for match in chinese.finditer(executable))
        return spans

    @staticmethod
    def _schema_has_zero_count_intent(text: str) -> bool:
        """Detect explicit inclusion of subjects with no matching targets."""
        executable = mask_non_executable(text)
        return any(pattern.search(executable) for pattern in _SCHEMA_ZERO_COUNT_PATTERNS)

    @staticmethod
    def _schema_is_zero_count_clause_suffix(text: str) -> bool:
        """Accept only supported outer ordering and limit clauses after a zero marker."""
        suffix = text.strip(" \t\r\n,.;，。；、")
        if not suffix:
            return True
        limit_match = re.search(r"(?:^|\s+)limit\s+\d+\s*$", suffix, re.IGNORECASE)
        if limit_match is not None:
            suffix = suffix[:limit_match.start()].strip(" \t\r\n,.;，。；、")
            if not suffix:
                return True
        ordering = re.fullmatch(
            r"(?:order(?:ed)?|sort(?:ed)?)\s+by\s+(.+)",
            suffix,
            re.IGNORECASE,
        )
        if ordering is None:
            return False
        clause = ordering.group(1)
        if re.search(r"\bor\b|[()\u4e00-\u9fff]", clause, re.IGNORECASE):
            return False
        terms = re.split(r"\s*,\s*|\s+and\s+", clause, flags=re.IGNORECASE)
        identifier = r"[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*){0,2}"
        item = re.compile(
            rf"^\s*{identifier}\s*(?:(?:ascending|descending|asc|desc)\s*)?$",
            re.IGNORECASE,
        )
        return bool(terms) and all(item.fullmatch(term) is not None for term in terms)

    @staticmethod
    def _schema_is_zero_count_suffix(text: str) -> bool:
        """Check whether a trailing phrase is solely an explicit zero marker."""
        executable = mask_non_executable(text).strip(" \t\r\n,.;，。；、")
        matches = []
        for pattern in _SCHEMA_ZERO_COUNT_PATTERNS:
            match = pattern.match(executable)
            if match is not None:
                matches.append(match)
        if len(matches) != 1:
            return False
        suffix = executable[matches[0].end():].strip(" \t\r\n,.;，。；、")
        return PipelineNL2SQLGenerator._schema_is_zero_count_clause_suffix(suffix)

    @staticmethod
    def _schema_mask_clause_tail(text: str) -> str:
        """Mask clauses following a group label while preserving offsets."""
        match = re.search(
            r"\b(?:where|whose|order(?:ed)?\s+by|sort(?:ed)?\s+by|limit)\b",
            text,
            re.IGNORECASE,
        )
        if match is None:
            return text
        return text[:match.start()] + " " * (len(text) - match.start())

    def _schema_extract_aggregations(
        self,
        text: str,
        table: SchemaTableContext | None = None,
        schema: SchemaContext | None = None,
        count_metric: tuple[str, str | None] | None = None,
    ) -> list[str]:
        existing = self._extract_aggregations(text)
        if count_metric is not None and count_metric[0] == "sum":
            return [f"SUM({count_metric[1]})"]
        if count_metric is not None and count_metric[0] == "count" and not any(
            aggregation.upper().startswith("COUNT(") for aggregation in existing
        ):
            existing = [*existing, "COUNT(*) AS count"]
        if table is None or schema is None or not table.has_column_metadata:
            return existing

        group_match = re.search(r"\b(?:group(?:ed)?\s+by|per|each|by)\b", text, re.IGNORECASE)
        metric_text = text if group_match is None else text[:group_match.start()]
        metric_candidates: list[tuple[int, str]] = []
        for column in table.columns:
            pattern = rf"(?<![\w$]){re.escape(column)}(?![\w$])"
            match = re.search(pattern, metric_text, re.IGNORECASE)
            if match:
                metric_candidates.append((match.start(), column))
        if metric_candidates:
            metric = min(metric_candidates, key=lambda item: item[0])[1]
            existing = [
                re.sub(r"^(AVG|SUM|MAX|MIN)\([^)]*\)$", lambda m: f"{m.group(1)}({metric})", aggregation, flags=re.IGNORECASE)
                if re.match(r"^(AVG|SUM|MAX|MIN)\(", aggregation, re.IGNORECASE)
                else aggregation
                for aggregation in existing
            ]
        return existing

    def _schema_resolve_group_by(
        self,
        text: str,
        table: SchemaTableContext,
        schema: SchemaContext,
        aggregations: list[str],
    ) -> list[str]:
        lowered = text.lower()
        match = re.search(
            r"\b(?:group\s+by|grouped\s+by)\s+"
            r"([A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)?)(.*)$",
            lowered,
            re.IGNORECASE,
        )
        match_kind = "group"
        if match is None and aggregations:
            if not re.search(r"\b(?:ordered|sorted|order|sort)\s+by\b", lowered):
                match = re.search(
                    r"\b(?:per|each|by)\s+"
                    r"([A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)?)(.*)$",
                    lowered,
                    re.IGNORECASE,
                )
                match_kind = "aggregation-group"
        chinese_group_intent = bool(re.search(r"每个|各个|每位|分组|汇总|按[^\s,，。；]+(?:分组|汇总|统计)", text))
        if match is None:
            if chinese_group_intent:
                raise SchemaValidationError("schema group column is not explicitly resolvable")
            return []
        raw_column, tail = match.groups()
        if tail.strip(" \t\r\n,.;，。；"):
            raise SchemaValidationError("multiple schema group columns are unsupported")
        parts = raw_column.split(".")
        if len(parts) > 1:
            candidates = schema.table_candidates(".".join(parts[:-1]))
            if len(candidates) != 1 or candidates[0].key != table.key:
                raise SchemaValidationError("group column table is not the selected schema table")
        canonical = schema.canonical_column(table, parts[-1])
        if canonical is None:
            if not table.has_column_metadata and match_kind == "group":
                return [parts[-1]]
            raise SchemaValidationError("group column is outside the schema")
        return [canonical]

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

    @staticmethod
    def _schema_mask_span(
        text: str, span: tuple[int, int]
    ) -> str:
        start, end = span
        return text[:start] + " " * (end - start) + text[end:]

    def _schema_parse_whose(self, text: str) -> _SchemaWhoseParsed | None:
        """Parse one schema-safe whose predicate without resolving its owner."""
        executable = mask_non_executable(text)
        match = _SCHEMA_WHOSE_PREFIX.search(executable)
        if match is None:
            return None
        whose_matches = list(_SCHEMA_WHOSE_PREFIX.finditer(executable))
        if len(whose_matches) != 1:
            raise SchemaValidationError("multiple whose predicates are unsupported")
        original_match = _SCHEMA_WHOSE_PREFIX.match(text, match.start())
        if original_match is None:
            raise SchemaValidationError("whose predicate is not executable")
        match = original_match

        raw_column, raw_operator = match.groups()
        position = match.end()
        if position >= len(text):
            raise SchemaValidationError("whose predicate value is missing")
        quote = text[position] if text[position] in "'\"" else None
        value_end = position
        if quote is not None:
            position += 1
            value_chars: list[str] = []
            closed = False
            while position < len(text):
                character = text[position]
                if character == "\\" and position + 1 < len(text):
                    value_chars.extend((character, text[position + 1]))
                    position += 2
                    continue
                if character == quote:
                    if position + 1 < len(text) and text[position + 1] == quote:
                        value_chars.append(quote)
                        position += 2
                        continue
                    closed = True
                    position += 1
                    break
                value_chars.append(character)
                position += 1
            if not closed:
                raise SchemaValidationError("whose quoted value is not closed")
            value = "".join(value_chars)
            literal = "'" + value.replace("'", "''") + "'"
            value_end = position
        else:
            numeric = re.match(
                r"-?(?:\d+(?:\.\d*)?|\.\d+)(?![\w$])",
                text[position:],
            )
            if numeric is not None:
                literal = numeric.group(0)
                value_end = position + numeric.end()
            else:
                null_match = re.match(r"null(?![\w$])", text[position:], re.IGNORECASE)
                if null_match is not None:
                    literal = "NULL"
                    value_end = position + null_match.end()
                else:
                    cjk_token = re.match(r"[\u4e00-\u9fff]+", text[position:])
                    if cjk_token is not None:
                        value = cjk_token.group(0)
                        if any(connector in value for connector in _SCHEMA_WHOSE_CJK_CONNECTORS):
                            raise SchemaValidationError("whose CJK value contains a connector")
                        literal = "'" + value.replace("'", "''") + "'"
                        value_end = position + cjk_token.end()
                    else:
                        token = re.match(r"[A-Za-z_][A-Za-z0-9_$]*(?![\w$])", text[position:])
                        if token is None:
                            raise SchemaValidationError("whose value is not a supported literal")
                        value = token.group(0)
                        if value.casefold() in _SCHEMA_WHOSE_REJECTED_VALUES:
                            raise SchemaValidationError("whose value is a reserved word")
                        after_token = text[position + token.end():].lstrip()
                        if after_token.startswith("("):
                            raise SchemaValidationError("whose function values are unsupported")
                        literal = "'" + value.replace("'", "''") + "'"
                        value_end = position + token.end()

        operator = raw_operator.casefold()
        if literal == "NULL":
            if operator == "is":
                normalized_operator = "IS"
            elif operator in {"is not", "isn't"}:
                normalized_operator = "IS NOT"
            else:
                raise SchemaValidationError("comparison with NULL is unsupported")
        else:
            normalized_operator = {
                "is": "=", "equals": "=", "is not": "!=", "isn't": "!=",
                "<>": "!=",
            }.get(operator, raw_operator)

        tail = executable[value_end:]
        if re.search(r"\bor\b|\bwhose\b|[()]", tail, re.IGNORECASE):
            raise SchemaValidationError("complex whose predicates are unsupported")
        stripped_tail = tail.strip()
        if stripped_tail and not re.match(
            r"^(?:and|order(?:ed)?\s+by|sort(?:ed)?\s+by|limit)\b",
            stripped_tail,
            re.IGNORECASE,
        ) and not self._schema_is_zero_count_suffix(stripped_tail):
            raise SchemaValidationError("unexpected text after whose predicate")
        span = (match.start(), value_end)
        return _SchemaWhoseParsed(raw_column, normalized_operator, literal, span)

    def _schema_resolve_whose(
        self,
        text: str,
        table: SchemaTableContext,
        schema: SchemaContext,
    ) -> tuple[str, tuple[int, int]] | None:
        """Resolve one schema-aware ``whose`` predicate for a selected table."""
        parsed = self._schema_parse_whose(text)
        if parsed is None:
            return None
        parts = parsed.raw_column.split(".")
        column_name = parts[-1]
        if len(parts) > 1:
            candidates = schema.table_candidates(".".join(parts[:-1]))
            if len(candidates) != 1 or candidates[0].key != table.key:
                raise SchemaValidationError("whose column table is not the selected table")
        canonical = schema.canonical_column(table, column_name)
        if canonical is None:
            if table.has_column_metadata:
                raise SchemaValidationError("whose column is outside the schema")
            canonical = column_name
        return f"{canonical} {parsed.operator} {parsed.literal}", parsed.span

    def _schema_resolve_joined_on(
        self,
        text: str,
        table_hint: Optional[str],
        schema: SchemaContext,
    ) -> tuple[SchemaTableContext, list[dict], tuple[int, int]] | None:
        """Resolve one schema-aware qualified equality after ``joined on``."""
        executable = mask_non_executable(text)
        prefixes = list(_SCHEMA_JOINED_ON_PREFIX.finditer(executable))
        if not prefixes:
            return None
        if re.search(r"\bjoined\s+with\b", executable, re.IGNORECASE):
            raise SchemaValidationError("mixed joined-on and joined-with clauses are unsupported")
        if len(prefixes) != 1:
            raise SchemaValidationError("multiple joined-on clauses are unsupported")
        if re.search(r"\b(?:per|each)\b|每个|各个|每位", executable, re.IGNORECASE):
            raise SchemaValidationError("joined-on with group labels is unsupported")
        prefix = prefixes[0]
        original_prefix = _SCHEMA_JOINED_ON_PREFIX.match(text, prefix.start())
        if original_prefix is None:
            raise SchemaValidationError("joined-on clause is not executable")
        prefix = original_prefix
        kind = (prefix.group(1) or "inner").upper()
        before_mentions = self._schema_table_mentions(text[:prefix.start()], schema)
        if table_hint:
            subject_candidates = schema.table_candidates(table_hint)
            if len(subject_candidates) != 1:
                raise SchemaValidationError("joined-on subject hint is ambiguous")
            subject = subject_candidates[0]
        elif before_mentions:
            subject = before_mentions[0]
        else:
            raise SchemaValidationError("joined-on subject is missing")

        remainder = executable[prefix.end():]
        left_match = _SCHEMA_JOINED_ON_OPERAND.match(remainder.lstrip())
        if left_match is None:
            raise SchemaValidationError("joined-on left endpoint is invalid")
        left_start = prefix.end() + (len(remainder) - len(remainder.lstrip()))
        left_raw = left_match.group(0)
        after_left = remainder.lstrip()[left_match.end():]
        equals = re.match(r"\s*=\s*", after_left)
        if equals is None:
            raise SchemaValidationError("joined-on requires one equality")
        right_offset = left_start + left_match.end() + equals.end()
        right_match = _SCHEMA_JOINED_ON_OPERAND.match(executable[right_offset:])
        if right_match is None:
            raise SchemaValidationError("joined-on right endpoint is invalid")
        right_raw = right_match.group(0)
        value_end = right_offset + right_match.end()

        tail = executable[value_end:]
        stripped_tail = tail.strip()
        if stripped_tail and not re.match(
            r"^(?:where|whose|order(?:ed)?\s+by|sort(?:ed)?\s+by)\b",
            stripped_tail,
            re.IGNORECASE,
        ):
            raise SchemaValidationError("unexpected text after joined-on equality")

        def resolve_endpoint(raw: str) -> tuple[SchemaTableContext, str]:
            parts = raw.split(".")
            table_name = ".".join(parts[:-1])
            candidates = schema.table_candidates(table_name)
            if len(candidates) != 1:
                raise SchemaValidationError("joined-on table is not unique")
            table = candidates[0]
            column = schema.canonical_column(table, parts[-1])
            if column is None:
                raise SchemaValidationError("joined-on column is outside the schema")
            return table, column

        left_table, left_column = resolve_endpoint(left_raw)
        right_table, right_column = resolve_endpoint(right_raw)
        if left_table.key == right_table.key:
            raise SchemaValidationError("self joined-on is unsupported")
        endpoint_tables = {left_table.key, right_table.key}
        if subject.key not in endpoint_tables:
            raise SchemaValidationError("joined-on subject is not an endpoint")
        target_keys = endpoint_tables - {subject.key}
        if len(target_keys) != 1:
            raise SchemaValidationError("joined-on target is ambiguous")
        target = right_table if right_table.key in target_keys else left_table
        mentions = self._schema_table_mentions(text, schema)
        if {table.key for table in mentions} - endpoint_tables:
            raise SchemaValidationError("joined-on contains an extra table")

        raw_relationships = [
            relationship for relationship in schema.relationships
            if {
                relationship.from_table.casefold(), relationship.to_table.casefold()
            } == endpoint_tables
        ]
        if raw_relationships:
            def matches_relationship(relationship) -> bool:
                if len(relationship.column_pairs) != 1:
                    return False
                from_column, to_column = relationship.column_pairs[0]
                declared = {
                    (relationship.from_table.casefold(), from_column.casefold()),
                    (relationship.to_table.casefold(), to_column.casefold()),
                }
                supplied = {
                    (left_table.key, left_column.casefold()),
                    (right_table.key, right_column.casefold()),
                }
                return declared == supplied

            if sum(matches_relationship(item) for item in raw_relationships) != 1:
                raise SchemaValidationError("joined-on does not match a unique relationship")

        condition = (
            f"{left_table.name}.{left_column} = "
            f"{right_table.name}.{right_column}"
        )
        span = (prefix.start(), value_end)
        return subject, [{
            "type": kind,
            "table": target.name,
            "subject": subject.name,
            "condition": condition,
            "relational": False,
            "join_spec": JoinSpec(kind=kind, matched_text="joined on"),
        }], span

    def _schema_resolve_joined_with(
        self,
        text: str,
        table_hint: Optional[str],
        schema: SchemaContext,
    ) -> tuple[SchemaTableContext, list[dict], tuple[int, int]] | None:
        """Resolve one relationship-backed physical ``joined with`` clause."""
        executable = mask_non_executable(text)
        matches = list(_SCHEMA_JOINED_WITH_PREFIX.finditer(executable))
        if not matches:
            return None
        if len(matches) != 1 or re.search(r"\bjoined\s+on\b", executable, re.IGNORECASE):
            raise SchemaValidationError("multiple or mixed joined clauses are unsupported")
        match = matches[0]
        original_match = _SCHEMA_JOINED_WITH_PREFIX.match(text, match.start())
        if original_match is None:
            raise SchemaValidationError("joined-with clause is not executable")
        match = original_match
        if re.search(
            r"\b(?:per|each|group\s+by|grouped\s+by)\b|每个|各个|每位",
            executable,
            re.IGNORECASE,
        ):
            raise SchemaValidationError("joined-with grouping is unsupported")

        kind = (match.group(1) or "inner").upper()
        target_name = match.group(2)
        target_candidates = schema.table_candidates(target_name)
        if len(target_candidates) != 1:
            raise SchemaValidationError("joined-with target is not unique")
        target = target_candidates[0]
        before_mentions = self._schema_table_mentions(text[:match.start()], schema)
        if table_hint:
            subject_candidates = schema.table_candidates(table_hint)
            if len(subject_candidates) != 1:
                raise SchemaValidationError("joined-with subject hint is ambiguous")
            subject = subject_candidates[0]
        elif before_mentions:
            subject = before_mentions[0]
        else:
            raise SchemaValidationError("joined-with subject is missing")
        if self._schema_text_match(text[:match.start()], target_name):
            raise SchemaValidationError("joined-with target is repeated before the clause")
        before_keys = {table.key for table in before_mentions}
        if before_keys - {subject.key, target.key}:
            raise SchemaValidationError("joined-with contains an extra table")
        if subject.key == target.key:
            raise SchemaValidationError("self joined-with is unsupported")

        tail = executable[match.end():]
        stripped_tail = tail.strip()
        if stripped_tail and not re.match(
            r"^(?:where|whose|order(?:ed)?\s+by|sort(?:ed)?\s+by)\b",
            stripped_tail,
            re.IGNORECASE,
        ):
            raise SchemaValidationError("unexpected text after joined-with target")
        relationships = [
            relationship for relationship in schema.relationships
            if {
                relationship.from_table.casefold(), relationship.to_table.casefold()
            } == {subject.key, target.key}
        ]
        if len(relationships) != 1:
            raise SchemaValidationError("joined-with relationship is not unique")
        relationship = relationships[0]
        condition = " AND ".join(
            f"{relationship.from_table}.{from_column} = {relationship.to_table}.{to_column}"
            for from_column, to_column in relationship.column_pairs
        )
        span = (match.start(), match.end())
        return subject, [{
            "type": kind,
            "table": target.name,
            "subject": subject.name,
            "condition": condition,
            "relational": False,
            "join_spec": JoinSpec(kind=kind, matched_text="joined with"),
        }], span

    def _schema_diagnostic_suggestions(
        self,
        text: str,
        table: SchemaTableContext,
        schema: SchemaContext,
        columns: list[str],
        existing: list,
    ) -> list:
        """Return high-confidence unmapped-column suggestions for schema success."""
        if not table.has_column_metadata:
            return list(existing)
        masked = mask_non_executable(text)
        schema_tables = {candidate.key for candidate in schema.tables}
        table_aliases = {
            pattern.casefold() for pattern in self.TABLE_PATTERNS
        } | {
            mapped.casefold() for mapped in self.TABLE_PATTERNS.values()
        }
        schema_columns = {column.casefold() for column in table.columns}
        mapped_aliases = {
            alias.casefold(): canonical
            for alias, canonical in self.COLUMN_PATTERNS.items()
        }
        warnings: list[tuple[int, str]] = []
        seen: set[str] = set()

        def add_warning(position: int, token: str, *, projection: bool = False) -> None:
            key = token.casefold()
            if key in seen or key in schema_columns:
                return
            canonical = mapped_aliases.get(key)
            if canonical is not None and canonical.casefold() in schema_columns:
                return
            message = (
                f'Possible projection term "{token}" was not resolved against the selected schema table.'
                if projection else
                f'Possible unmapped column reference: "{token}". '
                "Provide it in column_hints if it is a schema column."
            )
            seen.add(key)
            warnings.append((position, message))

        # Strong identifier contexts: `with token` and `by snake_case`.
        for match in re.finditer(
            r"\b(?:with|by)\s+([A-Za-z_][A-Za-z0-9_$]*)",
            masked,
            re.IGNORECASE,
        ):
            token = match.group(1)
            lowered = token.casefold()
            if lowered in _SCHEMA_DIAGNOSTIC_KEYWORDS | _SCHEMA_DIAGNOSTIC_VALUES:
                continue
            if schema.table_candidates(token) or lowered in schema_tables:
                continue
            if lowered in table_aliases:
                continue
            if schema.canonical_column(table, token) is not None:
                continue
            if lowered in mapped_aliases and mapped_aliases[lowered].casefold() in schema_columns:
                continue
            if match.group(0).casefold().startswith("by ") and "_" not in token:
                continue
            add_warning(match.start(1), token)

        # Explicit projection conjunctions: only mapped aliases after a
        # show/list/display marker, before any predicate/clause boundary.
        projection_marker = re.search(r"\b(?:show|list|display|select)\b", masked, re.IGNORECASE)
        if projection_marker:
            boundary = re.search(
                r"\b(?:where|whose|order(?:ed)?\s+by|sort(?:ed)?\s+by|group(?:ed)?\s+by)\b",
                masked[projection_marker.end():],
                re.IGNORECASE,
            )
            projection_end = (
                projection_marker.end() + boundary.start()
                if boundary is not None else len(masked)
            )
            for alias, canonical in sorted(self.COLUMN_PATTERNS.items(), key=lambda item: -len(item[0])):
                if canonical.casefold() in schema_columns:
                    continue
                aliases = [alias]
                if alias.isascii() and not alias.casefold().endswith("s"):
                    aliases.append(alias + "s")
                for candidate_alias in aliases:
                    expression = re.escape(candidate_alias)
                    if not re.search(r"[\u4e00-\u9fff]", candidate_alias):
                        expression = rf"(?<![\w$]){expression}(?![\w$])"
                    for match in re.finditer(expression, masked[projection_marker.end():projection_end], re.IGNORECASE):
                        add_warning(
                            projection_marker.end() + match.start(),
                            alias,
                            projection=True,
                        )
            projection_slice = masked[projection_marker.end():projection_end]
            for token_match in re.finditer(
                r"[A-Za-z_][A-Za-z0-9_$]*", projection_slice
            ):
                token = token_match.group(0)
                lowered = token.casefold()
                if (
                    lowered in _SCHEMA_DIAGNOSTIC_KEYWORDS
                    or lowered in _SCHEMA_DIAGNOSTIC_VALUES
                    or lowered in table_aliases
                    or lowered in schema_tables
                    or lowered in schema_columns
                ):
                    continue
                canonical = mapped_aliases.get(lowered)
                if canonical is not None and canonical.casefold() in schema_columns:
                    continue
                if canonical is None and (
                    "_" not in token and lowered not in _SCHEMA_DIAGNOSTIC_COLUMN_ALLOWLIST
                ):
                    continue
                add_warning(
                    projection_marker.end() + token_match.start(),
                    canonical or token,
                    projection=True,
                )

        warnings.sort(key=lambda item: item[0])
        diagnostic_messages = [message for _, message in warnings[:3]]
        combined: list = []
        for suggestion in [*existing, *diagnostic_messages]:
            if suggestion not in combined:
                combined.append(suggestion)
        return combined[:3]

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

        def raw_edges_between(left: str, right: str) -> list:
            return [
                relationship for relationship in schema.relationships
                if {relationship.from_table.casefold(), relationship.to_table.casefold()}
                == {left.casefold(), right.casefold()}
            ]

        def condition_for(relationship, left: str, right: str) -> str:
            if relationship.from_table.casefold() == left.casefold():
                pairs = relationship.column_pairs
                return " AND ".join(
                    f"{relationship.from_table}.{from_column} = {relationship.to_table}.{to_column}"
                    for from_column, to_column in pairs
                )
            return " AND ".join(
                f"{relationship.to_table}.{to_column} = {relationship.from_table}.{from_column}"
                for from_column, to_column in relationship.column_pairs
            )

        def shortest_path(target: SchemaTableContext) -> list[tuple[SchemaTableContext, str]] | None:
            queue: list[tuple[SchemaTableContext, list[tuple[SchemaTableContext, str]]]] = [(subject, [])]
            candidates: list[list[tuple[SchemaTableContext, str]]] = []
            while queue:
                current, path = queue.pop(0)
                if len(path) >= 2:
                    continue
                for edge in schema.relationships:
                    endpoints = {edge.from_table.casefold(), edge.to_table.casefold()}
                    if current.key not in endpoints:
                        continue
                    next_name = edge.to_table if edge.from_table.casefold() == current.key else edge.from_table
                    next_candidates = schema.table_candidates(next_name)
                    if len(next_candidates) != 1:
                        continue
                    next_table = next_candidates[0]
                    if next_table.key in {table.key for table, _ in path} or next_table.key == subject.key:
                        continue
                    next_path = [*path, (next_table, condition_for(edge, current.name, next_table.name))]
                    if next_table.key == target.key:
                        candidates.append(next_path)
                    else:
                        queue.append((next_table, next_path))
            if not candidates:
                return None
            shortest = min(len(path) for path in candidates)
            shortest_paths = [path for path in candidates if len(path) == shortest]
            if len(shortest_paths) != 1:
                raise SchemaValidationError("schema relationship path is ambiguous")
            return shortest_paths[0]

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
            raw_candidates = raw_edges_between(subject.name, related.name)
            condition = None
            if len(raw_candidates) > 1:
                raise SchemaValidationError("schema relationship is ambiguous")
            if len(raw_candidates) == 1:
                condition = condition_for(raw_candidates[0], subject.name, related.name)
                joins.append({
                    "type": join_type,
                    "table": related.name,
                    "subject": subject.name,
                    "condition": condition,
                    "relational": relational,
                    "join_spec": join_spec,
                })
                continue
            if not relational:
                raise SchemaValidationError("multi-hop physical joins are unsupported")
            path = shortest_path(related)
            if path is None:
                raise SchemaValidationError("schema relationship path is missing")
            joins.append({
                "type": join_type,
                "table": related.name,
                "subject": subject.name,
                "condition": path[0][1],
                "path": [{"table": table.name, "condition": edge_condition} for table, edge_condition in path],
                "relational": True,
                "join_spec": join_spec,
            })
        return subject, joins

    def _schema_resolve_path_whose(
        self,
        parsed: _SchemaWhoseParsed,
        subject: SchemaTableContext,
        path_steps: tuple[object, ...],
        schema: SchemaContext,
    ) -> tuple[str | None, _nl2sql_ir.PathCondition | None]:
        """Resolve one whose predicate against the validated path tables."""
        path_tables = [subject]
        path_tables.extend(
            schema.table_candidates(step.to_table)[0]
            for step in path_steps
            if len(schema.table_candidates(step.to_table)) == 1
        )
        if len(path_tables) != len(path_steps) + 1:
            raise SchemaValidationError("path table is not unique")

        parts = parsed.raw_column.split(".")
        column_name = parts[-1]
        if len(parts) > 1:
            owners = schema.table_candidates(".".join(parts[:-1]))
            if len(owners) != 1:
                raise SchemaValidationError("whose column table is not unique")
            owner = owners[0]
            if owner.key not in {table.key for table in path_tables}:
                raise SchemaValidationError("whose column table is outside the path")
        else:
            owners = [
                table for table in path_tables
                if schema.canonical_column(table, column_name) is not None
            ]
            if len(owners) != 1:
                raise SchemaValidationError("whose column owner is ambiguous or unknown")
            owner = owners[0]

        canonical = schema.canonical_column(owner, column_name)
        if canonical is None:
            raise SchemaValidationError("whose column is outside the path schema")
        predicate = f"{owner.name}.{canonical} {parsed.operator} {parsed.literal}"
        if owner.key == subject.key:
            return predicate, None
        return None, _nl2sql_ir.PathCondition(
            table=owner.name,
            column=canonical,
            operator=parsed.operator,
            literal=parsed.literal,
        )

    def _schema_resolve_multihop_unique_path(
        self,
        text: str,
        table_hint: Optional[str],
        schema: SchemaContext,
        *,
        include_zero: bool = False,
        whose_span: tuple[int, int] | None = None,
    ) -> tuple[SchemaTableContext, tuple[object, ...], tuple[int, int]] | None:
        """Resolve one bounded two-hop path for a subject-grouped unique count."""
        if not self._schema_unique_count_spans(text, ("count", None)):
            return None
        executable = mask_non_executable(text)
        group_match = re.search(
            r"\b(?:per|each)\s+([A-Za-z_][A-Za-z0-9_$]*)\b",
            executable,
            re.IGNORECASE,
        )
        if group_match is None:
            group_match = re.search(
                r"(?:每个|各个|每位)\s*([\u4e00-\u9fff]{1,8}?)"
                r"(?=的|数量|数|$)",
                executable,
            )
        if group_match is None:
            return None
        label = group_match.group(1)
        if table_hint:
            subject_candidates = schema.table_candidates(table_hint)
        else:
            subject_candidates = schema.table_candidates(label)
            if not subject_candidates:
                mapped = {
                    pattern: table
                    for pattern, table in self.TABLE_PATTERNS.items()
                    if pattern.casefold() == label.casefold()
                }
                subject_candidates = tuple(
                    candidate
                    for table_name in mapped.values()
                    for candidate in schema.table_candidates(table_name)
                )
                if not subject_candidates:
                    return None
        if len(subject_candidates) != 1:
            raise SchemaValidationError("multi-hop group subject is not unique")
        subject = subject_candidates[0]
        if not subject.primary_key:
            raise SchemaValidationError("multi-hop group subject has no primary key")

        masked_group = self._schema_mask_span(executable, group_match.span())
        if whose_span is not None:
            masked_group = self._schema_mask_span(masked_group, whose_span)
        mentions = self._schema_table_mentions(masked_group, schema)
        target_candidates = tuple(table for table in mentions if table.key != subject.key)
        if len(target_candidates) != 1:
            raise SchemaValidationError("multi-hop target table is not unique")
        target = target_candidates[0]
        if not target.primary_key:
            raise SchemaValidationError("multi-hop target has no primary key")

        def complete_edge(edge, left: SchemaTableContext, right: SchemaTableContext) -> bool:
            if left.key == edge.from_table.casefold():
                pairs = edge.column_pairs
            else:
                pairs = tuple((to_column, from_column) for from_column, to_column in edge.column_pairs)
            if len(left.primary_key) > 1 and not {
                pair[0].casefold() for pair in pairs
            }.issuperset(column.casefold() for column in left.primary_key):
                return False
            if len(right.primary_key) > 1 and not {
                pair[1].casefold() for pair in pairs
            }.issuperset(column.casefold() for column in right.primary_key):
                return False
            return True

        def oriented_step(edge, left: SchemaTableContext, right: SchemaTableContext):
            if edge.from_table.casefold() == left.key:
                pairs = edge.column_pairs
            else:
                pairs = tuple((to_column, from_column) for from_column, to_column in edge.column_pairs)
            return _nl2sql_ir.PathStep(left.name, right.name, tuple(pairs))

        direct = schema.relationship_candidates(subject.name, target.name)
        if len(direct) > 1:
            raise SchemaValidationError("direct multi-hop target relationship is ambiguous")
        if direct:
            if len(subject.primary_key) == 1 and not include_zero:
                return None
            if not complete_edge(direct[0], subject, target):
                raise SchemaValidationError("direct relationship does not cover composite identity")
            return subject, (oriented_step(direct[0], subject, target),), group_match.span()

        queue: list[tuple[SchemaTableContext, list[object]]] = [(subject, [])]
        paths: list[list[object]] = []
        expansions = 0
        while queue:
            current, path = queue.pop(0)
            if len(path) >= 2:
                continue
            for edge in schema.relationships:
                endpoints = {edge.from_table.casefold(), edge.to_table.casefold()}
                if current.key not in endpoints:
                    continue
                next_name = (
                    edge.to_table
                    if edge.from_table.casefold() == current.key
                    else edge.from_table
                )
                candidates = schema.table_candidates(next_name)
                if len(candidates) != 1:
                    continue
                next_table = candidates[0]
                if next_table.key == subject.key or any(
                    step.to_table.casefold() == next_table.key for step in path
                ):
                    continue
                expansions += 1
                if expansions > 4096:
                    raise SchemaValidationError("multi-hop path search budget exceeded")
                if not complete_edge(edge, current, next_table):
                    continue
                next_path = [*path, oriented_step(edge, current, next_table)]
                if next_table.key == target.key:
                    paths.append(next_path)
                else:
                    queue.append((next_table, next_path))
        if not paths:
            raise SchemaValidationError("multi-hop target path is missing")
        shortest_length = min(len(path) for path in paths)
        shortest = [path for path in paths if len(path) == shortest_length]
        if shortest_length != 2 or len(shortest) != 1:
            raise SchemaValidationError("multi-hop target path is ambiguous or unsupported")
        return subject, tuple(shortest[0]), group_match.span()

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
            executable_text = mask_non_executable(text)
            zero_count_intent = self._schema_has_zero_count_intent(text)
            parsed_whose = self._schema_parse_whose(text)
            joined_on_resolution = self._schema_resolve_joined_on(
                text, table_hint, schema
            )
            joined_with_resolution = None
            if joined_on_resolution is None:
                joined_with_resolution = self._schema_resolve_joined_with(
                    text, table_hint, schema
                )
            multihop_unique_resolution = None
            if joined_on_resolution is None and joined_with_resolution is None:
                multihop_unique_resolution = self._schema_resolve_multihop_unique_path(
                    text,
                    table_hint,
                    schema,
                    include_zero=zero_count_intent,
                    whose_span=parsed_whose.span if parsed_whose is not None else None,
                )
            label_resolution = None
            if (
                joined_on_resolution is None
                and joined_with_resolution is None
                and multihop_unique_resolution is None
            ):
                label_resolution = self._schema_resolve_english_group_label(executable_text, schema)
                if label_resolution is None:
                    label_resolution = self._schema_resolve_chinese_group_label(executable_text, schema)
            ignored_label_spans = (label_resolution[2],) if label_resolution else ()
            unknown_tables = self._schema_unknown_table_patterns(
                text, schema, ignored_spans=ignored_label_spans
            )
            if unknown_tables:
                return self._schema_failure(
                    text,
                    dialect,
                    "The request references tables outside the provided schema.",
                )
            joined_on_span = None
            joined_with_span = None
            if joined_on_resolution is not None:
                table_context, joins, joined_on_span = joined_on_resolution
                metric_text = self._schema_mask_span(text_lower, joined_on_span)
            elif joined_with_resolution is not None:
                table_context, joins, joined_with_span = joined_with_resolution
                metric_text = self._schema_mask_span(text_lower, joined_with_span)
            elif multihop_unique_resolution is not None:
                table_context, path_steps, group_span = multihop_unique_resolution
                joins = []
                metric_text = self._schema_mask_span(text_lower, group_span)
            elif label_resolution is not None:
                table_context = label_resolution[0]
                label_group_column = label_resolution[1]
                joins = []
                start, end = label_resolution[2]
                metric_text = text_lower[:start] + " " * (end - start) + text_lower[end:]
            else:
                table_context, joins = self._schema_resolve_joins(text, table_hint, schema)
                metric_text = text_lower
            whose_resolution = (
                None
                if multihop_unique_resolution is not None
                else self._schema_resolve_whose(text, table_context, schema)
            )
            whose_condition = None
            path_conditions: list[_nl2sql_ir.PathCondition] = []
            ordinary_conditions: list[str] = []
            whose_span: tuple[int, int] | None = None
            if multihop_unique_resolution is not None and parsed_whose is not None:
                subject, path_steps, _ = multihop_unique_resolution
                whose_condition, path_condition = self._schema_resolve_path_whose(
                    parsed_whose,
                    subject,
                    path_steps,
                    schema,
                )
                if path_condition is not None:
                    path_conditions.append(path_condition)
                whose_span = parsed_whose.span
            condition_text = text_lower
            condition_original = text
            if joined_on_span is not None:
                condition_text = self._schema_mask_span(condition_text, joined_on_span)
                condition_original = self._schema_mask_span(condition_original, joined_on_span)
            elif joined_with_span is not None:
                condition_text = self._schema_mask_span(condition_text, joined_with_span)
                condition_original = self._schema_mask_span(condition_original, joined_with_span)
            if whose_resolution is not None:
                whose_condition, whose_span = whose_resolution
                metric_text = self._schema_mask_span(metric_text, whose_span)
                condition_text = self._schema_mask_span(condition_text, whose_span)
                condition_original = self._schema_mask_span(condition_original, whose_span)
            elif whose_span is not None:
                metric_text = self._schema_mask_span(metric_text, whose_span)
                condition_text = self._schema_mask_span(condition_text, whose_span)
                condition_original = self._schema_mask_span(condition_original, whose_span)
            count_metric = self._schema_resolve_count_metric(
                text_lower, table_context, schema
            )
            if multihop_unique_resolution is not None and count_metric is None:
                count_metric = ("count", None)
            unique_count_spans = self._schema_unique_count_spans(
                text_lower, count_metric
            )
            unique_count_intent = bool(unique_count_spans)
            if zero_count_intent and (
                not unique_count_intent or multihop_unique_resolution is None
            ):
                raise SchemaValidationError(
                    "zero-count requests require a unique-count path and group label"
                )
            columns = self._schema_resolve_columns(
                metric_text,
                table_context,
                column_hints,
                schema,
                suppress_quantity_token=count_metric is not None,
            )
            conditions = self._schema_resolve_conditions(
                condition_text,
                self._extract_conditions_enhanced(condition_text, condition_original),
                table_context,
                schema,
            )
            ordinary_conditions = list(conditions)
            if whose_condition is not None:
                conditions = [*conditions, whose_condition]
            parsed = self._parse_text(text_lower, text)
            parsed.update(analysis)
            operation = self._detect_operation(text_lower)
            aggregations = self._schema_extract_aggregations(
                metric_text, table_context, schema, count_metric
            )
            group_by = (
                []
                if multihop_unique_resolution is not None
                else [label_group_column]
                if label_resolution is not None
                else self._schema_resolve_group_by(
                    self._schema_mask_clause_tail(text_lower)
                    if unique_count_intent
                    else text_lower,
                    table_context,
                    schema,
                    aggregations,
                )
            )
            distinct = self._check_distinct(text_lower)
            distinct_count_plan = None
            path_distinct_count_plan = None
            if unique_count_intent:
                if len(unique_count_spans) != 1:
                    raise SchemaValidationError(
                        "multiple unique count phrases are unsupported"
                    )
                consumed = text_lower
                for span in unique_count_spans:
                    consumed = self._schema_mask_span(consumed, span)
                if self._check_distinct(consumed):
                    raise SchemaValidationError(
                        "unique count cannot be combined with DISTINCT projection"
                    )
                if joins:
                    raise SchemaValidationError(
                        "unique count with relationships is unsupported"
                    )
                if multihop_unique_resolution is not None:
                    if ordinary_conditions:
                        raise SchemaValidationError(
                            "path unique count only supports whose predicates"
                        )
                    subject, path_steps, _ = multihop_unique_resolution
                    path_distinct_count_plan = _nl2sql_ir.PathDistinctCountPlan(
                        subject_table=subject.name,
                        path_steps=tuple(path_steps),
                        group_identity=tuple(subject.primary_key),
                        target_identity=tuple(
                            schema.table_candidates(path_steps[-1].to_table)[0].primary_key
                        ),
                        exclude_null_identity=True,
                        include_zero=zero_count_intent,
                        path_conditions=tuple(path_conditions),
                    )
                if len(table_context.primary_key) == 0:
                    raise SchemaValidationError(
                        "unique count requires a declared primary key"
                    )
                if any(
                    not aggregation.upper().startswith("COUNT(")
                    for aggregation in aggregations
                ):
                    raise SchemaValidationError(
                        "unique count cannot combine with non-COUNT aggregation"
                    )
                if path_distinct_count_plan is not None:
                    aggregations = []
                elif len(table_context.primary_key) == 1:
                    aggregations = [
                        f"COUNT(DISTINCT {table_context.primary_key[0]}) AS count"
                    ]
                else:
                    aggregations = []
                    distinct_count_plan = _nl2sql_ir.DistinctCountPlan(
                        tuple(table_context.primary_key),
                        exclude_null_identity=True,
                    )
                distinct = False
            if any(join.get("path") for join in joins):
                if conditions or aggregations or group_by or label_resolution is not None or distinct:
                    raise SchemaValidationError(
                        "multi-hop paths cannot be combined with filters or aggregation"
                    )
            ordering_candidates: list[tuple[str, str]] = []
            aggregate_orderings = None
            if path_distinct_count_plan is not None:
                path_orderings = self._schema_resolve_path_ordering(
                    text_lower,
                    table_context,
                    schema,
                    path_distinct_count_plan,
                    parsed_whose=parsed_whose,
                    group_span=(
                        multihop_unique_resolution[2]
                        if multihop_unique_resolution is not None
                        else None
                    ),
                )
                path_distinct_count_plan = replace(
                    path_distinct_count_plan,
                    path_orderings=path_orderings,
                )
            elif unique_count_intent and group_by:
                aggregate_orderings = self._schema_resolve_aggregate_ordering(
                    text_lower, table_context, schema, group_by,
                    whose_span=whose_span,
                    group_span=(label_resolution[2] if label_resolution is not None else None),
                )
            elif unique_count_intent and self._schema_has_explicit_ordering(text_lower):
                raise SchemaValidationError("unique scalar count ordering is unsupported")
            else:
                ordering_candidates = (
                    self._schema_resolve_ordering(text_lower, table_context, schema)
                    if self._schema_has_explicit_ordering(text_lower)
                    else []
                )
            if path_distinct_count_plan is None and len(ordering_candidates) > 1 and (
                group_by or aggregations or label_resolution is not None
            ):
                raise SchemaValidationError(
                    "multi-column ORDER BY combinations are unsupported"
                )
            if path_distinct_count_plan is None and len(ordering_candidates) > 1 and distinct:
                if columns == ["*"]:
                    raise SchemaValidationError(
                        "DISTINCT * cannot be combined with multi-column ORDER BY"
                    )
                projected = {
                    column.rsplit(".", 1)[-1].casefold()
                    for column in columns
                }
                if any(column.casefold() not in projected for column, _ in ordering_candidates):
                    raise SchemaValidationError(
                        "DISTINCT ORDER BY columns must be projected"
                    )
            ordering = (
                ordering_candidates[0]
                if path_distinct_count_plan is None and len(ordering_candidates) == 1
                else None
            )
            orderings = (
                ordering_candidates
                if path_distinct_count_plan is None and len(ordering_candidates) > 1
                else None
            )
            if path_distinct_count_plan is not None:
                masked_path_text = mask_non_executable(text_lower)
                if parsed_whose is not None:
                    masked_path_text = self._schema_mask_span(
                        masked_path_text,
                        parsed_whose.span,
                    )
                if multihop_unique_resolution is not None:
                    masked_path_text = self._schema_mask_span(
                        masked_path_text,
                        multihop_unique_resolution[2],
                    )
                limit = self._extract_limit(masked_path_text)
            else:
                if aggregate_orderings is not None:
                    masked_aggregate_text = mask_non_executable(text_lower)
                    if whose_span is not None:
                        masked_aggregate_text = self._schema_mask_span(masked_aggregate_text, whose_span)
                    if label_resolution is not None:
                        masked_aggregate_text = self._schema_mask_span(masked_aggregate_text, label_resolution[2])
                    limit = self._extract_limit(masked_aggregate_text)
                else:
                    limit = self._extract_limit(text_lower)
            render_columns = ["*"] if aggregations and not group_by else columns
            sql, explanation, confidence, evidence = self._build_sql_enhanced(
                operation,
                table_context.name,
                render_columns,
                conditions,
                aggregations,
                group_by,
                ordering,
                limit,
                joins,
                distinct,
                dialect,
                orderings=orderings,
                distinct_count_plan=distinct_count_plan,
                path_distinct_count_plan=path_distinct_count_plan,
                aggregate_orderings=aggregate_orderings,
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
            finalized = self._schema_finalize(result, schema)
            if finalized.success and finalized.schema_used:
                finalized.suggestions = self._schema_diagnostic_suggestions(
                    text,
                    table_context,
                    schema,
                    columns,
                    list(finalized.suggestions),
                )
            return finalized
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
        orderings=None,
        distinct_count_plan=None,
        path_distinct_count_plan=None,
        aggregate_orderings=None,
    ) -> tuple:
        """Build SQL statement from extracted components.

        Delegates to ``nl2sql_pipeline.renderer.render_sql``.
        Fail-closed behaviour (unresolved join → success=False) is
        enforced by ``render_sql``.
        """
        ir = _nl2sql_ir.build_ir(
            operation, table, columns, conditions, aggregations,
            group_by, ordering, limit, joins, distinct, dialect,
            orderings=orderings,
            distinct_count_plan=distinct_count_plan,
            path_distinct_count_plan=path_distinct_count_plan,
            aggregate_orderings=aggregate_orderings,
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
