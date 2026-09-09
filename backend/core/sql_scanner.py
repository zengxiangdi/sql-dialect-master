"""Quote/comment-aware helpers for SQL text transforms.

These helpers deliberately do not parse SQL grammar. They ensure text transforms
only operate on executable SQL segments, never inside literals or comments.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
import re


def scan_segments(sql: str) -> Iterator[tuple[str, str]]:
    i = 0
    start = 0
    n = len(sql)
    while i < n:
        ch = sql[i]

        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            if start < i:
                yield "code", sql[start:i]
            j = i + 2
            while j < n and sql[j] not in "\r\n":
                j += 1
            yield "comment", sql[i:j]
            i = j
            start = i
            continue

        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            if start < i:
                yield "code", sql[start:i]
            j = sql.find("*/", i + 2)
            j = n if j < 0 else j + 2
            yield "comment", sql[i:j]
            i = j
            start = i
            continue

        if ch in ("'", '"', "`") or (ch == "[" and "[" in sql[i:]):
            if start < i:
                yield "code", sql[start:i]
            quote = "]" if ch == "[" else ch
            j = i + 1
            while j < n:
                if quote == "'" and sql[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if sql[j] == quote:
                    if j + 1 < n and sql[j + 1] == quote:
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            yield "quoted", sql[i:j]
            i = j
            start = i
            continue

        i += 1

    if start < n:
        yield "code", sql[start:]


def replace_outside(
    sql: str,
    pattern: re.Pattern[str],
    replacement: str | Callable[[re.Match[str]], str],
) -> tuple[str, int]:
    parts: list[str] = []
    count = 0
    for kind, text in scan_segments(sql):
        if kind == "code":
            text, changed = pattern.subn(replacement, text)
            count += changed
        parts.append(text)
    return "".join(parts), count


def mask_non_executable(sql: str) -> str:
    return "".join(
        text if kind == "code" else "".join("\n" if c in "\r\n" else " " for c in text)
        for kind, text in scan_segments(sql)
    )


def top_level_keyword(text: str, keyword: str) -> int:
    wanted = keyword.upper()
    depth = 0
    quote: str | None = None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote is not None:
            if ch == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and text[i:i + len(wanted)].upper() == wanted:
            before = text[i - 1] if i else " "
            after_i = i + len(wanted)
            after = text[after_i] if after_i < len(text) else " "
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                return i
        i += 1
    return -1
