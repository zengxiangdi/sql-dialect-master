#!/usr/bin/env python3
"""Query Template module for NL2SQL.

Provides pattern-based SQL generation using prioritized templates.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Callable

logger = logging.getLogger(__name__)


# Clause markers that mean a single-purpose or catch-all template may truncate
# part of the user's intent. Composed queries must flow to enhanced parsing.
_COMPOSITION_MARKERS = (
    "order by", "sort", "排序", "排列",
    "group by", "grouped by", "分组", "汇总",
    "limit", "top ", "top\t", "only ", "前",
    " and ", " or ", "且", "并且", "或者", "或",
)

_TEMPLATE_BLOCKERS = {
    "condition_query": _COMPOSITION_MARKERS,
    "aggregate_query": _COMPOSITION_MARKERS,
    "time_range_query": _COMPOSITION_MARKERS,
    "select_with_columns": _COMPOSITION_MARKERS,
    "simple_select": _COMPOSITION_MARKERS,
}

# Keep template captures bounded. These patterns run against natural-language
# query text, so unbounded adjacent wildcards can cause excessive backtracking
# on adversarial input. 512 characters is ample for each individual template
# field while making the regex work bounded by construction.
_TEMPLATE_CAPTURE_LIMIT = 512


@dataclass
class QueryTemplate:
    """Template for pattern-based SQL generation with priority.

    Templates are matched in priority order (highest first).
    Each template has a regex pattern and a SQL template with placeholders.
    """
    name: str
    pattern: str
    sql_template: str
    priority: int = 50
    extractor: Optional[Callable] = None
    _compiled_pattern: re.Pattern = field(init=False, repr=False, default=None)

    def __post_init__(self):
        """Pre-compile regex pattern for better performance."""
        try:
            self._compiled_pattern = re.compile(self.pattern, re.IGNORECASE)
        except re.error as e:
            logger.warning(f"Failed to compile pattern for template {self.name}: {e}")
            self._compiled_pattern = None

    def match(self, text: str) -> Optional[Dict[str, Any]]:
        """Try to match this template against input text."""
        normalized = text.lower()
        blockers = _TEMPLATE_BLOCKERS.get(self.name, ())
        if any(marker in normalized for marker in blockers):
            logger.debug(
                "Skipping template '%s' because composition markers require enhanced parsing",
                self.name,
            )
            return None

        if self._compiled_pattern is None:
            match = re.search(self.pattern, text, re.IGNORECASE)
        else:
            match = self._compiled_pattern.search(text)

        if match:
            return match.groupdict() if match.groupdict() else {"match": match.group(0)}
        return None


DEFAULT_QUERY_TEMPLATES = [
    QueryTemplate(
        name="top_n_query",
        pattern=rf"(?:查询|获取|get|show|find)?\s*(?:前|top|bottom|最低|最少|lowest|smallest)\s*(\d+)\s*(?:个|条|名)?\s*(.{{1,{_TEMPLATE_CAPTURE_LIMIT}}}?)(?:按|by)?\s*(.{{1,{_TEMPLATE_CAPTURE_LIMIT}}})?\s*(?:排序|排列|order)?",
        sql_template="SELECT * FROM {table} ORDER BY {order_col} DESC LIMIT {n}",
        priority=90,
    ),
    QueryTemplate(
        name="count_by_group",
        pattern=rf"(?:统计|计算|count)\s*(?:每个|各个|each)?\s*(.{{1,{_TEMPLATE_CAPTURE_LIMIT}}}?)\s*(?:的|的数量|数量|有多少)",
        sql_template="SELECT {group_col}, COUNT(*) AS count FROM {table} GROUP BY {group_col}",
        priority=85,
    ),
    QueryTemplate(
        name="time_range_query",
        pattern=r"(?:查询|获取|get|find)?\s*(?:最近|过去|last|past)\s*(\d+)\s*(天|周|月|年|days?|weeks?|months?|years?)\s*(?:的|内的)?\s*(.+)",
        sql_template="SELECT * FROM {table} WHERE {date_col} >= DATE_SUB(CURRENT_DATE, {interval})",
        priority=85,
    ),
    QueryTemplate(
        name="aggregate_query",
        pattern=rf"(?:计算|求|get)?\s*(.{{1,{_TEMPLATE_CAPTURE_LIMIT}}}?)\s*(?:的)?\s*(平均|总和|最大|最小|average|sum|max|min)\s*(.{{1,{_TEMPLATE_CAPTURE_LIMIT}}})",
        sql_template="SELECT {agg_func}({col}) FROM {table}",
        priority=80,
    ),
    QueryTemplate(
        name="condition_query",
        pattern=rf"(?:查询|获取|find|get)?\s*(.{{1,{_TEMPLATE_CAPTURE_LIMIT}}}?)\s*(大于|小于|等于|超过|不等于|greater(?:\s+than)?|less(?:\s+than)?|equal(?:\s+to)?|>|<|=)\s*(\d+\.?\d*)\s*(?:的)?\s*(.{{1,{_TEMPLATE_CAPTURE_LIMIT}}})?",
        sql_template="SELECT * FROM {table} WHERE {col} {op} {value}",
        priority=75,
    ),
    QueryTemplate(
        name="join_query",
        pattern=rf"(?:查询|获取)?\s*(.{{1,{_TEMPLATE_CAPTURE_LIMIT}}}?)\s*(?:和|与|关联|连接|join)\s*(.{{1,{_TEMPLATE_CAPTURE_LIMIT}}}?)(?:的|数据)?",
        sql_template="SELECT * FROM {table1} JOIN {table2} ON {join_condition}",
        priority=70,
    ),
    QueryTemplate(
        name="select_with_columns",
        pattern=rf"(?:查询|获取|显示|select|get|show)\s*(.{{1,{_TEMPLATE_CAPTURE_LIMIT}}}?)\s*(?:的|from)?\s*(.{{1,{_TEMPLATE_CAPTURE_LIMIT}}}?)(?:表|table)?$",
        sql_template="SELECT {columns} FROM {table}",
        priority=60,
    ),
    QueryTemplate(
        name="simple_select",
        pattern=r"(?:查询|获取|显示|列出|select|get|show|list|find)\s*(?:所有|全部|all)?\s*(.+)",
        sql_template="SELECT * FROM {table}",
        priority=40,
    ),
]
