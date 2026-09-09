"""Quote/comment-aware adapters for legacy custom SQL transformations."""
from __future__ import annotations

import re

from .post_processor import PostProcessor
from .sql_scanner import replace_outside, mask_non_executable

_ORIGINAL_TOP = PostProcessor._convert_top_to_limit
_ORIGINAL_ROWNUM = PostProcessor._convert_rownum_to_limit
_ORIGINAL_GROUP_CONCAT = PostProcessor._fix_group_concat_default_separator


def _convert_top_scanned(self, sql):
    masked = mask_non_executable(sql)
    match = re.search(r"\bSELECT\s+TOP\s+(\d+)\b", masked, re.IGNORECASE)
    if not match:
        return sql, []
    number = match.group(1)
    cleaned, count = replace_outside(
        sql,
        re.compile(r"\bSELECT\s+TOP\s+\d+\b", re.IGNORECASE),
        "SELECT",
    )
    if not count:
        return sql, []
    if re.search(r"\bLIMIT\b", mask_non_executable(cleaned), re.IGNORECASE):
        return cleaned, [f"Converted TOP {number} to existing LIMIT"]
    return cleaned.rstrip(" ;\t\r\n") + f" LIMIT {number}", [
        f"Converted TOP {number} to LIMIT {number}"
    ]


def _convert_rownum_scanned(self, sql):
    masked = mask_non_executable(sql)
    match = re.search(r"\bROWNUM\s*<=?\s*(\d+)\b", masked, re.IGNORECASE)
    if not match:
        return sql, []
    number = match.group(1)
    result, count = replace_outside(
        sql,
        re.compile(r"\s+AND\s+ROWNUM\s*<=?\s*\d+\b", re.IGNORECASE),
        "",
    )
    if not count:
        result, count = replace_outside(
            sql,
            re.compile(r"\bWHERE\s+ROWNUM\s*<=?\s*\d+\b", re.IGNORECASE),
            "",
        )
    if not count:
        return sql, [
            "Skipped automatic ROWNUM conversion because predicate shape was not safely removable"
        ]
    if re.search(r"\bLIMIT\b", mask_non_executable(result), re.IGNORECASE):
        return result, [f"Converted ROWNUM <= {number} using existing LIMIT"]
    return result.rstrip(" ;\t\r\n") + f" LIMIT {number}", [
        f"Converted ROWNUM to LIMIT {number}"
    ]


def _fix_group_concat_scanned(self, sql):
    masked = mask_non_executable(sql)
    if "GROUP_CONCAT" not in masked.upper():
        return sql, []

    def replace_call(args, original):
        if re.search(r"\bSEPARATOR\b", args, re.IGNORECASE):
            return original
        values = self._parse_function_args(args)
        if len(values) != 1:
            return original
        expression = values[0]
        return f"STRING_AGG({expression}::TEXT, ',')"

    result = self._replace_function_calls(sql, "GROUP_CONCAT", replace_call)
    return (
        result,
        ["Converted GROUP_CONCAT to STRING_AGG with default separator"]
        if result != sql
        else [],
    )


PostProcessor._convert_top_to_limit = _convert_top_scanned
PostProcessor._convert_rownum_to_limit = _convert_rownum_scanned
PostProcessor._fix_group_concat_default_separator = _fix_group_concat_scanned
