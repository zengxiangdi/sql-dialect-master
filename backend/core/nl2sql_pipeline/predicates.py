#!/usr/bin/env python3
"""P8 NL2SQL pipeline: predicate extraction (moved from nl2sql_legacy).

``extract_conditions`` is a verbatim move of
``nl2sql_legacy._extract_conditions_enhanced``.  All keyword tables,
IN-predicate parsing, comparison operators, BETWEEN / LIKE / NULL /
date / time / status rules are unchanged; the only difference is that
``COLUMN_PATTERNS`` is now passed as a parameter instead of read from
the instance attribute.
"""
import re
from typing import Dict, List, Optional

from ..nl2sql_components.boolean_conditions import (
    extract_boolean_conditions,
    extract_status_conditions,
)
from ..p1_sql_scanner import mask_non_executable

_QUOTED_COMPARISON_PREFIX = re.compile(
    r"(?<![\w$])([A-Za-z_][A-Za-z0-9_$]*)\s*"
    r"(is\s+not|isn't|not|is|<>|!=|>=|<=|=|>|<)\s*",
    re.IGNORECASE,
)


def _column_for_text(text: str, column_patterns: Dict[str, str]) -> Optional[str]:
    for pattern, column in sorted(column_patterns.items(), key=lambda item: -len(item[0])):
        expression = re.escape(pattern)
        if not re.search(r"[\u4e00-\u9fff]", pattern):
            expression = rf"(?<![\w$]){expression}(?![\w$])"
        if re.search(expression, text, re.IGNORECASE):
            return column
    return None


def _quoted_comparisons(
    original: str, column_patterns: Dict[str, str]
) -> list[str]:
    quoted = []
    executable = mask_non_executable(original)
    known_columns = {value.casefold(): value for value in column_patterns.values()}
    for match in _QUOTED_COMPARISON_PREFIX.finditer(original):
        if executable[match.start():match.end()] != original[match.start():match.end()]:
            continue
        position = match.end()
        if position >= len(original) or original[position] not in "'\"":
            continue
        quote = original[position]
        position += 1
        value_chars: list[str] = []
        closed = False
        while position < len(original):
            character = original[position]
            if character == "\\" and position + 1 < len(original):
                value_chars.extend((character, original[position + 1]))
                position += 2
                continue
            if character == quote:
                if position + 1 < len(original) and original[position + 1] == quote:
                    value_chars.append(quote)
                    position += 2
                    continue
                closed = True
                position += 1
                break
            value_chars.append(character)
            position += 1
        if not closed:
            continue
        raw_column, operator = match.groups()
        value = "".join(value_chars)
        column = known_columns.get(raw_column.casefold(), raw_column)
        if quote == "'":
            literal = quote + value.replace("'", "''") + quote
        else:
            literal = "'" + value.replace("'", "''") + "'"
        normalized_operator = {
            "is": "=",
            "isn't": "!=",
            "is not": "!=",
            "not": "!=",
            "<>": "!=",
        }.get(operator.casefold(), operator)
        quoted.append(f"{column} {normalized_operator} {literal}")
    return quoted


def extract_conditions(
    text: str,
    original: str,
    column_patterns: Dict[str, str],
) -> list:
    """Extract WHERE conditions with enhanced parsing including boolean expressions.

    Moved verbatim from ``nl2sql_legacy._extract_conditions_enhanced``.
    ``column_patterns`` replaces ``self.COLUMN_PATTERNS``.
    """
    # Use the structured boolean extractor first — it correctly handles
    # multiple predicates connected by AND/OR while preserving precedence.
    boolean_conditions = extract_boolean_conditions(text)
    if boolean_conditions:
        return boolean_conditions

    conditions = _quoted_comparisons(original, column_patterns)
    executable_original = mask_non_executable(original)
    executable_text = mask_non_executable(text)
    numbers = re.findall(r"-?\d+(?:\.\d*)?", executable_original)
    condition_column = _column_for_text(executable_text, column_patterns)

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
        ([">=", "大于等于", "不小于", "至少", "greater than or equal to", "larger than or equal to"], ">="),
        (["<=", "小于等于", "不大于", "最多", "less than or equal to", "smaller than or equal to"], "<="),
        (["<>", "!=", "不等于", "不是", "不为", "not equal", "isn't", "doesn't equal"], "!="),
        (["大于", "超过", "高于", "多于", "greater", "more than", "above", "over", ">"], ">"),
        (["小于", "低于", "少于", "不足", "less", "less than", "below", "under", "<"], "<"),
        (["等于", "是", "为", "equals", "equal", "="], "="),
    ]
    # For each operator word, the threshold is the number that
    # immediately follows it in the original text (not numbers[0] —
    # '前10条金额大于100' must bind 100 to 大于, not 10).  Multi-char
    # operator words are tried in longest-first order so that e.g.
    # 大于等于 binds its own value before the 大于 row fires on the same
    # text — the legacy row order let the shorter 大于 substring steal
    # an 大于等于 match and emit ">" instead of ">=".
    #
    # The primary value bind (operator word → number directly after it)
    # is the canonical form.  When that bind fails but an operator word
    # is still present (e.g. 'greater than 5' — number follows 'than',
    # not 'greater'), a fallback binds the column before the operator
    # word to the first number after it.  This keeps the legacy
    # operator-word + numbers[0] behavior for English phrases while
    # correcting the Chinese case where the operator word sits between
    # the column and the threshold number.
    for keywords, op in comparisons:
        bound_value = None
        matched_keyword = None
        # Primary bind: the number that immediately follows the operator
        # word itself (Chinese-style adjacency, e.g. '大于100').
        # Longest keyword first so '大于等于' never yields to '大于'.
        for keyword in sorted(keywords, key=len, reverse=True):
            if keyword not in executable_original:
                continue
            m = re.search(
                re.escape(keyword) + r"\s*(-?\d+(?:\.\d*)?)",
                executable_original,
            )
            if m:
                bound_value = m.group(1)
                matched_keyword = keyword
                break
        # Second bind: the number at the END of the operator phrase
        # (English "greater than 100" / "greater than or equal to 100"
        # — the value follows "than"/"to", not the operator's head word).
        # The Top-N count that precedes the whole phrase (numbers[0] =
        # "10" in "top 10 …") must never win this slot.
        if bound_value is None:
            for keyword in sorted(keywords, key=len, reverse=True):
                if keyword not in executable_original:
                    continue
                m = re.search(
                    re.escape(keyword)
                    + r"(?:\s+than\s+|\s+or\s+equal\s+to\s+|\s+than\s+or\s+equal\s+to\s+)?(-?\d+(?:\.\d*)?)",
                    executable_original,
                    re.IGNORECASE,
                )
                if m:
                    bound_value = m.group(1)
                    matched_keyword = keyword
                    break
        if matched_keyword is not None and bound_value is None and numbers:
            bound_value = numbers[0]
        if bound_value is not None:
            col = condition_column or "column"
            conditions.append(f"{col} {op} {bound_value}")
            break
        # Fallback: operator word present but no number is directly or
        # tail-adjacent to it — bind the column named before the operator
        # word to the first available number.
        if any(k in executable_original for k in keywords) and numbers:
            col = condition_column or "column"
            conditions.append(f"{col} {op} {numbers[0]}")
            break

    if any(keyword in executable_text for keyword in ["之间", "范围", "between", "from...to"]):
        if len(numbers) >= 2:
            col = condition_column or "column"
            conditions.append(f"{col} BETWEEN {numbers[0]} AND {numbers[1]}")

    if any(keyword in executable_text for keyword in ["包含", "含有", "contains", "like", "includes"]):
        text_match = re.search(
            r"(?<![\w$])([A-Za-z_][A-Za-z0-9_$]*)\s+"
            r"(?:contains|containing|includes|including)\s+"
            r"(?:the\s+)?([^,;，。；]+?)(?=\s+(?:and|or)\b|[,;，。；]|$)",
            original,
            re.IGNORECASE,
        )
        cn_text_match = re.search(
            r"(名称|名字|标题|描述|分类|品牌)\s*(?:包含|含有|包括)\s*([^且并或者和，,。；]+)",
            original,
        )
        match = re.search(r"[\"']([^\"']+)[\"']", original)
        if text_match:
            raw_column, raw_value = text_match.groups()
            column = next(
                (value for value in column_patterns.values() if value.casefold() == raw_column.casefold()),
                raw_column,
            )
            value = raw_value.strip().strip("'\"")
            if value:
                conditions.append(f"{column} LIKE '%{value.replace(chr(39), chr(39) * 2)}%'")
        elif cn_text_match:
            raw_column, raw_value = cn_text_match.groups()
            aliases = {"名称": "name", "名字": "name", "标题": "title", "描述": "description", "分类": "category", "品牌": "brand"}
            conditions.append(f"{aliases[raw_column]} LIKE '%{raw_value.strip().replace(chr(39), chr(39) * 2)}%'")
        elif match:
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

    date_col = "created_at" if "created_at" in executable_text else "date"
    if "今天" in executable_text or "today" in executable_text:
        conditions.append(f"{date_col} = CURRENT_DATE")
    elif "昨天" in executable_text or "yesterday" in executable_text:
        conditions.append(f"{date_col} = DATE_SUB(CURRENT_DATE, 1)")
    elif "前天" in executable_text or "day before" in executable_text:
        conditions.append(f"{date_col} = DATE_SUB(CURRENT_DATE, 2)")
    elif "明天" in executable_text or "tomorrow" in executable_text:
        conditions.append(f"{date_col} = DATE_ADD(CURRENT_DATE, 1)")

    time_patterns = [
        (r"(最近|过去|last|past)\s*(\d+)\s*(天|day)", "DAY"),
        (r"(最近|过去|last|past)\s*(\d+)\s*(周|week)", "WEEK"),
        (r"(最近|过去|last|past)\s*(\d+)\s*(月|month)", "MONTH"),
        (r"(最近|过去|last|past)\s*(\d+)\s*(年|year)", "YEAR"),
    ]
    for pattern, unit in time_patterns:
        match = re.search(pattern, executable_text, re.IGNORECASE)
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
        if ("last week" in executable_text or "本周" in executable_text) and "this week" not in executable_text and "本周" not in executable_text:
            conditions.append(f"{date_col} >= DATE_SUB(CURRENT_DATE, 7)")
        if "last month" in executable_text:
            conditions.append(f"{date_col} >= ADD_MONTHS(CURRENT_DATE, -1)")
        if "last year" in executable_text:
            conditions.append(f"{date_col} >= ADD_MONTHS(CURRENT_DATE, -12)")

    if "本周" in executable_text or "this week" in executable_text:
        conditions.append(f"WEEKOFYEAR({date_col}) = WEEKOFYEAR(CURRENT_DATE)")
    if "本月" in executable_text or "this month" in executable_text:
        conditions.append(
            f"MONTH({date_col}) = MONTH(CURRENT_DATE) AND YEAR({date_col}) = YEAR(CURRENT_DATE)"
        )
    if "本年" in executable_text or "this year" in executable_text:
        conditions.append(f"YEAR({date_col}) = YEAR(CURRENT_DATE)")

    status_conditions = extract_status_conditions(text)
    for status_condition in status_conditions:
        if status_condition.split(" ", 1)[0] not in in_matched_columns:
            conditions.append(status_condition)
    return conditions
