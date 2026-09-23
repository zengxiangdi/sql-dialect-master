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
        text_lower: str = "",
        text_original: str = "",
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
        # The clause-aware merge below combines the branch's own predicates
        # with any template-external time/status condition without duplicating
        # a clause the branch owns. The extractor must see the full original
        # text for number extraction: the template capture alone silently
        # drops conditions that sit outside the captured window.
        external_conditions = self._extract_conditions_enhanced(
            text_lower, text_original or text_lower
        )

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
                # The canonical D3 semantic expression is the single source of
                # the date predicate. Other external conditions (comparisons,
                # status flags) stay template-external and are composed by the
                # clause-aware merge below, which de-duplicates instead of
                # re-appending a second WHERE.
                n = numbers[0] if numbers else "7"
                date_col = (
                    "created_at"
                    if "created_at" in str(analysis["columns"])
                    else "date"
                )
                date_predicate = None
                for c in external_conditions:
                    if "DATE_SUB" in c or "ADD_MONTHS" in c or "DATE_ADD" in c:
                        date_predicate = c
                        break
                if date_predicate is None:
                    date_predicate = f"{date_col} >= DATE_SUB(CURRENT_DATE, {n})"
                sql = f"SELECT *\nFROM {table}\nWHERE {date_predicate}"
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
                condition_predicate = f"{col} {op} {value}"
                # Fold in template-external conditions that are not already
                # implied by the branch's own comparison. Date predicates are
                # recognised by their canonical D3 forms; any other external
                # condition (status, flags) is appended verbatim.
                sql = f"SELECT *\nFROM {table}\nWHERE {condition_predicate}"
                for c in external_conditions:
                    if c in sql:
                        continue
                    if "DATE_SUB" not in c and "ADD_MONTHS" not in c:
                        sql += f"\nAND {c}"
                explanation_parts.append(f"条件: {col} {op} {value}")
                confidence += 0.1
            elif template.name == "join_query":
                # JOIN composition is owned by the enhanced path: route every
                # join request through _extract_joins, which only yields a
                # canonical condition for known relationships. The template
                # must not invent a condition of its own.
                all_joins = self._extract_joins(text_lower)
                joins = [j for j in all_joins if j["condition"] is not None]
                # The join request is only safe when every pair the text names
                # has a canonical relationship; otherwise fail the request.
                pairs_blocked = [j for j in all_joins if j["condition"] is None]
                if pairs_blocked:
                    blocked = " ⟷ ".join(
                        [j["subject"] for j in pairs_blocked]
                        + [j["table"] for j in pairs_blocked]
                    )
                    return NL2SQLResult(
                        success=False,
                        input_text=match_groups.get("match", ""),
                        sql=None,
                        dialect=dialect,
                        explanation=(
                            "Unable to safely infer the relationship between the "
                            f"table(s) involved ({blocked}). Please provide the "
                            "join condition or schema relationship."
                        ),
                        confidence=0.0,
                        suggestions=[
                            "Specify the relationship between tables, "
                            "e.g., 'users.id = invoices.user_id'"
                        ],
                        parsed_elements=analysis,
                    )
                if joins:
                    subject = self._extract_table_subject(text_lower)
                    subject = subject or joins[0].get("subject")
                    sql = f"SELECT *\nFROM {subject or joins[0]['table']}"
                    for join in joins:
                        sql += f"\nJOIN {join['table']} ON {join['condition']}"
                        explanation_parts.append(
                            f"关联: {subject or joins[0]['table']} ⟷ {join['table']}"
                        )
                    confidence += 0.15 * len(joins)
                else:
                    # No known pair resolvable — fail-safe too.
                    return NL2SQLResult(
                        success=False,
                        input_text=match_groups.get("match", ""),
                        sql=None,
                        dialect=dialect,
                        explanation=(
                            "Unable to safely infer the relationship between the "
                            "table(s). Please provide the join condition or "
                            "schema relationship."
                        ),
                        confidence=0.0,
                        suggestions=[
                            "Specify the relationship between tables, "
                            "e.g., 'users.id = invoices.user_id'"
                        ],
                        parsed_elements=analysis,
                    )
            elif template.name == "select_with_columns":
                cols = ", ".join(columns) if columns != ["*"] else "*"
                sql = f"SELECT {cols}\nFROM {table}"
                explanation_parts.append(f"查询: {cols}")
            else:
                sql = f"SELECT *\nFROM {table}"
                explanation_parts.append(f"查询表: {table}")

            # Clause-aware predicate composition: add only the time/status
            # conditions the composed SQL does not already carry. Branches
            # that own their WHERE clause (time_range/condition) already
            # folded the external conditions in above; this step then
            # de-duplicates instead of appending a second WHERE.
            merged_conditions: List[str] = []
            for c in external_conditions:
                base = c.split(" AND ")[0] if " AND " in c else c
                base = base.strip()
                if base in sql or c in sql:
                    continue
                if not any(
                    kw in text_lower
                    for kw in [
                        "today", "yesterday", "tomorrow", "last", "past",
                        "本周", "本月", "本年", "今天", "昨天", "明天"
                    ]
                ) and c in [
                    "status = 'active'", "status = 'inactive'",
                    "is_deleted = 1", "is_deleted = 0"
                ]:
                    continue
                merged_conditions.append(c)
            if merged_conditions:
                if "WHERE" in sql.upper():
                    sql = f"{sql}\nAND {' AND '.join(merged_conditions)}"
                else:
                    sql = f"{sql}\nWHERE {' AND '.join(merged_conditions)}"
                explanation_parts.append(f"日期条件: {len(merged_conditions)}个")
                confidence += 0.1

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
        # Word-boundary matching for tables to avoid false positives like "order" matching "orders"
        import re as _re
        for pattern, table in self.TABLE_PATTERNS.items():
            if _re.search(r'\b' + _re.escape(pattern) + r'\b', text_lower) and table not in parsed["tables"]:
                parsed["tables"].append(table)
        # Word-boundary matching for columns
        for pattern, column in self.COLUMN_PATTERNS.items():
            if re.search(r'\b' + re.escape(pattern) + r'\b', text_lower) and column not in parsed["columns"]:
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

    def _extract_table_subject(self, text: str) -> Optional[str]:
        """Extract the subject table (first appearing in text) for D2 relational queries.

        For queries like 'users who have orders', returns 'users' (the subject)
        rather than 'orders' (the relation). Uses first occurrence position.
        """
        candidates = []
        for pattern, table in self.TABLE_PATTERNS.items():
            if table not in candidates:
                pos = text.find(pattern)
                if pos != -1:
                    candidates.append((pos, table))
        if candidates:
            candidates.sort(key=lambda x: x[0])
            return candidates[0][1]
        return None

    def _named_tables(self, text: str) -> list:
        """Return the distinct table names the text mentions, in order of first appearance."""
        occurrences = []
        seen = set()
        for pattern, table in self.TABLE_PATTERNS.items():
            if table in seen:
                continue
            pos = text.find(pattern)
            if pos != -1:
                occurrences.append((pos, table))
                seen.add(table)
        return [t for _, t in sorted(occurrences)]

    def _extract_columns(self, text: str) -> list:
        """Extract column names from text."""
        columns = []
        for pattern, column in self.COLUMN_PATTERNS.items():
            if pattern in text and column not in columns:
                columns.append(column)
        return columns if columns else ["*"]

    def _extract_conditions_enhanced(self, text: str, original: str) -> list:
        """Extract WHERE conditions with enhanced parsing including boolean expressions."""
        # Use the structured boolean extractor first — it correctly handles
        # multiple predicates connected by AND/OR while preserving precedence.
        boolean_conditions = extract_boolean_conditions(text)
        if boolean_conditions:
            return boolean_conditions

        conditions = []
        numbers = re.findall(r"\d+\.?\d*", original)
        condition_column = None
        for pattern, column in self.COLUMN_PATTERNS.items():
            if pattern in text:
                condition_column = column
                break

        # Handle IN/NOT IN predicate (must come before generic comparison handling)
        in_matched_columns: set = set()
        in_match = re.search(
            r"\b(\w+)\s+(not\s+)?in\s*\(([^)]+)\)",
            text,
            re.IGNORECASE,
        )
        if in_match:
            col = in_match.group(1)
            negation = in_match.group(2) is not None
            raw_values = in_match.group(3).strip()
            # Parse comma-separated values, preserving quoted strings
            values = []
            current = ""
            quote_char = None
            for char in raw_values:
                if char in ("'", '"'):
                    if quote_char and quote_char == char:
                        quote_char = None
                    elif not quote_char:
                        quote_char = char
                    current += char
                elif char == "," and not quote_char:
                    if current.strip():
                        values.append(current.strip())
                    current = ""
                else:
                    current += char
            if current.strip():
                values.append(current.strip())

            if values:
                formatted_values = ", ".join(
                    f"'{v}'" if v.startswith(("'", '"')) or not re.match(r"^-?\d+(\.\d+)?$", v) else v
                    for v in values
                )
                operator = "NOT IN" if negation else "IN"
                conditions.append(f"{col} {operator} ({formatted_values})")
                in_matched_columns.add(col.lower())

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
        elif "明天" in text or "tomorrow" in text:
            conditions.append(f"{date_col} = DATE_ADD(CURRENT_DATE, 1)")

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

        # Bare period expressions without explicit count
        if not any(c for c in conditions if "DATE_SUB" in c or "DATE_ADD" in c or "ADD_MONTHS" in c or "CURRENT_DATE" in c):
            if ("last week" in text or "本周" in text) and "this week" not in text and "本周" not in text:
                conditions.append(f"{date_col} >= DATE_SUB(CURRENT_DATE, 7)")
            if "last month" in text:
                conditions.append(f"{date_col} >= ADD_MONTHS(CURRENT_DATE, -1)")
            if "last year" in text:
                conditions.append(f"{date_col} >= ADD_MONTHS(CURRENT_DATE, -12)")

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
            # Skip status pattern if the column was already matched via IN predicate
            col_match = re.match(r"^(\w+)\s*=", condition)
            col_name = col_match.group(1).lower() if col_match else None
            if col_name and col_name in in_matched_columns:
                continue
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
        # Use word-boundary matching to avoid false positives (e.g., "orders" contains "order")
        if any(re.search(rf'\b{k}\b', text, re.IGNORECASE) for k in ["排序", "排列", "sort", "order", "sorted"]):
            return (
                order_col or "id",
                "DESC"
                if any(re.search(rf'\b{k}\b', text, re.IGNORECASE) for k in ["降序", "从大到小", "递减", "desc", "descending", "decreasing"])
                else "ASC",
            )
        if any(re.search(rf'\b{k}\b', text, re.IGNORECASE) for k in ["最大", "最高", "最多", "max", "highest", "top"]):
            return (order_col or "amount", "DESC")
        if any(re.search(rf'\b{k}\b', text, re.IGNORECASE) for k in ["最小", "最低", "最少", "min", "lowest"]):
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
        """Extract JOIN information from text.

        Detects relational existence patterns (e.g., "users who have orders")
        and returns structured join contexts for EXISTS-based SQL generation.
        """
        joins = []
        # Collect unique tables in text-appearance order (first occurrence wins)
        # Exclude "order" when it's part of "order by" sorting clause
        table_occurrences = []
        for pattern, table in self.TABLE_PATTERNS.items():
            # Skip "order" pattern if it's part of "order by" sorting clause
            if pattern == "order" and re.search(r'\border\b\s+by\b', text, re.IGNORECASE):
                continue
            if re.search(r'\b' + re.escape(pattern) + r'\b', text) and table not in [t for _, t in table_occurrences]:
                table_occurrences.append((text.find(pattern), table))
        tables_found = [t for _, t in sorted(table_occurrences)]
        if len(tables_found) >= 2:
            # Determine relation type from keywords
            # Positive relational: "who have", "with", etc. -> EXISTS
            # Negative relational: "without", "not have", etc. -> NOT EXISTS
            # Explicit JOIN keywords: physical JOIN
            if any(k in text for k in [
                "without", "not have", "no ",
                "who don't have", "who doesn't have",
                "who do not have", "who does not have",
            ]):
                join_type = "NOT EXISTS"
            elif any(k in text for k in [
                "who have", "who has", "that have", "that has",
                "with orders", "with customers",
                "with users", "with employees",
                "with invoices", "with payments", "with transactions",
                "with suppliers", "with products",
                "who placed", "who made", "who created", "who submitted",
                "in departments", "in products", "in orders", "in users",
            ]):
                join_type = "EXISTS"
            elif any(k in text for k in ["left join", "right join",
                                          "inner join", "outer join",
                                          "左连接", "右连接", "内连接"]):
                join_type = text.split()[0].upper() if " " in text else "JOIN"
            else:
                join_type = "JOIN"

            main_table = tables_found[0]
            for other_table in tables_found[1:]:
                join_key = self._guess_join_key(main_table, other_table)
                if join_key is None:
                    # Unknown relationship - do not generate fabricated condition.
                    # Carry both sides of the pair so downstream fail-closed
                    # messages can name the actual unresolved relationship
                    # rather than re-deriving it from the final table variable.
                    joins.append({
                        "type": join_type,
                        "table": other_table,
                        "subject": main_table,
                        "condition": None,
                        "relational": join_type in ("EXISTS", "NOT EXISTS"),
                    })
                    continue
                joins.append({
                    "type": join_type,
                    "table": other_table,
                    "subject": main_table,
                    "condition": join_key,
                    # Mark as relational (EXISTS/NOT EXISTS) rather than physical JOIN
                    "relational": join_type in ("EXISTS", "NOT EXISTS"),
                })
        return joins

    def _guess_join_key(self, table1: str, table2: str) -> Optional[str]:
        """Guess the join key between two tables.

        Returns None for unknown relationships instead of guessing.
        """
        join_patterns = {
            ("users", "orders"): "users.id = orders.user_id",
            ("orders", "users"): "orders.user_id = users.id",
            ("users", "transactions"): "users.id = transactions.user_id",
            ("orders", "products"): "orders.product_id = products.id",
            ("products", "orders"): "products.id = orders.product_id",
            ("users", "products"): "users.id = products.user_id",
            ("products", "users"): "products.user_id = users.id",
            ("employees", "departments"): "employees.dept_id = departments.id",
            ("departments", "employees"): "departments.id = employees.dept_id",
            ("orders", "payments"): "orders.id = payments.order_id",
            ("customers", "orders"): "customers.id = orders.customer_id",
            ("orders", "customers"): "orders.customer_id = customers.id",
        }
        key = (table1, table2)
        if key in join_patterns:
            return join_patterns[key]
        # Unknown relationship - do not guess
        return None

    def _check_distinct(self, text: str) -> bool:
        """Check if DISTINCT is needed."""
        return any(k in text for k in ["去重", "唯一", "不重复", "distinct", "unique"])

    def _has_relational_keyword(self, text: str) -> bool:
        """Check if text contains relational existence keywords (D2)."""
        relational_patterns = [
            "who have", "who has", "that have", "that has",
            "who don't have", "who doesn't have", "who do not have", "who does not have",
            "without", "no ", "not have", "don't have", "doesn't have",
            "with orders", "with customers", "with products",
            "with users", "with employees", "with suppliers",
            "with invoices", "with payments", "with transactions",
            "who placed", "who made", "who created", "who submitted",
            "in departments", "in products", "in orders", "in users",
        ]
        return any(pattern in text for pattern in relational_patterns)

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

        Fail-closed: any join entry with ``condition is None`` (an
        unresolved/unknown relationship) immediately returns
        ``(None, explanation, 0.0)`` so the caller observes
        ``success=False``.  The relationship is never silently dropped.
        """
        # ------------------------------------------------------------------
        # Structural guard: reject unresolved joins at the entry point.
        # This is the single canonical fail-closed check; it covers every
        # call site of _build_sql_enhanced (early boolean/null path,
        # ordinary enhanced fallback, and any future caller) without
        # requiring each caller to duplicate the check.
        # ------------------------------------------------------------------
        for join in joins:
            if join.get("condition") is None:
                # Use the subject/table context carried by the join entry
                # (populated by _extract_joins) so the pair is named from
                # the actual relationship structure, not from the final
                # `table` variable which may have been resolved differently.
                subject = join.get("subject") or table
                pair_desc = f"{subject} ⟷ {join['table']}"
                explanation = (
                    "Unable to safely infer the relationship between the "
                    f"table(s) involved ({pair_desc}). Please provide the "
                    "join condition or schema relationship."
                )
                return None, explanation, 0.0

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
                # Join conditions are only ever emitted from a resolved
                # canonical relationship (G1). Unresolved pairs are blocked
                # upstream by generate(); keep a structural guard so a join
                # can never be composed with a missing condition.
                if join.get("condition") is None:
                    continue
                if join.get("relational"):
                    # EXISTS/NOT EXISTS: preserves row count, no duplicates
                    if join["type"] == "NOT EXISTS":
                        subquery = f"SELECT 1\n    FROM {join['table']}\n    WHERE {join['condition']}"
                        # Merge date conditions into subquery if present
                        if conditions:
                            cond_sql = conditions if isinstance(conditions, str) else " AND ".join(conditions)
                            subquery += f"\n    AND {cond_sql}"
                            conditions = []  # Remove from top-level conditions
                        sql += f"\nWHERE NOT EXISTS (\n    {subquery}\n)"
                        explanation_parts.append(f"关联: {join['table']} (NOT EXISTS)")
                    else:
                        subquery = f"SELECT 1\n    FROM {join['table']}\n    WHERE {join['condition']}"
                        # Merge date conditions into subquery if present
                        if conditions:
                            cond_sql = conditions if isinstance(conditions, str) else " AND ".join(conditions)
                            subquery += f"\n    AND {cond_sql}"
                            conditions = []  # Remove from top-level conditions
                        sql += f"\nWHERE EXISTS (\n    {subquery}\n)"
                        explanation_parts.append(f"关联: {join['table']} (EXISTS)")
                    confidence += 0.1
                else:
                    # Physical JOIN (original behavior)
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
