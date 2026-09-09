"""Stable NL2SQL facade with focused semantic extraction fixes."""
import re

from .nl2sql_legacy import NL2SQLGenerator as _NL2SQLGenerator
from .nl2sql_legacy import NL2SQLResult


class NL2SQLGenerator(_NL2SQLGenerator):
    """Keep the public generator API while fixing count/group semantics."""

    def _match_templates(self, text: str):
        """Route count-by-group requests through enhanced semantic extraction."""
        template, match_groups = super()._match_templates(text)
        if template and template.name == "count_by_group":
            return None, None
        return template, match_groups

    def _extract_group_by(self, text: str) -> list:
        """Extract explicit per-group intent such as '每个部门' when needed."""
        group_cols = super()._extract_group_by(text)
        if group_cols:
            return group_cols

        match = re.search(r"(?:每个|各个)\s*([^的\s]+?)\s*的", text, re.IGNORECASE)
        if not match:
            match = re.search(r"(?:per|each)\s+(\w+)\b", text, re.IGNORECASE)
        if not match:
            return []

        group_text = match.group(1).strip()
        for keyword, column in self.COLUMN_PATTERNS.items():
            if keyword in group_text:
                return [column]
        if "部门" in group_text or "department" in group_text:
            return ["department"]
        if "用户" in group_text or "user" in group_text:
            return ["user_id"]
        if "日期" in group_text or "date" in group_text:
            return ["date"]
        return []

    def _extract_ordering(self, text: str):
        """Order aggregate-count requests by the requested count deterministically."""
        ordering = super()._extract_ordering(text)
        count_requested = any(
            keyword in text
            for keyword in ["数量", "计数", "多少", "count", "how many"]
        )
        sorting_requested = any(
            keyword in text
            for keyword in ["排序", "排列", "sort", "order", "sorted"]
        )
        if count_requested and sorting_requested:
            descending = any(
                keyword in text
                for keyword in [
                    "降序",
                    "从大到小",
                    "递减",
                    "desc",
                    "descending",
                    "decreasing",
                ]
            )
            ascending = any(
                keyword in text
                for keyword in [
                    "升序",
                    "从小到大",
                    "递增",
                    "asc",
                    "ascending",
                    "increasing",
                ]
            )
            return "count", "ASC" if ascending and not descending else "DESC"
        return ordering
