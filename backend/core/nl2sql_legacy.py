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
from .nl2sql_components.templates import DEFAULT_QUERY_TEMPLATES, QueryTemplate
from .nl2sql_components.tokenizer import Tokenizer

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
                # Determine ordering direction based on request text
                request_text = str((match_groups or {}).get("match", "")).lower()
                ascending_requested = bool(
                    re.search(r"\b(bottom|lowest|smallest)\b|最低|最少", request_text)
                )
                order_dir = "ASC" if ascending_requested else "DESC"
                if ascending_requested:
                    explanation_parts.append(f"查询最低/最少{n}条记录")
                else:
                    explanation_parts.append(f"查询前{n}条记录")
                base_sql = (
                    f"SELECT *\nFROM {table}\n"
                    f"ORDER BY {order_col} {order_dir}"
                )
                sql = self._add_limit(base_sql, int(n), dialect)
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

    def _extract_conditions_enhanced(self, text: str, original: str) -> list:
        """Extract WHERE conditions with enhanced parsing."""
        conditions = []
        numbers = re.findall(r"\d+\.?\d*", original)
        condition_column = None
        for pattern, column in self.COLUMN_PATTERNS.items():
            if pattern in text:
                condition_column = column
                break

        comparisons = [
            (["大于等于", "不小于", "至少", "greater than or equal to", "larger than or equal to"], ">="),
            (["小于等于", "不大于", "最多", "less than or equal to", "smaller than or equal to"], "<="),
            (["不等于", "不是", "不为", "not equal", "isn't", "doesn't equal"], "!="),
            (["大于", "超过", "高于", "多于", "greater", "more than", "above", "over", ">"], ">"),
            (["小于", "低于", "少于", "不足", "less", "less than", "below", "under", "<"], "<"),
            (["等于", "是", "为", "equals", "equal", "="], "="),
        ]
        for keywords, op in comparisons:
            if any(keyword in text for keyword in keywords) and numbers:
                col = condition_column or "column"
                conditions.append(f"{col} {op} {numbers[0]}")
                break

        if any(keyword in text for keyword in ["之间", "范围", "between", "from...to"]):
            if len(numbers) >= 2:
                col = condition_column or "column"
                conditions.append(f"{col} BETWEEN {numbers[0]} AND {numbers[1]}")

        if any(keyword in text for keyword in ["包含", "含有", "contains", "like", "includes"]):
            match = re.search(r"[\"']([^\"']+)[\"']", original)
            if match:
                col = condition_column or "column"
                conditions.append(f"{col} LIKE '%{match.group(1)}%'")

        has_negative_null = any(
            keyword in text
            for keyword in ["非空", "不为空", "is not null", "not null", "not empty"]
        )
        if has_negative_null:
            conditions.append(f"{condition_column or 'column'} IS NOT NULL")
        elif any(keyword in text for keyword in ["为空", "空值", "is null", "null", "empty"]):
            conditions.append(f"{condition_column or 'column'} IS NULL")

        date_col = "created_at" if "created_at" in text else "date"
        if "今天" in text or "today" in text:
            conditions.append(f"{date_col} = CURRENT_DATE")
        elif "昨天" in text or "yesterday" in text:
            conditions.append(f"{date_col} = DATE_SUB(CURRENT_DATE, 1)")
        elif "前天" in text or "day before" in text:
            conditions.append(f"{date_col} = DATE_SUB(CURRENT_DATE, 2)")

        time_patterns = [
            (r"(最近|过去|last|past)\s*(\d+)\s*(天|day)", "DAY"),
            (r"(最近|过去|last|past)\s*(\d+)\s*(周|week)", "WEEK"),
            (r"(最近|过去|last|past)\s*(\d+)\s*(月|month)", "MONTH"),
            (r"(最近|过去|last|past)\s*(\d+)\s*(年|year)", "YEAR"),
        ]
        for pattern, unit in time_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                n = match.group(2)
                if unit == "DAY":
                    conditions.append(f"{date_col} >= DATE_SUB(CURRENT_DATE, {n})")
                elif unit == "WEEK":
                    conditions.append(f"{date_col} >= DATE_SUB(CURRENT_DATE, {int(n) * 7})")
                elif unit == "MONTH":
                    conditions.append(f"{date_col} >= ADD_MONTHS(CURRENT_DATE, -{n})")
                elif unit == "YEAR":
                    conditions.append(f"{date_col} >= ADD_MONTHS(CURRENT_DATE, -{int(n) * 12})")
                break

        if "本周" in text or "this week" in text:
            conditions.append(f"WEEKOFYEAR({date_col}) = WEEKOFYEAR(CURRENT_DATE)")
        if "本月" in text or "this month" in text:
            conditions.append(
                f"MONTH({date_col}) = MONTH(CURRENT_DATE) AND YEAR({date_col}) = YEAR(CURRENT_DATE)"
            )
        if "本年" in text or "this year" in text:
            conditions.append(f"YEAR({date_col}) = YEAR(CURRENT_DATE)")

        status_patterns = [
            (["有效", "active", "enabled", "valid"], "status = 'active'"),
            (["无效", "inactive", "disabled", "invalid"], "status = 'inactive'"),
            (["已删除", "deleted", "removed"], "is_deleted = 1"),
            (["未删除", "not deleted"], "is_deleted = 0"),
            (["已完成", "completed", "done", "finished"], "status = 'completed'"),
            (["未完成", "pending", "incomplete"], "status = 'pending'"),
            (["已支付", "paid"], "status = 'paid'"),
            (["未支付", "unpaid"], "status = 'unpaid'"),
        ]
        for keywords, condition in status_patterns:
            if any(keyword in text for keyword in keywords):
                conditions.append(condition)
                break
        return conditions

    def _extract_aggregations(self, text: str) -> list:
        """Extract aggregation functions from text."""
        aggs = []
        agg_column = None
        for pattern, column in self.COLUMN_PATTERNS.items():
            if pattern in text:
                agg_column = column
                break
        col = agg_column or "amount"
        if any(k in text for k in ["统计", "计数", "数量", "多少", "几个", "count", "total", "how many"]):
            aggs.append("COUNT(*)")
        if any(k in text for k in ["求和", "总和", "合计", "总计", "sum", "total of"]):
            aggs.append(f"SUM({col})")
        if any(k in text for k in ["平均", "均值", "平均值", "average", "avg", "mean"]):
            aggs.append(f"AVG({col})")
        if any(k in text for k in ["最大", "最高", "最多", "max", "maximum", "highest", "largest"]):
            aggs.append(f"MAX({col})")
        if any(k in text for k in ["最小", "最低", "最少", "min", "minimum", "lowest", "smallest"]):
            aggs.append(f"MIN({col})")
        return aggs

    def _extract_group_by(self, text: str) -> list:
        """Extract GROUP BY columns from text."""
        group_cols = []
        patterns = [
            r"按(.+?)(分组|汇总|统计)",
            r"group\s*by\s*(\w+)",
            r"grouped\s*by\s*(\w+)",
            r"per\s+(\w+)",
            r"each\s+(\w+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            group_text = match.group(1).strip()
            for kw, col in self.COLUMN_PATTERNS.items():
                if kw in group_text:
                    group_cols.append(col)
                    break
            else:
                for kw in self.TABLE_PATTERNS:
                    if kw in group_text:
                        if "部门" in group_text or "department" in group_text:
                            group_cols.append("department")
                        elif "用户" in group_text or "user" in group_text:
                            group_cols.append("user_id")
                        elif "日期" in group_text or "date" in group_text:
                            group_cols.append("date")
                        elif "月" in group_text or "month" in group_text:
                            group_cols.append("MONTH(date)")
                        elif "年" in group_text or "year" in group_text:
                            group_cols.append("YEAR(date)")
                        break
        return group_cols

    def _extract_ordering(self, text: str) -> Optional[Tuple[str, str]]:
        """Extract ORDER BY clause from text."""
        order_col = None
        for pattern, column in self.COLUMN_PATTERNS.items():
            if pattern in text:
                order_col = column
                break
        if any(k in text for k in ["排序", "排列", "sort", "order", "sorted"]):
            return (
                order_col or "id",
                "DESC"
                if any(k in text for k in ["降序", "从大到小", "递减", "desc", "descending", "decreasing"])
                else "ASC",
            )
        if any(k in text for k in ["最大", "最高", "最多", "max", "highest", "top"]):
            return (order_col or "amount", "DESC")
        if any(k in text for k in ["最小", "最低", "最少", "min", "lowest"]):
            return (order_col or "amount", "ASC")
        return None

    def _extract_limit(self, text: str) -> Optional[int]:
        """Extract LIMIT value from text."""
        patterns = [
            r"前\s*(\d+)", r"top\s*(\d+)", r"limit\s*(\d+)",
            r"first\s*(\d+)", r"(\d+)\s*条", r"(\d+)\s*个",
            r"(\d+)\s*行", r"(\d+)\s*rows?", r"only\s*(\d+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return int(match.group(1))
        return None

    def _extract_joins(self, text: str) -> list:
        """Extract JOIN information from text."""
        joins = []
        tables_found = []
        for pattern, table in self.TABLE_PATTERNS.items():
            if pattern in text and table not in tables_found:
                tables_found.append(table)
        if len(tables_found) >= 2:
            join_type = "JOIN"
            if any(k in text for k in ["左连接", "left join", "左关联"]):
                join_type = "LEFT JOIN"
            elif any(k in text for k in ["右连接", "right join", "右关联"]):
                join_type = "RIGHT JOIN"
            elif any(k in text for k in ["内连接", "inner join"]):
                join_type = "INNER JOIN"
            main_table = tables_found[0]
            for other_table in tables_found[1:]:
                joins.append(
                    {
                        "type": join_type,
                        "table": other_table,
                        "condition": self._guess_join_key(main_table, other_table),
                    }
                )
        return joins

    def _guess_join_key(self, table1: str, table2: str) -> str:
        """Guess the join key between two tables."""
        join_patterns = {
            ("users", "orders"): "users.id = orders.user_id",
            ("orders", "users"): "orders.user_id = users.id",
            ("users", "transactions"): "users.id = transactions.user_id",
            ("orders", "products"): "orders.product_id = products.id",
            ("products", "orders"): "products.id = orders.product_id",
            ("employees", "departments"): "employees.dept_id = departments.id",
            ("departments", "employees"): "departments.id = employees.dept_id",
            ("orders", "payments"): "orders.id = payments.order_id",
            ("customers", "orders"): "customers.id = orders.customer_id",
        }
        key = (table1, table2)
        if key in join_patterns:
            return join_patterns[key]
        singular = table1.rstrip("s")
        return f"{table1}.id = {table2}.{singular}_id"

    def _check_distinct(self, text: str) -> bool:
        """Check if DISTINCT is needed."""
        return any(k in text for k in ["去重", "唯一", "不重复", "distinct", "unique"])

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
        """Build SQL statement from extracted components."""
        explanation_parts = []
        confidence = 0.5
        if operation == "SELECT":
            distinct_kw = "DISTINCT " if distinct else ""
            if aggregations:
                if group_by:
                    select_parts = group_by + aggregations
                    select_clause = ", ".join(select_parts)
                else:
                    select_clause = ", ".join(aggregations)
                explanation_parts.append(f"聚合: {', '.join(aggregations)}")
                confidence += 0.15
            else:
                select_clause = ", ".join(columns)
                if columns != ["*"]:
                    explanation_parts.append(f"列: {', '.join(columns)}")
                    confidence += 0.1
            sql = f"SELECT {distinct_kw}{select_clause}\nFROM {table}"
            explanation_parts.append(f"表: {table}")
            if table != "table_name":
                confidence += 0.2
            for join in joins:
                sql += f"\n{join['type']} {join['table']} ON {join['condition']}"
                explanation_parts.append(f"关联: {join['table']}")
                confidence += 0.1
            if conditions:
                condition_sql = conditions if isinstance(conditions, str) else " AND ".join(conditions)
                sql += f"\nWHERE {condition_sql}"
                count = len(conditions) if not isinstance(conditions, str) else 1
                explanation_parts.append(f"条件: {count}个")
                confidence += 0.1
            if group_by:
                sql += f"\nGROUP BY {', '.join(group_by)}"
                explanation_parts.append(f"分组: {', '.join(group_by)}")
                confidence += 0.1
            elif aggregations and columns != ["*"]:
                group_cols = [c for c in columns if c != "*"]
                if group_cols:
                    sql += f"\nGROUP BY {', '.join(group_cols)}"
            if ordering:
                sql += f"\nORDER BY {ordering[0]} {ordering[1]}"
                explanation_parts.append(f"排序: {ordering[0]} {ordering[1]}")
            if limit:
                sql = self._add_limit(sql, limit, dialect)
                explanation_parts.append(f"限制: {limit}条")
                confidence += 0.1
        elif operation == "INSERT":
            cols = columns if columns != ["*"] else ["col1", "col2"]
            placeholders = ", ".join(["?"] * len(cols))
            sql = f"INSERT INTO {table} ({', '.join(cols)})\nVALUES ({placeholders})"
            explanation_parts.append(f"插入到: {table}")
        elif operation == "UPDATE":
            update_cols = columns if columns != ["*"] else ["column"]
            set_clause = ", ".join([f"{c} = ?" for c in update_cols])
            sql = f"UPDATE {table}\nSET {set_clause}"
            if conditions:
                condition_sql = conditions if isinstance(conditions, str) else " AND ".join(conditions)
                sql += f"\nWHERE {condition_sql}"
            else:
                sql += "\nWHERE id = ?"
            explanation_parts.append(f"更新: {table}")
        elif operation == "DELETE":
            sql = f"DELETE FROM {table}"
            if conditions:
                condition_sql = conditions if isinstance(conditions, str) else " AND ".join(conditions)
                sql += f"\nWHERE {condition_sql}"
            else:
                sql += "\nWHERE id = ?"
            explanation_parts.append(f"删除: {table}")
        else:
            sql = f"-- 无法解析: {operation}"
            confidence = 0.0

        sql = f"-- Generated for {dialect.upper()}\n{sql}"
        sql = self._apply_dialect_adjustments(sql, dialect)
        confidence += self._validate_generated_sql(sql, dialect)
        return sql, " | ".join(explanation_parts), min(max(confidence, 0.0), 1.0)

    def _validate_generated_sql(self, sql: str, dialect: str) -> float:
        """Validate generated SQL syntax and return confidence adjustment."""
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

    def _add_limit(self, sql: str, limit: int, dialect: str) -> str:
        """Add LIMIT clause with dialect-specific syntax."""
        if dialect == "oracle":
            return f"{sql}\nFETCH FIRST {limit} ROWS ONLY"
        if dialect == "tsql":
            return sql.replace("SELECT", f"SELECT TOP {limit}", 1)
        return f"{sql}\nLIMIT {limit}"

    def _apply_dialect_adjustments(self, sql: str, dialect: str) -> str:
        """Apply dialect-specific syntax adjustments.

        Uses executable-region-aware replacement so literals, comments, and
        quoted identifiers are never modified.
        """
        from .p1_sql_scanner import executable_segments

        dialect = dialect.lower()

        if dialect == "hive":
            return sql

        replacements: list[tuple[re.Pattern, str | Callable[[re.Match[str]], str]]] = []

        if dialect == "oracle":
            # Handle DATE_SUB/DATE_ADD/ADD_MONTHS with CURRENT_DATE first,
            # then handle the already-converted forms (TRUNC(SYSDATE)).
            replacements = [
                (
                    re.compile(
                        r"\bDATE_SUB\(\s*(?:TRUNC\(SYSDATE\)|CURRENT_DATE)\s*,\s*(\d+)\s*\)",
                        re.IGNORECASE,
                    ),
                    r"TRUNC(SYSDATE) - \1",
                ),
                (
                    re.compile(
                        r"\bDATE_ADD\(\s*(?:TRUNC\(SYSDATE\)|CURRENT_DATE)\s*,\s*(\d+)\s*\)",
                        re.IGNORECASE,
                    ),
                    r"TRUNC(SYSDATE) + \1",
                ),
                (
                    re.compile(
                        r"\bADD_MONTHS\(\s*(?:TRUNC\(SYSDATE\)|CURRENT_DATE)\s*,\s*([+-]?\d+)\s*\)",
                        re.IGNORECASE,
                    ),
                    r"ADD_MONTHS(TRUNC(SYSDATE), \1)",
                ),
                (re.compile(r"\bCURRENT_TIMESTAMP\b", re.IGNORECASE), "SYSTIMESTAMP"),
                (re.compile(r"\bCURRENT_DATE\b", re.IGNORECASE), "TRUNC(SYSDATE)"),
            ]
        elif dialect == "tsql":
            replacements = [
                (
                    re.compile(
                        r"\bDATE_SUB\(\s*(?:CAST\(GETDATE\(\)\s+AS\s+DATE\)|CURRENT_DATE)\s*,\s*(\d+)\s*\)",
                        re.IGNORECASE,
                    ),
                    r"DATEADD(DAY, -\1, CAST(GETDATE() AS DATE))",
                ),
                (
                    re.compile(
                        r"\bDATE_ADD\(\s*(?:CAST\(GETDATE\(\)\s+AS\s+DATE\)|CURRENT_DATE)\s*,\s*(\d+)\s*\)",
                        re.IGNORECASE,
                    ),
                    r"DATEADD(DAY, \1, CAST(GETDATE() AS DATE))",
                ),
                (
                    re.compile(
                        r"\bADD_MONTHS\(\s*(?:CAST\(GETDATE\(\)\s+AS\s+DATE\)|CURRENT_DATE)\s*,\s*([+-]?\d+)\s*\)",
                        re.IGNORECASE,
                    ),
                    r"DATEADD(MONTH, \1, CAST(GETDATE() AS DATE))",
                ),
                (re.compile(r"\bCURRENT_TIMESTAMP\b", re.IGNORECASE), "SYSDATETIME()"),
                (re.compile(r"\bCURRENT_DATE\b", re.IGNORECASE), "CAST(GETDATE() AS DATE)"),
            ]
        elif dialect == "mysql":
            replacements = [
                (
                    re.compile(r"\bDATE_SUB\(\s*CURRENT_DATE\s*,\s*(\d+)\s*\)", re.IGNORECASE),
                    r"DATE_SUB(CURRENT_DATE, INTERVAL \1 DAY)",
                ),
                (
                    re.compile(r"\bDATE_ADD\(\s*CURRENT_DATE\s*,\s*(\d+)\s*\)", re.IGNORECASE),
                    r"DATE_ADD(CURRENT_DATE, INTERVAL \1 DAY)",
                ),
                (
                    re.compile(
                        r"\bADD_MONTHS\(\s*CURRENT_DATE\s*,\s*([+-]?\d+)\s*\)",
                        re.IGNORECASE,
                    ),
                    lambda match: (
                        f"DATE_SUB(CURRENT_DATE, INTERVAL {abs(int(match.group(1)))} MONTH)"
                        if int(match.group(1)) < 0
                        else f"DATE_ADD(CURRENT_DATE, INTERVAL {match.group(1)} MONTH)"
                    ),
                ),
            ]
        elif dialect in ("postgres", "duckdb"):
            replacements = [
                (
                    re.compile(r"\bDATE_SUB\(\s*CURRENT_DATE\s*,\s*(\d+)\s*\)", re.IGNORECASE),
                    r"CURRENT_DATE - INTERVAL '\1 days'",
                ),
                (
                    re.compile(r"\bDATE_ADD\(\s*CURRENT_DATE\s*,\s*(\d+)\s*\)", re.IGNORECASE),
                    r"CURRENT_DATE + INTERVAL '\1 days'",
                ),
                (
                    re.compile(
                        r"\bADD_MONTHS\(\s*CURRENT_DATE\s*,\s*([+-]?\d+)\s*\)",
                        re.IGNORECASE,
                    ),
                    r"CURRENT_DATE + INTERVAL '\1 month'",
                ),
            ]
        else:
            return sql

        for pattern, replacement in replacements:
            parts = []
            cursor = 0
            for start, end in executable_segments(sql):
                parts.append(sql[cursor:start])
                segment = sql[start:end]
                segment = pattern.sub(replacement, segment)
                parts.append(segment)
                cursor = end
            parts.append(sql[cursor:])
            sql = "".join(parts)

        return sql

    def _generate_suggestions(self, text: str, sql: str, dialect: str) -> list:
        """Generate improvement suggestions."""
        suggestions = []
        if "table_name" in sql:
            suggestions.append("💡 请指定具体的表名，如：用户表、订单表")
        if "column >" in sql or "column <" in sql or "column =" in sql:
            suggestions.append("💡 请指定具体的列名用于条件判断，如：年龄大于30")
        if dialect == "hive" and "SELECT *" in sql:
            suggestions.append("💡 Hive 建议指定具体列名以提高性能")
        if "JOIN" not in sql and any(k in text for k in ["关联", "连接", "join", "和", "与"]):
            suggestions.append("💡 检测到关联需求，请明确指定两个表名")
        if "?" in sql:
            suggestions.append("💡 请替换 ? 占位符为实际值")
        if "GROUP BY" in sql and "HAVING" not in sql:
            suggestions.append("💡 可以添加 HAVING 子句过滤分组结果")
        if dialect == "hive" and "ORDER BY" in sql and "LIMIT" not in sql:
            suggestions.append("💡 Hive 中 ORDER BY 建议配合 LIMIT 使用")
        if "DELETE" in sql and "WHERE" not in sql:
            suggestions.append("⚠️ DELETE 没有 WHERE 条件将删除所有数据！")
        if "UPDATE" in sql and "WHERE" not in sql:
            suggestions.append("⚠️ UPDATE 没有 WHERE 条件将更新所有数据！")
        return suggestions

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
