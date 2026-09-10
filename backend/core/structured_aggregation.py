"""Scanner-backed structural rewrites for aggregation function rules."""
from __future__ import annotations

import re
from typing import Callable

from .function_call_scanner import replace_function_calls
from .p1_sql_scanner import mask_non_executable, split_top_level_args
from .rules import TransformRule


def _top_level_keyword(text: str, keyword: str) -> int:
    masked = mask_non_executable(text)
    wanted = keyword.upper()
    depth = 0
    for index, char in enumerate(masked):
        if char == "(":
            depth += 1
            continue
        if char == ")" and depth:
            depth -= 1
            continue
        if depth == 0 and masked[index:index + len(wanted)].upper() == wanted:
            before = masked[index - 1] if index else " "
            after_index = index + len(wanted)
            after = masked[after_index] if after_index < len(masked) else " "
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                return index
    return -1


def _replace_string_agg(args: str, original: str, target: str) -> str:
    values = split_top_level_args(args)
    if len(values) != 2 or not all(values):
        return original
    expression, separator = values
    if target == "mysql":
        return f"GROUP_CONCAT({expression} SEPARATOR {separator})"
    return f"STRING_AGG({expression}::TEXT, {separator})"


def _replace_group_concat(args: str, original: str) -> str:
    separator_position = _top_level_keyword(args, "SEPARATOR")
    before_separator = args if separator_position < 0 else args[:separator_position].rstrip()
    separator = "','" if separator_position < 0 else args[separator_position + len("SEPARATOR"):].strip()
    if not separator:
        return original

    order_position = _top_level_keyword(before_separator, "ORDER BY")
    expression = before_separator if order_position < 0 else before_separator[:order_position].rstrip()
    order_by = None if order_position < 0 else before_separator[order_position + len("ORDER BY"):].strip()
    distinct = bool(re.match(r"^DISTINCT\b", expression, re.IGNORECASE))
    if distinct:
        expression = re.sub(r"^DISTINCT\s+", "", expression, count=1, flags=re.IGNORECASE).strip()
    if not expression:
        return original

    prefix = "DISTINCT " if distinct else ""
    result = f"STRING_AGG({prefix}{expression}::TEXT, {separator}"
    if order_by:
        result += f" ORDER BY {order_by}"
    return result + ")"


def _replace_listagg(sql: str) -> tuple[str, bool]:
    function_name = "LISTAGG"
    masked = mask_non_executable(sql)
    name_upper = function_name.upper()
    length = len(sql)
    result: list[str] = []
    cursor = 0
    index = 0
    applied = False

    while index < length:
        if masked[index:index + len(function_name)].upper() != name_upper:
            index += 1
            continue
        if index > 0 and (masked[index - 1].isalnum() or masked[index - 1] == "_"):
            index += 1
            continue

        open_index = index + len(function_name)
        while open_index < length and masked[open_index].isspace():
            open_index += 1
        if open_index >= length or masked[open_index] != "(":
            index += 1
            continue

        depth = 0
        close_index = open_index
        while close_index < length:
            char = masked[close_index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    break
            close_index += 1
        if close_index >= length or depth != 0:
            index += 1
            continue

        suffix_index = close_index + 1
        while suffix_index < length and masked[suffix_index].isspace():
            suffix_index += 1
        within_group = "WITHIN" + " " + "GROUP"
        if masked[suffix_index:suffix_index + len(within_group)].upper() != within_group:
            index += 1
            continue
        suffix_index += len(within_group)
        while suffix_index < length and masked[suffix_index].isspace():
            suffix_index += 1
        if suffix_index >= length or masked[suffix_index] != "(":
            index += 1
            continue

        order_depth = 0
        order_close = suffix_index
        while order_close < length:
            char = masked[order_close]
            if char == "(":
                order_depth += 1
            elif char == ")":
                order_depth -= 1
                if order_depth == 0:
                    break
            order_close += 1
        if order_close >= length or order_depth != 0:
            index += 1
            continue

        args = sql[open_index + 1:close_index]
        order_clause = sql[suffix_index + 1:order_close].strip()
        if not re.match(r"^ORDER\s+BY\b", order_clause, re.IGNORECASE):
            index += 1
            continue

        values = split_top_level_args(args)
        if len(values) != 2 or not all(values):
            index += 1
            continue

        result.append(sql[cursor:index])
        result.append(f"ARRAY_JOIN(COLLECT_LIST({values[0]}), {values[1]})")
        cursor = order_close + 1
        index = cursor
        applied = True

    if not applied:
        return sql, False
    result.append(sql[cursor:])
    return "".join(result), True


def install_structured_aggregation_rules() -> None:
    """Install structural aggregation handlers after legacy patches are loaded."""
    current_apply = TransformRule.apply
    if getattr(current_apply, "_sdm_structured_aggregation", False):
        return

    handlers: dict[str, Callable[[TransformRule, str], tuple[str, bool]]] = {}

    def string_agg_mysql(self: TransformRule, sql: str) -> tuple[str, bool]:
        if not self.enabled:
            return sql, False
        applied = False

        def replacer(args: str, original: str) -> str:
            nonlocal applied
            transformed = _replace_string_agg(args, original, "mysql")
            applied = applied or transformed != original
            return transformed

        return replace_function_calls(sql, "STRING_AGG", replacer), applied

    def group_concat_postgres(self: TransformRule, sql: str) -> tuple[str, bool]:
        if not self.enabled:
            return sql, False
        applied = False

        def replacer(args: str, original: str) -> str:
            nonlocal applied
            transformed = _replace_group_concat(args, original)
            applied = applied or transformed != original
            return transformed

        return replace_function_calls(sql, "GROUP_CONCAT", replacer), applied

    handlers["tsql_string_agg_to_mysql"] = string_agg_mysql
    handlers["postgres_string_agg_to_mysql"] = string_agg_mysql
    handlers["mysql_group_concat_to_postgres"] = group_concat_postgres

    def listagg_handler(self: TransformRule, sql: str) -> tuple[str, bool]:
        if not self.enabled:
            return sql, False
        return _replace_listagg(sql)

    handlers["oracle_listagg_to_hive"] = listagg_handler

    def apply(self: TransformRule, sql: str) -> tuple[str, bool]:
        handler = handlers.get(self.name)
        if handler is not None:
            return handler(self, sql)
        return current_apply(self, sql)

    apply._sdm_structured_aggregation = True  # type: ignore[attr-defined]
    TransformRule.apply = apply


__all__ = ["install_structured_aggregation_rules"]
