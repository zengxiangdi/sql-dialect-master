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
from typing import Any, Dict, List, Optional, Tuple

import sqlglot

from .column_hint_validation import validate_column_hints
from .config import SUPPORTED_DIALECTS, settings
from .nl2sql_components.mappings import (
    KEYWORDS as MAPPING_KEYWORDS,
    TABLE_PATTERNS as MAPPING_TABLE_PATTERNS,
    COLUMN_PATTERNS as MAPPING_COLUMN_PATTERNS,
)
from .nl2sql_components.templates import DEFAULT_QUERY_TEMPLATES, QueryTemplate
from .nl2sql_components.tokenizer import Tokenizer
from .nl2sql_components.boolean_conditions import extract_boolean_conditions

logger = logging.getLogger(__name__)


@dataclass
class NL2SQLResult:
    """Result of NL2SQL generation."""

    success: bool = False
    input_text: str = ""
    sql: Optional[str] = None
    dialect: str = ""
    explanation: str = ""
    confidence: float = 0.0
    suggestions: list = field(default_factory=list)
    parsed_elements: dict = field(default_factory=dict)


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
        """Try to match input text against query templates."""
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
        """Tokenize text and perform semantic analysis."""
        tokens = self.tokenizer.tokenize(text)
        numbers = self.tokenizer.extract_numbers(text)
        quoted = self.tokenizer.extract_quoted_strings(text)

        detected_tables = [
            self.TABLE_PATTERNS[token]
            for token in tokens
            if token in self.TABLE_PATTERNS
        ]
        detected_columns = [
            self.COLUMN_PATTERNS[token]
            for token in tokens
            if token in self.COLUMN_PATTERNS
        ]
        detected_ops = [
            self.KEYWORDS[token]
            for token in tokens
            if token in self.KEYWORDS
        ]

        return {
            "tokens": tokens,
            "numbers": numbers,
            "quoted_strings": quoted,
            "tables": list(set(detected_tables)),
            "columns": list(set(detected_columns)),
            "operations": list(set(detected_ops)),
            "is_chinese": self.tokenizer.is_chinese(text),
            "token_count": len(tokens),
        }

    def _generate_from_template(
        self,
        template: QueryTemplate,
        match_groups: Dict[str, Any],
        analysis: Dict[str, Any],
        dialect: str,
        table_hint: Optional[str],
        column_hints: Optional[List[str]],
    ) -> NL2SQLResult:
        """Generate SQL from a matched template."""
        confidence = 0.7
        explanation_parts = []
        table = table_hint or (
            analysis["tables"][0] if analysis["tables"] else "table_name"
        )
        if table != "table_name":
            confidence += 0.1
        columns = column_hints or analysis["columns"] or ["*"]
        numbers = analysis["numbers"]

        try:
            if template.name == "top_n_query":
                n = numbers[0] if numbers else "10"
                order_col = analysis["columns"][0] if analysis["columns"] else "id"
                sql = (
                    f"SELECT *\nFROM {table}\n"
                    f"ORDER BY {order_col} DESC\nLIMIT {n}"
                )
                explanation_parts.append(f"查询前{n}条记录")
                confidence += 0.1
            elif template.name == "count_by_group":
                group_col = (
                    analysis["columns"][0] if analysis["columns"] else "category"
                )
                sql = (
                    f"SELECT {group_col}, COUNT(*) AS count\n"
                    f"FROM {table}\nGROUP BY {group_col}"
                )
                explanation_parts.append(f"按{group_col}分组统计")
                confidence += 0.1
            elif template.name == "time_range_query":
                n = numbers[0] if numbers else "7"
                date_col = (
                    "created_at"
                    if "created_at" in str(analysis["columns"])
                    else "date"
                )
                sql = (
                    f"SELECT *\nFROM {table}\n"
                    f"WHERE {date_col} >= DATE_SUB(CURRENT_DATE, {n})"
                )
                explanation_parts.append(f"查询最近{n}天数据")
                confidence += 0.1
            elif template.name == "aggregate_query":
                agg_func = "COUNT"
                for token in analysis["tokens"]:
                    if token in ["平均", "average", "avg"]:
                        agg_func = "AVG"
                    elif token in ["总和", "sum", "合计"]:
                        agg_func = "SUM"
                    elif token in ["最大", "max", "maximum"]:
                        agg_func = "MAX"
                    elif token in ["最小", "min", "minimum"]:
                        agg_func = "MIN"
                col = analysis["columns"][0] if analysis["columns"] else "*"
                sql = f"SELECT {agg_func}({col}) AS result\nFROM {table}"
                explanation_parts.append(f"计算{agg_func}({col})")
                confidence += 0.1
            elif template.name == "condition_query":
                col = analysis["columns"][0] if analysis["columns"] else "column"
                value = numbers[0] if numbers else "0"
                op = "="
                for token in analysis["tokens"]:
                    if token in ["大于", "超过", "greater", ">"]:
                        op = ">"
                    elif token in ["小于", "低于", "less", "<"]:
                        op = "<"
                    elif token in ["不等于", "!="]:
                        op = "!="
                    elif token in ["大于等于", ">="]:
                        op = ">="
                    elif token in ["小于等于", "<="]:
                        op = "<="
                sql = f"SELECT *\nFROM {table}\nWHERE {col} {op} {value}"
                explanation_parts.append(f"条件: {col} {op} {value}")
                confidence += 0.1
            elif template.name == "join_query":
                tables = analysis["tables"]
                if len(tables) >= 2:
                    t1, t2 = tables[0], tables[1]
                    join_key = self._guess_join_key(t1, t2)
                    sql = f"SELECT *\nFROM {t1}\nJOIN {t2} ON {join_key}"
                    explanation_parts.append(f"关联: {t1} ⟷ {t2}")
                    confidence += 0.15
                else:
                    sql = (
                        f"SELECT *\nFROM {table}\n"
                        f"JOIN table2 ON {table}.id = table2.{table.rstrip('s')}_id"
                    )
                    explanation_parts.append("关联查询 (请指定第二个表)")
                    confidence -= 0.1
            elif template.name == "select_with_columns":
                cols = ", ".join(columns) if columns != ["*"] else "*"
                sql = f"SELECT {cols}\nFROM {table}"
                explanation_parts.append(f"查询: {cols}")
            else:
                sql = f"SELECT *\nFROM {table}"
                explanation_parts.append(f"查询表: {table}")

            sql = f"-- Generated for {dialect.upper()}\n{sql}"
            sql = self._apply_dialect_adjustments(sql, dialect)
            confidence += self._validate_generated_sql(sql, dialect)
            suggestions = self._generate_suggestions_for_template(
                template, table, columns, dialect
            )

            return NL2SQLResult(
                success=True,
                input_text=match_groups.get("match", ""),
                sql=sql,
                dialect=dialect,
                explanation=" | ".join(explanation_parts),
                confidence=min(max(confidence, 0.0), 1.0),
                suggestions=suggestions,
                parsed_elements=analysis,
            )
        except Exception as exc:
            logger.warning("Template generation failed: %s", exc)
            return NL2SQLResult(
                success=False,
                input_text=str(match_groups),
                dialect=dialect,
                explanation=f"Template error: {exc}",
                confidence=0.0,
            )

    def _generate_suggestions_for_template(
        self,
        template: QueryTemplate,
        table: str,
        columns: List[str],
        dialect: str,
    ) -> List[str]:
        """Generate suggestions specific to template-based generation."""
        suggestions = []
        if table == "table_name":
            suggestions.append("💡 请指定具体的表名，如：用户表、订单表、员工表")
        if columns == ["*"]:
            suggestions.append("💡 建议指定具体列名以提高查询性能")
        if template.name == "join_query":
            suggestions.append("💡 请确认关联条件是否正确")
        if template.name == "time_range_query" and dialect == "oracle":
            suggestions.append("💡 Oracle 日期函数语法可能需要调整")
        return suggestions

    def generate(
        self,
        text: str,
        dialect: str = None,
        table_hint: str = None,
        column_hints: List[str] = None,
    ) -> NL2SQLResult:
        """Generate SQL from natural language text."""
        dialect = dialect or self.default_dialect
        error = validate_column_hints(column_hints)
        if error:
            return NL2SQLResult(
                success=False,
                input_text=text if isinstance(text, str) else "",
                dialect=dialect,
                explanation=error,
                confidence=0.0,
            )
        text_lower = text.lower()

        logger.info("NL2SQL: Processing '%s...' for dialect %s", text[:50], dialect)
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
            table = table_hint or self._extract_table(text_lower)
            columns = column_hints if column_hints else self._extract_columns(text_lower)
            conditions = self._extract_conditions_enhanced(text_lower, text)
            aggregations = self._extract_aggregations(text_lower)
            group_by = self._extract_group_by(text_lower)
            ordering = self._extract_ordering(text_lower)
            limit = self._extract_limit(text_lower)
            joins = self._extract_joins(text_lower)
            distinct = self._check_distinct(text_lower)
            sql, explanation, confidence = self._build_sql_enhanced(
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
            suggestions = self._generate_suggestions(text, sql, dialect)
            return NL2SQLResult(
                success=sql is not None,
                input_text=text,
                sql=sql,
                dialect=dialect,
                explanation=explanation,
                confidence=confidence,
                suggestions=suggestions,
                parsed_elements=parsed,
            )

        template, match_groups = self._match_templates(text_lower)
        if template:
            result = self._generate_from_template(
                template, match_groups, analysis, dialect, table_hint, column_hints
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
        table = table_hint or self._extract_table(text_lower)
        columns = column_hints if column_hints else self._extract_columns(text_lower)
        conditions = self._extract_conditions_enhanced(text_lower, text)
        aggregations = self._extract_aggregations(text_lower)
        group_by = self._extract_group_by(text_lower)
        ordering = self._extract_ordering(text_lower)
        limit = self._extract_limit(text_lower)
        joins = self._extract_joins(text_lower)
        distinct = self._check_distinct(text_lower)

        sql, explanation, confidence = self._build_sql_enhanced(
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
        suggestions = self._generate_suggestions(text, sql, dialect)

        return NL2SQLResult(
            success=sql is not None,
            input_text=text,
            sql=sql,
            dialect=dialect,
            explanation=explanation,
            confidence=confidence,
            suggestions=suggestions,
            parsed_elements=parsed,
        )

    def _parse_text(self, text_lower: str, original: str) -> dict:
        """Parse and extract all elements from text."""
        parsed = {
            "tables": [],
            "columns": [],
            "conditions": [],
            "aggregations": [],
            "time_range": None,
            "limit": None,
            "order": None,
            "joins": [],
        }
        for pattern, table in self.TABLE_PATTERNS.items():
            if pattern in text_lower and table not in parsed["tables"]:
                parsed["tables"].append(table)
        for pattern, column in self.COLUMN_PATTERNS.items():
            if pattern in text_lower and column not in parsed["columns"]:
                parsed["columns"].append(column)
        numbers = re.findall(r"\d+", original)
        if numbers:
            parsed["numbers"] = numbers
        return parsed

    def _detect_operation(self, text: str) -> str:
        """Detect SQL operation type from text."""
        for keyword, op in self.KEYWORDS.items():
            if keyword in text and op in ["SELECT", "INSERT", "UPDATE", "DELETE"]:
                return op
        return "SELECT"

    def _extract_table(self, text: str) -> str:
        """Extract table name from text."""
        tables_found = []
        for pattern, table in self.TABLE_PATTERNS.items():
            if pattern in text:
                tables_found.append((text.find(pattern), table, len(pattern)))
        if tables_found:
            tables_found.sort(key=lambda item: (-item[2], item[0]))
            return tables_found[0][1]
        return "table_name"

    def _extract_columns(self, text: str) -> list:
        """Extract column names from text."""
        columns = []
        for pattern, column in self.COLUMN_PATTERNS.items():
            if pattern in text and column not in columns:
                columns.append(column)
        return columns if columns else ["*"]
