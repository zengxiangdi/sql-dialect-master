"""Compatibility fix for scanner-safe MySQL GROUP_CONCAT conversion."""
from __future__ import annotations

from typing import Tuple, List

from .post_processor import PostProcessor


def _top_level_keyword(text: str, keyword: str) -> int:
    """Find a keyword outside quotes and nested parentheses."""
    upper = text.upper()
    keyword_upper = keyword.upper()
    depth = 0
    quote = False
    i = 0
    while i < len(text):
        char = text[i]
        if char == "'":
            if quote and i + 1 < len(text) and text[i + 1] == "'":
                i += 2
                continue
            quote = not quote
        elif not quote:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif depth == 0 and upper.startswith(keyword_upper, i):
                before = text[i - 1] if i else " "
                after = text[i + len(keyword):] if i + len(keyword) < len(text) else " "
                if before.isspace() and after[:1].isspace():
                    return i
        i += 1
    return -1


def _replace_group_concat_calls(sql: str) -> Tuple[str, bool]:
    """Replace GROUP_CONCAT calls without applying regex to arbitrary SQL."""
    result: list[str] = []
    i = 0
    changed = False
    upper = sql.upper()
    name = "GROUP_CONCAT"

    while i < len(sql):
        if sql[i] == "'":
            start = i
            i += 1
            while i < len(sql):
                if sql[i] == "'":
                    if i + 1 < len(sql) and sql[i + 1] == "'":
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            result.append(sql[start:i])
            continue

        if upper.startswith(name, i) and (i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_")):
            j = i + len(name)
            while j < len(sql) and sql[j].isspace():
                j += 1
            if j < len(sql) and sql[j] == "(":
                depth = 0
                quote = False
                k = j
                while k < len(sql):
                    char = sql[k]
                    if char == "'":
                        if quote and k + 1 < len(sql) and sql[k + 1] == "'":
                            k += 2
                            continue
                        quote = not quote
                    elif not quote:
                        if char == "(":
                            depth += 1
                        elif char == ")":
                            depth -= 1
                            if depth == 0:
                                args = sql[j + 1:k].strip()
                                converted = _convert_args(args)
                                result.append(converted)
                                changed = changed or converted != sql[i:k + 1]
                                i = k + 1
                                break
                    k += 1
                else:
                    result.append(sql[i:])
                    break
                continue

        result.append(sql[i])
        i += 1

    return "".join(result), changed


def _convert_args(args: str) -> str:
    separator = ","
    separator_pos = _top_level_keyword(args, "SEPARATOR")
    if separator_pos >= 0:
        separator_text = args[separator_pos + len("SEPARATOR"):].strip()
        if len(separator_text) >= 2 and separator_text[0] == "'" and separator_text[-1] == "'":
            separator = separator_text[1:-1].replace("''", "'")
        args = args[:separator_pos].rstrip()

    order_pos = _top_level_keyword(args, "ORDER BY")
    order_expr = None
    if order_pos >= 0:
        order_expr = args[order_pos + len("ORDER BY"):].strip()
        args = args[:order_pos].rstrip()

    distinct = False
    if args.upper().startswith("DISTINCT"):
        rest = args[len("DISTINCT"):]
        if not rest or rest[0].isspace():
            distinct = True
            args = rest.strip()

    if not args:
        return "GROUP_CONCAT()"

    value = f"DISTINCT ({args})::TEXT" if distinct else f"{args}::TEXT"
    escaped_separator = separator.replace("'", "''")
    result = f"STRING_AGG({value}, '{escaped_separator}'"
    if order_expr:
        result += f" ORDER BY {order_expr}"
    return result + ")"


def _convert_group_concat(self: PostProcessor, sql: str) -> Tuple[str, List[str]]:
    result, changed = _replace_group_concat_calls(sql)
    return result, ["Converted GROUP_CONCAT to STRING_AGG"] if changed else []


_ORIGINAL_PROCESS = PostProcessor.process


def _process_with_scanner(self: PostProcessor, sql: str, source: str, target: str):
    result, notes = _ORIGINAL_PROCESS(self, sql, source, target)
    if source.lower() == "mysql" and target.lower() == "postgres":
        result, changed = _replace_group_concat_calls(result)
        if changed:
            notes = list(notes) + ["Converted GROUP_CONCAT to STRING_AGG"]
    return result, notes


if not getattr(PostProcessor, "_sdm_group_concat_fix", False):
    PostProcessor._convert_group_concat = _convert_group_concat
    PostProcessor.process = _process_with_scanner
    PostProcessor._sdm_group_concat_fix = True
